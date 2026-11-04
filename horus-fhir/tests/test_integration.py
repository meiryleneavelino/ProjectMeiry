"""Integration tests against the running horus-fhir stack, seen from the Mac
(where the browser runs). They write to fhir-channel: run tools.py reset-demo
afterwards for a clean demo.

  .venv/bin/python -m pytest -q tests/test_integration.py
"""
import json
import socket
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import tools  # noqa: E402  (compose helpers: run commands inside horus-fhir-net)

API = "http://127.0.0.1:8099"


def call(method, path, body=None, token=None):
    token = token if token is not None else (ROOT / ".local" / "api-token").read_text().strip()
    request = urllib.request.Request(API + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            return response.status, json.loads(response.read() or b"null")
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read() or b"null")


@pytest.fixture(scope="module")
def demo():
    """Steps 0-3 of the scenario through the API (reuses the policy if it exists)."""
    code, status = call("GET", "/status")
    if code != 200 or not status["chain"]["ok"]:
        pytest.skip("horus-fhir is not running: python3 tools.py start")
    code, _ = call("POST", "/admin/policies?as=adm-001", {})
    assert code in (200, 409)
    assert call("POST", "/service-requests?as=phy-001")[0] == 200
    code, consent = call("POST", "/consents?as=pat-001", {"serviceRequestId": "sr-001", "grantee": "phy-001", "days": 30})
    assert code == 200, consent
    reports = {}
    for request_id in ("sr-001", "sr-002"):
        code, result = call("POST", "/lab/results?as=lab-001", {"serviceRequestId": request_id})
        assert code == 200, result
        reports[request_id] = result["fhir"]["diagnosticReport"]
    return {"consent": consent, "a": reports["sr-001"], "b": reports["sr-002"]}


def access(persona, report):
    return call("GET", f"/reports/{report}?as={persona}")


def test_permit_delivers_the_exam_and_records_everything(demo):
    code, outcome = access("phy-001", demo["a"])
    assert code == 200 and outcome["reason"] == "PERMIT" and outcome["hashCheck"]["match"]
    assert outcome["resource"]["diagnosticReport"]["id"] == demo["a"]
    components = [step["component"] for step in outcome["decisionTrace"]]
    assert {"PDP", "PAP", "PIP"} <= set(components) and components.index("PAP") < components.index("PDP", 1)
    assert call("GET", f"/transactions/{outcome['txId']}")[1]["validationCode"] == "VALID"
    timeline = call("GET", "/audit")[1]
    assert any(item["name"] == "AuditEvent" and item["txId"] == outcome["txId"] for item in timeline)
    assert any(item["name"] == "AccessDecision" and item["txId"] == outcome["txId"] for item in timeline)


@pytest.mark.parametrize("persona,report,reason", [("phy-001", "b", "NO_CONSENT"), ("phy-002", "a", "WRONG_GRANTEE"),
                                                   ("lab-001", "a", "NOT_PHYSICIAN"), ("pat-001", "a", "NOT_PHYSICIAN")])
def test_denials_carry_only_the_reason(demo, persona, report, reason):
    code, outcome = access(persona, demo[report])
    assert code == 403 and outcome["reason"] == reason and "resource" not in outcome
    assert outcome["txId"] and outcome["auditEventId"]  # the denial is on-chain and audited too


def test_wrong_persona_is_refused_by_the_chaincode(demo):
    code, body = call("POST", "/admin/policies?as=phy-001", {})
    assert code == 403 and body["component"] == "ledger" and "role=admin" in body["detail"]


def test_consent_deadline_is_recorded_on_chain(demo):
    # Expiry itself is proven by the Go test with the transaction timestamp
    # (TestDenyExpired); a real network cannot move its clock forward.
    code, consent = call("POST", "/consents?as=pat-001", {"serviceRequestId": "sr-002", "grantee": "phy-002", "days": 1})
    assert code == 200
    deadline = datetime.fromisoformat(consent["onChain"]["validUntil"].replace("Z", "+00:00"))
    assert abs(deadline - (datetime.now(timezone.utc) + timedelta(days=1))) < timedelta(minutes=5)
    code, outcome = access("phy-002", demo["b"])
    assert code == 200 and outcome["reason"] == "PERMIT"


def test_hashes_verify_against_fhir(demo):
    assert call("GET", f"/verify/report/{demo['a']}")[1]["match"]
    assert call("GET", f"/verify/consent/{demo['consent']['fhir']['id']}")[1]["match"]


def test_tampered_fhir_content_is_not_delivered(demo):
    code, outcome = access("phy-001", demo["a"])
    observation = outcome["resource"]["observations"][0]
    tampered = {key: value for key, value in observation.items() if key != "meta"}
    tampered["meta"] = {"security": observation["meta"]["security"]}
    tampered["valueQuantity"]["value"] = 42.0
    tools.tools("curl -fsS -X PUT -H 'Content-Type: application/fhir+json' "
                f"--data '{json.dumps(tampered)}' http://fhir-hapi:8080/fhir/Observation/{observation['id']} -o /dev/null")
    code, outcome = access("phy-001", demo["a"])
    assert code == 403 and outcome["reason"] == "HASH_MISMATCH" and "resource" not in outcome
    assert outcome["hashCheck"]["match"] is False
    assert call("GET", f"/verify/report/{demo['a']}")[1]["match"] is False


def test_revocation_takes_effect(demo):
    consent_id = demo["consent"]["fhir"]["id"]
    code, revoked = call("POST", f"/consents/{consent_id}/revoke?as=pat-001")
    assert code == 200 and revoked["onChain"]["status"] == "revoked"
    # Any other still-active consent sr-001 -> phy-001 (earlier runs) would
    # rightly keep permitting: revoke them all before checking.
    for item in call("GET", "/consents")[1]:
        chain = item["onChain"] or {}
        if chain.get("status") == "active" and chain["serviceRequestId"] == "sr-001" and chain["grantee"] == "phy-001":
            assert call("POST", f"/consents/{item['id']}/revoke?as=pat-001")[0] == 200
    code, outcome = access("phy-001", demo["a"])
    assert code == 403 and outcome["reason"] == "REVOKED"
    verification = call("GET", f"/verify/consent/{consent_id}")[1]
    assert verification["match"] and verification["fhirStatus"] == "inactive"


# ---- the PEP cannot be bypassed --------------------------------------------

def test_only_the_pep_is_published_on_the_host():
    lines = subprocess.run([tools.DOCKER, "ps", "--filter", "label=com.docker.compose.project=horus-fhir",
                            "--format", "{{.Names}} {{.Ports}}"], capture_output=True, text=True, check=True).stdout.splitlines()
    published = [line for line in lines if "->" in line]
    assert published == [line for line in lines if line.startswith("fhir-api ")]
    assert "127.0.0.1:8099->8000/tcp" in published[0] and "0.0.0.0" not in published[0]


@pytest.mark.parametrize("port", [8090, 8080, 7050, 7051, 7053, 7054, 9999])
def test_fhir_and_fabric_ports_are_closed_on_the_host(port):
    with socket.socket() as probe:
        probe.settimeout(1)
        assert probe.connect_ex(("127.0.0.1", port)) != 0, f"port {port} must not be reachable from the Mac"


def test_api_has_no_fhir_passthrough_and_needs_a_token():
    for path in ("/fhir/Patient", "/Patient/patient-001", "/fhir/metadata", "/Observation"):
        assert call("GET", path)[0] == 404, path
    assert call("GET", "/status", token="wrong-token-wrong-token-wrong")[0] == 401


def test_vite_proxies_only_the_pep():
    config = (ROOT.parent / "horus-sandbox-frontend" / "vite.config.ts").read_text()
    assert '"/fhir-api"' in config and "http://127.0.0.1:8099" in config
    assert "8090" not in config and "fhir-hapi" not in config
