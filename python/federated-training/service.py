import argparse
import hmac
import json
import logging
import os
import secrets
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID, uuid4

import httpx
import uvicorn
from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Path as ApiPath
from fastapi.responses import FileResponse
from kubernetes import client, config
from kubernetes.client.exceptions import ApiException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from model import ALGORITHM, FEATURES, ORGANIZATIONS, aggregate, export_model, prepare_dataset
from model import initial_model, train_local
from integration import send_via_sidecar, verify_capability


logger = logging.getLogger("federated-training")
state_lock = threading.RLock()
ROLE = os.getenv("ROLE", "coordinator")
STATE_ROOT = Path(os.getenv("STATE_ROOT", "/state"))
API_TOKEN = os.getenv("API_TOKEN", "")
INTEGRATED = os.getenv("DYNAMOS_INTEGRATED") == "true"
TERMINAL = {"completed", "failed", "cancelled", "interrupted"}


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Weights(StrictModel):
    coefficients: list[Annotated[float, Field(allow_inf_nan=False, ge=-1000000, le=1000000)]] = Field(min_length=4, max_length=4)
    intercept: float = Field(allow_inf_nan=False, ge=-1000000, le=1000000)


class TrainingRequest(StrictModel):
    algorithm: Literal["logistic-regression-v1"] = ALGORITHM
    organizations: list[Literal["UVA", "VU", "TUDELFT"]] = Field(min_length=2, max_length=3)
    dataset_id: Literal["synthetic-local-v1"] = "synthetic-local-v1"
    rounds: int = Field(default=3, ge=1, le=10, strict=True)
    local_epochs: int = Field(default=2, ge=1, le=5, strict=True)
    authorization: str | None = None

    @field_validator("organizations")
    @classmethod
    def unique_organizations(cls, organizations):
        if len(set(organizations)) != len(organizations):
            raise ValueError("Organizations must be distinct")
        return organizations


class RoundRequest(StrictModel):
    run_id: UUID
    round_number: int = Field(ge=1, le=10, strict=True)
    local_epochs: int = Field(ge=1, le=5, strict=True)
    model: Weights
    authorization: str | None = None


class LocalUpdate(Weights):
    samples: int = Field(ge=1, le=10000, strict=True)
    accuracy: float = Field(ge=0, le=1, allow_inf_nan=False)
    validation_loss: float = Field(ge=0, le=100, allow_inf_nan=False)


def authorize(authorization: Annotated[str | None, Header()] = None):
    if not API_TOKEN or not hmac.compare_digest(authorization or "", f"Bearer {API_TOKEN}"):
        raise HTTPException(401, "Authentication required")


def write_json(path, value):
    with state_lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(value), encoding="utf-8")
        temporary.replace(path)


def read_json(path):
    with state_lock:
        if not path.is_file():
            raise HTTPException(404, "Not found")
        return json.loads(path.read_text(encoding="utf-8"))


def run_path(run_id):
    return STATE_ROOT / "runs" / str(UUID(str(run_id))) / "status.json"


def round_name(request):
    return f"training-{request.run_id.hex[:16]}-r{request.round_number}"


def agent_clients():
    config.load_incluster_config()
    return client.CoreV1Api(), client.BatchV1Api()


def worker_job(name, namespace, image):
    return {
        "apiVersion": "batch/v1", "kind": "Job",
        "metadata": {"name": name, "labels": {"app": "federated-training", "role": "worker"}},
        "spec": {
            "backoffLimit": 0, "activeDeadlineSeconds": 180, "ttlSecondsAfterFinished": 600,
            "template": {
                "metadata": {"labels": {"app": "federated-training", "role": "worker"},
                             "annotations": {"linkerd.io/inject": "disabled"}},
                "spec": {
                    "automountServiceAccountToken": False, "restartPolicy": "Never",
                    "securityContext": {"runAsNonRoot": True, "runAsUser": 10001, "fsGroup": 10001,
                                        "seccompProfile": {"type": "RuntimeDefault"}},
                    "containers": [{
                        "name": "trainer", "image": image, "imagePullPolicy": "IfNotPresent",
                        "args": ["trainer"],
                        "env": [{"name": "ORGANIZATION", "value": namespace.upper()},
                                {"name": "CALLBACK_URL", "value": f"http://training-agent.{namespace}.svc.cluster.local:8080"},
                                {"name": "OPENBLAS_NUM_THREADS", "value": "1"}],
                        "resources": {"requests": {"cpu": "100m", "memory": "128Mi"},
                                      "limits": {"cpu": "500m", "memory": "512Mi"}},
                        "securityContext": {"allowPrivilegeEscalation": False, "readOnlyRootFilesystem": True,
                                            "capabilities": {"drop": ["ALL"]}},
                        "volumeMounts": [{"name": "dataset", "mountPath": "/data", "readOnly": True},
                                         {"name": "input", "mountPath": "/input", "readOnly": True},
                                         {"name": "temporary", "mountPath": "/tmp"}],
                    }],
                    "volumes": [{"name": "dataset", "persistentVolumeClaim": {"claimName": "training-data", "readOnly": True}},
                                {"name": "input", "configMap": {"name": name}},
                                {"name": "temporary", "emptyDir": {"sizeLimit": "32Mi"}}],
                },
            },
        },
    }


class CancelledRun(Exception):
    pass


def check_cancelled(run_id):
    if read_json(run_path(run_id))["status"] == "cancelling":
        raise CancelledRun()


def publish_progress(path, record):
    with state_lock:
        if read_json(path)["status"] == "cancelling":
            raise CancelledRun()
        write_json(path, record)


def execute_training(run_id, request):
    path = run_path(run_id)
    record = read_json(path)
    headers = {"Authorization": f"Bearer {API_TOKEN}"}
    active_rounds = []
    try:
        record["status"] = "running"
        publish_progress(path, record)
        global_model = initial_model()
        with httpx.Client(timeout=65, headers=headers, trust_env=False) as connection:
            for round_number in range(1, request.rounds + 1):
                check_cancelled(run_id)
                if INTEGRATED:
                    approval = connection.post(os.environ["DYNAMOS_GATEWAY_URL"] + "/api/v1/ml/revalidate",
                                               headers={"X-Training-Authorization": request.authorization})
                    approval.raise_for_status()
                active_rounds = []
                for organization in request.organizations:
                    check_cancelled(run_id)
                    base_url = f"http://training-agent.{organization.lower()}.svc.cluster.local:8080"
                    round_request = {
                        "run_id": str(run_id), "round_number": round_number,
                        "local_epochs": request.local_epochs, "model": global_model,
                    }
                    if INTEGRATED:
                        round_request["authorization"] = request.authorization
                    response = connection.post(f"{base_url}/rounds", json=round_request)
                    response.raise_for_status()
                    active_rounds.append((organization, base_url, response.json()["name"]))
                updates = []
                observations = []
                for organization, base_url, name in active_rounds:
                    deadline = time.monotonic() + 240
                    while True:
                        check_cancelled(run_id)
                        response = connection.get(f"{base_url}/rounds/{name}")
                        response.raise_for_status()
                        state = response.json()
                        if state["status"] == "completed":
                            update = LocalUpdate.model_validate(state["update"]).model_dump()
                            updates.append(update)
                            observations.append({"organization": organization, "job": name,
                                                 "namespace": organization.lower(), "status": "completed",
                                                 "accuracy": update["accuracy"], "validation_loss": update["validation_loss"]})
                            break
                        if state["status"] == "failed" or time.monotonic() > deadline:
                            raise RuntimeError("A local training job failed or timed out")
                        time.sleep(1)
                global_model = aggregate(updates)
                check_cancelled(run_id)
                record["completed_rounds"] = round_number
                record["round_history"].append({"round": round_number, "organizations": observations})
                publish_progress(path, record)
            with state_lock:
                check_cancelled(run_id)
                if INTEGRATED:
                    approval = connection.post(os.environ["DYNAMOS_GATEWAY_URL"] + "/api/v1/ml/revalidate",
                                               headers={"X-Training-Authorization": request.authorization})
                    approval.raise_for_status()
                export_model(path.parent / "model.json", global_model, request.organizations, request.rounds)
                record["status"] = "completed"
                write_json(path, record)
    except CancelledRun:
        record["status"] = "cancelled"
    except Exception:
        logger.exception("Federated run failed: %s", run_id)
        record["status"] = "failed"
        record["error"] = "Training failed; check the coordinator and organization jobs."
    finally:
        if record["status"] != "completed":
            with httpx.Client(timeout=5, headers=headers, trust_env=False) as connection:
                for _, base_url, name in active_rounds:
                    try:
                        connection.delete(f"{base_url}/rounds/{name}")
                    except httpx.HTTPError:
                        logger.warning("Could not cancel local job %s", name)
        with state_lock:
            if read_json(path)["status"] == "cancelling":
                record["status"] = "cancelled"
            write_json(path, record)


@asynccontextmanager
async def lifespan(application):
    if not API_TOKEN:
        raise RuntimeError("API_TOKEN must be configured")
    if ROLE == "coordinator":
        for path in (STATE_ROOT / "runs").glob("*/status.json"):
            record = read_json(path)
            if record["status"] not in TERMINAL:
                record["status"] = "interrupted"
                record["error"] = "Coordinator restarted; start a new run."
                write_json(path, record)
    yield


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


@app.get("/health")
def health():
    return {"status": "ok", "role": ROLE}


if ROLE == "coordinator":
    @app.get("/catalog", dependencies=[Depends(authorize)])
    def catalog():
        return {"organizations": list(ORGANIZATIONS),
                "algorithms": [{"id": ALGORITHM, "name": "Logistic regression (FedAvg)"}],
                "dataset_id": "synthetic-local-v1", "network_verified": os.getenv("NETWORK_VERIFIED") == "true",
                "integration": "dynamos" if INTEGRATED else "standalone"}

    @app.get("/runs", dependencies=[Depends(authorize)])
    def list_runs():
        return [read_json(path) for path in sorted((STATE_ROOT / "runs").glob("*/status.json"), reverse=True)]

    @app.post("/runs", status_code=202, dependencies=[Depends(authorize)])
    def create_run(request: TrainingRequest, tasks: BackgroundTasks):
        if os.getenv("NETWORK_VERIFIED") != "true":
            raise HTTPException(503, "Isolation tests must pass before training is enabled")
        grant = None
        if INTEGRATED:
            try:
                grant = verify_capability(request.authorization, os.environ["TRAINING_SIGNING_KEY"], request.model_dump())
            except (ValueError, KeyError, TypeError):
                raise HTTPException(403, "DYNAMOS authorization and composition are required")
        with state_lock:
            if any(record["status"] not in TERMINAL for record in list_runs()):
                raise HTTPException(409, "Another training run is active")
            run_id = UUID(grant["run_id"]) if grant else uuid4()
            record = {"id": str(run_id), "status": "queued", "algorithm": request.algorithm,
                      "organizations": request.organizations, "rounds": request.rounds,
                      "dataset_id": request.dataset_id, "local_epochs": request.local_epochs,
                      "integration": "dynamos" if INTEGRATED else "standalone",
                      "completed_rounds": 0, "round_history": [], "created_at": time.time()}
            write_json(run_path(run_id), record)
        tasks.add_task(execute_training, run_id, request)
        return record

    @app.get("/runs/{run_id}", dependencies=[Depends(authorize)])
    def get_run(run_id: UUID):
        return read_json(run_path(run_id))

    @app.post("/runs/{run_id}/cancel", dependencies=[Depends(authorize)])
    def cancel_run(run_id: UUID):
        with state_lock:
            record = read_json(run_path(run_id))
            if record["status"] not in TERMINAL:
                record["status"] = "cancelling"
                write_json(run_path(run_id), record)
            return record

    @app.get("/runs/{run_id}/model", dependencies=[Depends(authorize)])
    def download_model(run_id: UUID):
        path = run_path(run_id)
        if read_json(path)["status"] != "completed":
            raise HTTPException(409, "Final model is not available")
        return FileResponse(path.parent / "model.json", media_type="application/json",
                            filename=f"global-model-{run_id}.json")

elif ROLE == "agent":
    @app.post("/rounds", status_code=202, dependencies=[Depends(authorize)])
    def create_round(request: RoundRequest):
        namespace = os.environ["ORGANIZATION"].lower()
        if namespace.upper() not in ORGANIZATIONS:
            raise HTTPException(500, "Invalid organization configuration")
        name = round_name(request)
        core_api, batch_api = agent_clients()
        callback_token = secrets.token_urlsafe(32)
        payload = {**request.model_dump(mode="json"), "callback_token": callback_token, "name": name}
        path = STATE_ROOT / "rounds" / f"{name}.json"
        with state_lock:
            if path.exists():
                raise HTTPException(409, "Round already exists")
            write_json(path, {"status": "pending", "callback_token": callback_token})
        try:
            core_api.create_namespaced_config_map(namespace, {
                "metadata": {"name": name, "labels": {"app": "federated-training"}},
                "data": {"request.json": json.dumps(payload)},
            })
            job = batch_api.create_namespaced_job(namespace, worker_job(name, namespace, os.environ["TRAINER_IMAGE"]))
            core_api.patch_namespaced_config_map(name, namespace, {"metadata": {"ownerReferences": [{
                "apiVersion": "batch/v1", "kind": "Job", "name": name, "uid": job.metadata.uid,
            }]}})
        except ApiException:
            write_json(path, {"status": "failed", "callback_token": callback_token})
            logger.exception("Could not create training job")
            raise HTTPException(500, "Could not create local training job")
        return {"name": name, "namespace": namespace}

    @app.get("/rounds/{name}", dependencies=[Depends(authorize)])
    def get_round(name: Annotated[str, ApiPath(pattern=r"^training-[a-f0-9]{16}-r[1-9][0-9]?$" )]):
        state = read_json(STATE_ROOT / "rounds" / f"{name}.json")
        _, batch_api = agent_clients()
        job = batch_api.read_namespaced_job(name, os.environ["ORGANIZATION"].lower())
        if job.status.failed or any(condition.type == "Failed" and condition.status == "True"
                                    for condition in (job.status.conditions or [])):
            return {"status": "failed"}
        if state["status"] == "completed" and job.status.succeeded:
            return {"status": "completed", "update": state["update"]}
        return {"status": "running"}

    @app.delete("/rounds/{name}", dependencies=[Depends(authorize)])
    def delete_round(name: Annotated[str, ApiPath(pattern=r"^training-[a-f0-9]{16}-r[1-9][0-9]?$" )]):
        core_api, batch_api = agent_clients()
        namespace = os.environ["ORGANIZATION"].lower()
        for operation in (lambda: batch_api.delete_namespaced_job(name, namespace, propagation_policy="Foreground"),
                          lambda: core_api.delete_namespaced_config_map(name, namespace)):
            try:
                operation()
            except ApiException as error:
                if error.status != 404:
                    raise HTTPException(500, "Could not delete job")
        return {"status": "cancelled"}

    @app.post("/rounds/{name}/result")
    def receive_result(name: Annotated[str, ApiPath(pattern=r"^training-[a-f0-9]{16}-r[1-9][0-9]?$" )],
                       update: LocalUpdate, authorization: Annotated[str | None, Header()] = None):
        path = STATE_ROOT / "rounds" / f"{name}.json"
        with state_lock:
            state = read_json(path)
            if state["status"] != "pending" or not hmac.compare_digest(
                    authorization or "", f"Bearer {state['callback_token']}"):
                raise HTTPException(403, "Invalid or consumed result capability")
            write_json(path, {"status": "completed", "update": update.model_dump()})
        return {"status": "accepted"}


def run_trainer():
    request = json.loads(Path("/input/request.json").read_text())
    validated = RoundRequest.model_validate({key: request[key] for key in
                                            ("run_id", "round_number", "local_epochs", "model")})
    update = train_local("/data/dataset.csv", validated.model.model_dump(),
                         validated.local_epochs, validated.round_number)
    if INTEGRATED:
        send_via_sidecar(update, request, os.environ["ORGANIZATION"])
        return
    url = f"{os.environ['CALLBACK_URL']}/rounds/{request['name']}/result"
    for attempt in range(3):
        try:
            response = httpx.post(url, json=update, timeout=15, trust_env=False,
                                  headers={"Authorization": f"Bearer {request['callback_token']}"})
            response.raise_for_status()
            return
        except httpx.HTTPError:
            if attempt == 2:
                raise
            time.sleep(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("serve", "trainer", "seed"), default="serve", nargs="?")
    arguments = parser.parse_args()
    if arguments.mode == "seed":
        prepare_dataset(os.environ["ORGANIZATION"], "/data/dataset.csv")
    elif arguments.mode == "trainer":
        run_trainer()
    else:
        uvicorn.run(app, host="0.0.0.0", port=8080, workers=1)