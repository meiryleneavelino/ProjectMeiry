"""horus-fhir API: the only entry point to FHIR (the PEP) plus the flows that
feed the PAP and the PIP. Identity is SIMULATED with ?as=<persona>: it picks
which wallet certificate signs. This is NOT authentication (future: SMART on
FHIR or Keycloak). Every call needs the API bearer token."""
import hmac
import re
import time
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from . import hashing, resources
from .fabric_client import FabricClient, LedgerError
from .fhir_client import FhirClient, FhirError
from .pep import PEP
from .settings import CHANNEL_LABEL, POLICY_ID, Settings

CONSENT_REQUIRED = {
    "description": "Restricted results need an active, unexpired consent of the result's patient for the requesting physician",
    "actions": ["read"],
    "rules": [{"type": "subjectRole", "value": "physician"},
              {"type": "consent", "checks": ["exists", "grantee", "patient", "active", "notExpired"]}],
}


class PolicyInput(BaseModel):
    policyId: str = Field(default=POLICY_ID, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    policy: dict = Field(default_factory=lambda: dict(CONSENT_REQUIRED))


class ConsentInput(BaseModel):
    serviceRequestId: str = Field(pattern=r"^sr-[0-9]{3}$")
    grantee: str = Field(pattern=r"^phy-[0-9]{3}$")
    days: int = Field(default=30, ge=1, le=365)


class ResultValue(BaseModel):
    code: str = Field(pattern=r"^[0-9]{1,7}-[0-9]$")
    display: str | None = Field(default=None, max_length=120)
    value: float | None = None
    unit: str | None = Field(default=None, max_length=20)
    text: str | None = Field(default=None, max_length=120)


class LabInput(BaseModel):
    serviceRequestId: str = Field(pattern=r"^sr-[0-9]{3}$")
    securityLabel: str = Field(default="R", pattern=r"^[A-Za-z0-9_-]{1,32}$")
    policyId: str = POLICY_ID
    values: list[ResultValue] | None = None


def create_app(settings: Settings | None = None, fhir: FhirClient | None = None, ledger: FabricClient | None = None):
    settings = settings or Settings.load()
    fhir = fhir or FhirClient(settings.fhir_base)
    ledger = ledger or FabricClient(settings.gateway_url, settings.gateway_token)
    pep = PEP(fhir, ledger, settings)

    @asynccontextmanager
    async def lifespan(_):
        for attempt in range(60):  # seed the fictitious step-1 resources (idempotent PUTs)
            try:
                for resource in resources.seed_resources():
                    fhir.put(resource)
                break
            except Exception:
                time.sleep(3)
        yield

    app = FastAPI(title="horus-fhir PEP", lifespan=lifespan)

    @app.middleware("http")
    async def token(request: Request, call_next):
        if request.url.path != "/health":
            supplied = request.headers.get("authorization", "")
            if not hmac.compare_digest(supplied, f"Bearer {settings.api_token}"):
                return JSONResponse({"detail": "invalid API token"}, status_code=401)
        return await call_next(request)

    @app.exception_handler(LedgerError)
    async def ledger_error(_, error: LedgerError):
        return JSONResponse({"detail": error.detail, "kind": error.kind, "component": "ledger"},
                            status_code=error.status if error.status in (401, 403, 404, 409, 422) else 503)

    @app.exception_handler(FhirError)
    async def fhir_error(_, error: FhirError):
        return JSONResponse({"detail": error.detail, "component": "fhir"},
                            status_code=404 if error.status == 404 else 502)

    def persona(as_: str = Query(alias="as", pattern=r"^[a-z]{3}-[0-9]{3}$")):
        try:
            return settings.persona(as_)
        except KeyError:
            raise HTTPException(422, f"unknown persona {as_}")

    def require(who: dict, role: str):
        # UX pre-check only, before writing FHIR; the chaincode is the authority.
        if who["role"] != role:
            raise HTTPException(403, f"{who['id']} is not role={role}; the chaincode would refuse this write")

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/personas")
    def personas():
        return {"notice": settings.notice, "personas": [settings.persona(key) for key in settings.personas],
                "exams": settings.exams}

    @app.get("/status")
    def status():
        result = {"ledger": CHANNEL_LABEL, "identity": "simulated (as=), not authentication"}
        try:
            result["fhir"] = {"ok": True, "fhirVersion": fhir.metadata().get("fhirVersion")}
        except Exception as error:  # noqa: BLE001 - report, do not fail
            result["fhir"] = {"ok": False, "error": str(error)[:200]}
        try:
            result["chain"] = {"ok": True, **ledger.chain()}
        except LedgerError as error:
            result["chain"] = {"ok": False, "error": error.detail}
        return result

    # ---- PAP --------------------------------------------------------------
    @app.post("/admin/policies")
    def create_policy(data: PolicyInput, update: bool = False, who: dict = Depends(persona)):
        receipt = ledger.create_policy(who["id"], data.policyId, data.policy, update=update)
        return {"component": "PAP", "policy": receipt["result"], "txId": receipt["txId"],
                "blockNumber": receipt["blockNumber"], "timings": receipt["timings"]}

    @app.get("/policies")
    def policies():
        return ledger.evaluate("adm-001", "PAP:ListPolicies")

    # ---- step 1: orders (FHIR only, nothing on-chain) -------------------------
    @app.post("/service-requests")
    def order_exams(who: dict = Depends(persona)):
        require(who, "physician")
        existing = {item["id"]: item for item in fhir.search("ServiceRequest")}
        created = []
        for request in resources.service_requests(who["fhir"]):
            if request["id"] in existing:  # idempotent: keep the original order
                created.append(existing[request["id"]])
            else:
                created.append(fhir.put(request))
        return {"component": None, "ledger": "no on-chain record (step 1)",
                "serviceRequests": [{"id": item["id"], "exam": settings.exams[item["id"]]["label"],
                                     "requester": item["requester"]["reference"], "versionId": item["meta"]["versionId"]}
                                    for item in created]}

    @app.get("/service-requests")
    def list_orders():
        return [{"id": item["id"], "exam": settings.exams.get(item["id"], {}).get("label", item["id"]),
                 "requester": item["requester"]["reference"], "patient": item["subject"]["reference"],
                 "status": item["status"]} for item in sorted(fhir.search("ServiceRequest"), key=lambda item: item["id"])]

    # ---- PIP: consent -------------------------------------------------------
    @app.post("/consents")
    def grant_consent(data: ConsentInput, who: dict = Depends(persona)):
        require(who, "patient")
        if data.grantee not in settings.personas:
            raise HTTPException(422, f"unknown grantee {data.grantee}")
        grantee = settings.persona(data.grantee)
        request = fhir.read("ServiceRequest", data.serviceRequestId)
        if request["subject"]["reference"] != who["fhir"]:
            raise HTTPException(403, "this ServiceRequest belongs to another patient")
        start, end = resources.valid_until(data.days)
        consent_id = resources.opaque("consent")
        stored = fhir.put(resources.consent(consent_id, who["fhir"], grantee["fhir"], data.serviceRequestId, start, end))
        consent_hash = hashing.resource_hash(fhir.read("Consent", consent_id))
        receipt = ledger.put_consent(who["id"], consent_id, data.serviceRequestId, who["id"], data.grantee,
                                     resources.iso(end), consent_hash)
        return {"component": "PIP", "fhir": {"id": consent_id, "versionId": stored["meta"]["versionId"]},
                "consentHash": consent_hash, "onChain": receipt["result"], "txId": receipt["txId"],
                "blockNumber": receipt["blockNumber"], "timings": receipt["timings"]}

    @app.post("/consents/{consent_id}/revoke")
    def revoke_consent(consent_id: str, who: dict = Depends(persona)):
        require(who, "patient")
        receipt = ledger.submit(who["id"], "PIP:RevokeConsent", consent_id)  # the ledger decides first
        current = fhir.read("Consent", consent_id)
        current["status"] = "inactive"
        stored = fhir.put(current)
        return {"component": "PIP", "onChain": receipt["result"], "txId": receipt["txId"],
                "blockNumber": receipt["blockNumber"], "fhir": {"id": consent_id, "status": "inactive",
                                                                "versionId": stored["meta"]["versionId"]}}

    @app.get("/consents")
    def consents():
        chain = {item["consentId"]: item for item in ledger.evaluate("adm-001", "PIP:ListConsents")}
        items = []
        for consent in fhir.search("Consent"):
            items.append({"id": consent["id"], "fhirStatus": consent["status"], "patient": consent["patient"]["reference"],
                          "serviceRequestId": consent["provision"]["data"][0]["reference"]["reference"].split("/")[1],
                          "grantee": consent["provision"]["actor"][0]["reference"]["reference"],
                          "validUntil": consent["provision"]["period"]["end"], "onChain": chain.get(consent["id"])})
        return sorted(items, key=lambda item: item["id"])

    # ---- PIP + PAP: lab results ----------------------------------------------
    @app.post("/lab/results")
    def lab_result(data: LabInput, who: dict = Depends(persona)):
        require(who, "lab")
        ledger.evaluate("adm-001", "PAP:GetPolicy", data.policyId)  # fail early: step 0 must exist
        request = fhir.read("ServiceRequest", data.serviceRequestId)
        patient_pseudo = settings.pseudonym_of(request["subject"]["reference"])
        values = [item.model_dump(exclude_none=True) for item in data.values] if data.values else \
            resources.DEFAULT_RESULTS[data.serviceRequestId]
        report, observations, provenance = resources.lab_results(request, data.securityLabel, who["fhir"], values)
        fhir.transaction([*observations, report, provenance])
        stored_report, stored_observations = pep.read_report(report["id"])
        report_hash = hashing.report_hash(stored_report, stored_observations)
        pip = ledger.put_resource(who["id"], report["id"], data.serviceRequestId, patient_pseudo, report_hash,
                                  data.securityLabel, who["id"])
        pap = ledger.bind_resource("adm-001", report["id"], data.policyId)  # admin identity, as specified
        return {"fhir": {"diagnosticReport": report["id"], "observations": [item["id"] for item in observations],
                         "provenance": provenance["id"]},
                "reportHash": report_hash,
                "pip": {"component": "PIP", "txId": pip["txId"], "blockNumber": pip["blockNumber"], "onChain": pip["result"]},
                "pap": {"component": "PAP", "txId": pap["txId"], "blockNumber": pap["blockNumber"], "onChain": pap["result"]}}

    @app.get("/results")
    def results():
        chain = {item["reportId"]: item for item in ledger.evaluate("adm-001", "PIP:ListResources")}
        items = []
        for report in fhir.search("DiagnosticReport"):
            request_id = report["basedOn"][0]["reference"].split("/")[1]
            items.append({"id": report["id"], "serviceRequestId": request_id,
                          "exam": settings.exams.get(request_id, {}).get("label", request_id),
                          "securityLabel": [item["code"] for item in report.get("meta", {}).get("security", [])],
                          "issued": report.get("issued"), "onChain": chain.get(report["id"])})
        return sorted(items, key=lambda item: item["issued"] or "")

    # ---- PEP -------------------------------------------------------------
    @app.get("/reports/{report_id}")
    def read_report(report_id: str, who: dict = Depends(persona)):
        if not resources_id_ok(report_id):
            raise HTTPException(422, "invalid report id")
        outcome = pep.enforce_read(report_id, who["id"])
        return JSONResponse(outcome.body(), status_code=outcome.status)

    # ---- audit and verification ---------------------------------------------
    @app.get("/audit")
    def audit():
        timeline = [{"source": "on-chain", "name": item["name"], "component": item["component"],
                     "timestamp": item["timestamp"], "txId": item["txId"], "actor": item["actor"], "detail": item["detail"]}
                    for item in ledger.evaluate("adm-001", "ListEvents")]
        for event in fhir.search("AuditEvent", _sort="-date"):
            details = {item["type"]: item.get("valueString") for item in event["entity"][0].get("detail", [])}
            timeline.append({"source": "off-chain", "name": "AuditEvent", "component": "PEP", "id": event["id"],
                             "timestamp": event["recorded"], "txId": details.get("fabricTxId"),
                             "actor": event["agent"][0].get("altId"),
                             "detail": {"what": event["entity"][0]["what"]["reference"], **details}})
        return sorted(timeline, key=lambda item: item["timestamp"])

    @app.get("/verify/{kind}/{resource_id}")
    def verify(kind: str, resource_id: str):
        if kind == "report":
            on_chain = ledger.evaluate("adm-001", "PIP:GetResource", resource_id)
            report, observations = pep.read_report(resource_id)
            computed = hashing.report_hash(report, observations)
            return {"kind": kind, "id": resource_id, "onChain": on_chain["reportHash"], "computed": computed,
                    "match": computed == on_chain["reportHash"], "txId": on_chain["txId"]}
        if kind == "consent":
            on_chain = ledger.evaluate("adm-001", "PIP:GetConsent", resource_id)
            versions = fhir.history("Consent", resource_id)
            matched = [item["meta"]["versionId"] for item in versions
                       if hashing.resource_hash(item) == on_chain["consentHash"]]
            current = versions[0] if versions else None
            return {"kind": kind, "id": resource_id, "onChain": on_chain["consentHash"],
                    "computedCurrent": hashing.resource_hash(current) if current else None,
                    "matchesVersion": matched[0] if matched else None, "match": bool(matched),
                    "currentVersion": current["meta"]["versionId"] if current else None,
                    "onChainStatus": on_chain["status"], "fhirStatus": current["status"] if current else None}
        raise HTTPException(422, "kind must be report or consent")

    @app.get("/transactions/{tx_id}")
    def transaction(tx_id: str):
        return ledger.transaction(tx_id)

    return app


def resources_id_ok(value: str) -> bool:
    return re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", value) is not None
