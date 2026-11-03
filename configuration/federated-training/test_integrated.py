import json
import time
import urllib.error

from manage import LOCAL, kubectl
from test_run import expect_error, main as train_and_download, request


def agreement(organization, value=None):
    arguments = ["exec", "etcd-0", "-n", "core", "--", "/usr/local/bin/etcdctl",
                 "--endpoints=http://127.0.0.1:2379"]
    key = f"/policyEnforcer/agreements/{organization}"
    if value is None:
        return json.loads(kubectl(*arguments, "get", key, "--print-value-only", capture=True))
    kubectl(*arguments, "put", key, json.dumps(value), capture=True)


def main():
    _, catalog = request("/catalog")
    assert catalog["integration"] == "dynamos" and catalog["network_verified"]
    original = agreement("TUDELFT")
    revoked = json.loads(json.dumps(original))
    revoked["relations"]["sandbox-researcher"]["allowedAlgorithms"] = []
    try:
        agreement("TUDELFT", revoked)
        expect_error("/runs", 403, {"algorithm": "logistic-regression-v1", "organizations": ["UVA", "TUDELFT"],
                                   "dataset_id": "synthetic-local-v1", "rounds": 3, "local_epochs": 2})
        print("PASS: DYNAMOS policy denied training before Job creation")
    finally:
        agreement("TUDELFT", original)
    train_and_download()
    record = json.loads((LOCAL / "training-report.json").read_text())
    assert record["integration"] == "dynamos"
    for observations in record["round_history"]:
        for entry in observations["organizations"]:
            job = json.loads(kubectl("get", f"job/{entry['job']}", "-n", entry["namespace"], "-o", "json", capture=True))
            pod = job["spec"]["template"]["spec"]
            assert [container["name"] for container in pod["containers"]] == ["trainer", "sidecar"]
            assert not pod["automountServiceAccountToken"]
            assert pod["containers"][0]["volumeMounts"][0]["readOnly"]
    run_id = record["id"]
    try:
        agreement("TUDELFT", revoked)
        expect_error(f"/runs/{run_id}/model", 403)
        print("PASS: DYNAMOS policy denied model download after revocation")
    finally:
        agreement("TUDELFT", original)
    _, active = request("/runs", {"algorithm": "logistic-regression-v1", "organizations": ["UVA", "TUDELFT"],
                                 "dataset_id": "synthetic-local-v1", "rounds": 3, "local_epochs": 2})
    try:
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            _, state = request(f"/runs/{active['id']}")
            if state["completed_rounds"] >= 1:
                break
            if state["status"] in ("failed", "cancelled", "interrupted"):
                raise RuntimeError("Run failed before the revocation test")
            time.sleep(1)
        else:
            raise RuntimeError("First federated round timed out")
        agreement("TUDELFT", revoked)
        while time.monotonic() < deadline:
            _, state = request(f"/runs/{active['id']}")
            if state["status"] == "failed":
                break
            if state["status"] == "completed":
                raise RuntimeError("Revoked training unexpectedly completed")
            time.sleep(1)
        else:
            raise RuntimeError("Revoked training did not stop")
        print("PASS: active training stopped at policy revalidation; no final download")
    finally:
        agreement("TUDELFT", original)
        request(f"/runs/{active['id']}/cancel", {})
    proof = kubectl("logs", "deployment/training-agent", "-n", "tudelft", "-c", "agent", "--tail=100", capture=True)
    assert "Training result received through DYNAMOS sidecar" in proof
    (LOCAL / "integration-report.json").write_text(json.dumps({
        "status": "passed", "run_id": run_id, "all_workers_have_sidecars": True,
        "denial_before_execution": True, "denial_after_revocation": True,
        "active_revalidation": True, "rabbitmq_result_received": True,
    }, indent=2))
    print("PASS: API -> policy-enforcer -> orchestrator -> DYNAMOS agents -> trainer/sidecar -> RabbitMQ")


if __name__ == "__main__":
    main()