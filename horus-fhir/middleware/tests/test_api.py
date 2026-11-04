"""Endpoint tests of the PEP API with in-memory FHIR and ledger (no network)."""
import copy
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import hashing
from app.fabric_client import LedgerError
from app.fhir_client import FhirError
from app.main import create_app
from app.settings import Settings

TOKEN = "t" * 32
AUTH = {"Authorization": f"Bearer {TOKEN}"}


class FakeFhir:
    """Versioned in-memory FHIR server (enough for the API flows)."""

    def __init__(self, log):
        self.versions, self.log, self.created = {}, log, 0

    def _store(self, resource):
        key = (resource["resourceType"], resource["id"])
        history = self.versions.setdefault(key, [])
        stored = copy.deepcopy(resource)
        stored["meta"] = {**stored.get("meta", {}), "versionId": str(len(history) + 1), "lastUpdated": "2026-11-04T10:00:00Z"}
        history.append(stored)
        return copy.deepcopy(stored)

    def metadata(self):
        return {"fhirVersion": "4.0.1"}

    def put(self, resource):
        self.log.append(f"fhir.put {resource['resourceType']}")
        return self._store(resource)

    def create(self, resource):
        self.created += 1
        self.log.append(f"fhir.create {resource['resourceType']}")
        return self._store({**resource, "id": str(self.created)})

    def transaction(self, resources):
        self.log.append("fhir.transaction")
        for resource in resources:
            self._store(resource)

    def read(self, kind, resource_id):
        if (kind, resource_id) not in self.versions:
            raise FhirError(404, "not found")
        return copy.deepcopy(self.versions[(kind, resource_id)][-1])

    def history(self, kind, resource_id):
        return [copy.deepcopy(item) for item in reversed(self.versions[(kind, resource_id)])]

    def search(self, kind, **_):
        return [copy.deepcopy(history[-1]) for (resource_type, _id), history in self.versions.items() if resource_type == kind]


class FakeLedger:
    def __init__(self, log):
        self.log, self.policies, self.consents, self.resources = log, {}, {}, {}
        self.decision = {"permitted": False, "reason": "NO_CONSENT", "trace": []}
        self.tx = 0

    def _receipt(self, result):
        self.tx += 1
        return {"result": result, "txId": f"{self.tx:064x}", "blockNumber": self.tx, "timings": {"totalMs": 1.0}}

    def submit(self, persona, function, *args):
        self.log.append(f"ledger.submit {function} as {persona}")
        if function == "PIP:RevokeConsent":
            self.consents[args[0]]["status"] = "revoked"
            return self._receipt(self.consents[args[0]])
        raise AssertionError(function)

    def evaluate(self, persona, function, *args):
        if function == "PAP:GetPolicy":
            self.log.append("ledger.evaluate PAP:GetPolicy")
            if args[0] not in self.policies:
                raise LedgerError(404, "notfound", "policy does not exist")
            return self.policies[args[0]]
        if function == "PIP:GetConsent":
            return self.consents[args[0]]
        if function == "PIP:GetResource":
            return self.resources[args[0]]
        return {"PIP:ListConsents": list(self.consents.values()), "PIP:ListResources": list(self.resources.values()),
                "ListEvents": [], "PAP:ListPolicies": {"policies": list(self.policies.values()), "bindings": []}}[function]

    def create_policy(self, persona, policy_id, body, update=False):
        if persona != "adm-001":
            raise LedgerError(403, "forbidden", "requires role=admin issued by HospitalMSP")
        self.policies[policy_id] = {"policyId": policy_id, "version": 1, **body}
        return self._receipt(self.policies[policy_id])

    def put_consent(self, persona, consent_id, request_id, patient, grantee, valid_until, consent_hash):
        self.log.append(f"ledger.submit PIP:PutConsent as {persona}")
        self.consents[consent_id] = {"consentId": consent_id, "serviceRequestId": request_id, "patientPseudo": patient,
                                     "grantee": grantee, "validUntil": valid_until, "consentHash": consent_hash,
                                     "status": "active", "txId": "c" * 64}
        return self._receipt(self.consents[consent_id])

    def put_resource(self, persona, report_id, request_id, patient, report_hash, label, lab_id):
        self.log.append(f"ledger.submit PIP:PutResource as {persona}")
        self.resources[report_id] = {"reportId": report_id, "reportHash": report_hash, "txId": "r" * 64,
                                     "serviceRequestId": request_id, "patientPseudo": patient, "securityLabel": label}
        return self._receipt(self.resources[report_id])

    def bind_resource(self, persona, report_id, policy_id):
        self.log.append(f"ledger.submit PAP:BindResource as {persona}")
        return self._receipt({"target": f"resource:{report_id}", "policyId": policy_id})

    def request_access(self, persona, report_id, action="read"):
        self.log.append(f"ledger.submit PDP:RequestAccess as {persona}")
        return self._receipt(dict(self.decision))

    def chain(self):
        return {"height": self.tx + 4, "currentBlockHash": "00"}

    def transaction(self, tx_id):
        return {"txId": tx_id, "validationCode": "VALID", "valid": True}


@pytest.fixture()
def world():
    config = json.loads((Path(__file__).parent.parent / "config/personas.json").read_text())
    settings = Settings(fhir_base="fake", gateway_url="fake", gateway_token=TOKEN, api_token=TOKEN,
                        personas=config["personas"], exams=config["exams"], notice=config["notice"])
    log = []
    fhir, ledger = FakeFhir(log), FakeLedger(log)
    with TestClient(create_app(settings, fhir, ledger)) as client:
        log.clear()  # drop the startup seed
        yield client, fhir, ledger, log


def test_token_is_required(world):
    client, *_ = world
    assert client.get("/health").status_code == 200
    assert client.get("/status").status_code == 401
    assert client.get("/status", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.get("/status", headers=AUTH).status_code == 200


def test_unknown_persona(world):
    client, *_ = world
    assert client.get("/reports/dr-1?as=abc-123", headers=AUTH).status_code == 422
    assert client.get("/reports/dr-1?as=../etc", headers=AUTH).status_code == 422


def test_no_route_reaches_fhir_directly(world):
    client, *_ = world
    for path in ("/fhir/Patient", "/Patient/patient-001", "/fhir/metadata", "/DiagnosticReport/dr-1", "/fhir-api/Patient"):
        assert client.get(path, headers=AUTH).status_code == 404, path


def test_denied_read_carries_no_content(world):
    client, fhir, ledger, log = world
    response = client.get("/reports/dr-1?as=phy-002", headers=AUTH)
    body = response.json()
    assert response.status_code == 403 and body["reason"] == "NO_CONSENT" and "resource" not in body
    assert log[0] == "ledger.submit PDP:RequestAccess as phy-002" and log[-1] == "fhir.create AuditEvent"


def test_role_precheck_happens_before_any_fhir_write(world):
    client, fhir, ledger, log = world
    client.post("/service-requests?as=phy-001", headers=AUTH)
    log.clear()
    response = client.post("/consents?as=phy-001", headers=AUTH, json={"serviceRequestId": "sr-001", "grantee": "phy-001"})
    assert response.status_code == 403 and log == []
    assert not fhir.search("Consent")
    response = client.post("/lab/results?as=pat-001", headers=AUTH, json={"serviceRequestId": "sr-001"})
    assert response.status_code == 403 and log == []


def test_policy_write_refused_by_ledger_maps_to_403(world):
    client, *_ = world
    response = client.post("/admin/policies?as=phy-001", headers=AUTH, json={})
    assert response.status_code == 403 and response.json()["component"] == "ledger"


def test_lab_result_order_fhir_then_pip_then_pap(world):
    client, fhir, ledger, log = world
    client.post("/service-requests?as=phy-001", headers=AUTH)
    ledger.policies["ConsentRequiredPolicy"] = {"policyId": "ConsentRequiredPolicy", "version": 1}
    log.clear()
    response = client.post("/lab/results?as=lab-001", headers=AUTH, json={"serviceRequestId": "sr-001"})
    assert response.status_code == 200, response.json()
    order = [entry for entry in log if entry.startswith(("fhir.transaction", "ledger"))]
    assert order == ["ledger.evaluate PAP:GetPolicy", "fhir.transaction", "ledger.submit PIP:PutResource as lab-001",
                     "ledger.submit PAP:BindResource as adm-001"]
    report_id = response.json()["fhir"]["diagnosticReport"]
    report = fhir.read("DiagnosticReport", report_id)
    observations = [fhir.read(*item["reference"].split("/")) for item in report["result"]]
    assert ledger.resources[report_id]["reportHash"] == hashing.report_hash(report, observations)
    assert ledger.resources[report_id]["patientPseudo"] == "pat-001"


def test_lab_result_without_policy_writes_nothing(world):
    client, fhir, ledger, log = world
    client.post("/service-requests?as=phy-001", headers=AUTH)
    log.clear()
    response = client.post("/lab/results?as=lab-001", headers=AUTH, json={"serviceRequestId": "sr-001"})
    assert response.status_code == 404 and "fhir.transaction" not in log


def test_consent_hash_and_verify_after_revocation(world):
    client, fhir, ledger, log = world
    client.post("/service-requests?as=phy-001", headers=AUTH)
    granted = client.post("/consents?as=pat-001", headers=AUTH, json={"serviceRequestId": "sr-001", "grantee": "phy-001"}).json()
    consent_id = granted["fhir"]["id"]
    assert ledger.consents[consent_id]["consentHash"] == hashing.resource_hash(fhir.read("Consent", consent_id))
    assert granted["consentHash"] == ledger.consents[consent_id]["consentHash"]
    assert client.post(f"/consents/{consent_id}/revoke?as=pat-001", headers=AUTH).status_code == 200
    assert fhir.read("Consent", consent_id)["status"] == "inactive"
    verification = client.get(f"/verify/consent/{consent_id}", headers=AUTH).json()
    assert verification["match"] and verification["matchesVersion"] == "1" and verification["currentVersion"] == "2"
    assert verification["fhirStatus"] == "inactive" and verification["onChainStatus"] == "revoked"


def test_patient_cannot_consent_on_another_patients_request(world):
    client, fhir, ledger, log = world
    fhir.put({"resourceType": "ServiceRequest", "id": "sr-009", "status": "active", "intent": "order",
              "subject": {"reference": "Patient/patient-999"}, "requester": {"reference": "Practitioner/practitioner-001"}})
    response = client.post("/consents?as=pat-001", headers=AUTH, json={"serviceRequestId": "sr-009", "grantee": "phy-001"})
    assert response.status_code == 403 and not fhir.search("Consent")
