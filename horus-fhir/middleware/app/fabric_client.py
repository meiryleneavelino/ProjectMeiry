"""Calls to the PAP, PIP and PDP of the fhir-abac chaincode through fhir-gateway
(Fabric Gateway SDK, Go). Only IDs, hashes, deadlines, statuses and decisions
are ever sent: no clinical content goes to the ledger."""
import json

import httpx


class LedgerError(Exception):
    def __init__(self, status: int, kind: str, detail: str):
        super().__init__(f"{kind}: {detail}")
        self.status, self.kind, self.detail = status, kind, detail


class FabricClient:
    def __init__(self, url: str, token: str, client: httpx.Client | None = None):
        self.url = url.rstrip("/")
        self.http = client or httpx.Client(timeout=120, headers={"Authorization": f"Bearer {token}"})

    def _call(self, method: str, path: str, body=None):
        try:
            response = self.http.request(method, f"{self.url}{path}", json=body)
        except httpx.HTTPError as error:
            raise LedgerError(503, "unavailable", f"fhir-gateway unreachable: {error}") from error
        data = response.json() if response.content else {}
        if response.status_code >= 400:
            raise LedgerError(response.status_code, data.get("kind", "unavailable"), data.get("detail", response.text[:300]))
        return data

    def submit(self, persona: str, function: str, *args: str) -> dict:
        """Endorse (HospitalMSP AND LabMSP), order, wait for commit. Returns
        {"result", "txId", "blockNumber", "timings"}."""
        receipt = self._call("POST", "/submit", {"as": persona, "function": function, "args": list(args)})
        receipt["result"] = receipt.get("result")
        return receipt

    def evaluate(self, persona: str, function: str, *args: str):
        return self._call("POST", "/evaluate", {"as": persona, "function": function, "args": list(args)})["result"]

    def chain(self) -> dict:
        return self._call("GET", "/chain")

    def transaction(self, tx_id: str) -> dict:
        return self._call("GET", f"/transactions/{tx_id}")

    # --- PAP -------------------------------------------------------------
    def create_policy(self, persona: str, policy_id: str, body: dict, update=False):
        function = "PAP:UpdatePolicy" if update else "PAP:CreatePolicy"
        return self.submit(persona, function, policy_id, json.dumps(body, ensure_ascii=False))

    def bind_resource(self, persona: str, report_id: str, policy_id: str):
        return self.submit(persona, "PAP:BindResource", f"resource:{report_id}", policy_id)

    # --- PIP -------------------------------------------------------------
    def put_consent(self, persona, consent_id, service_request_id, patient_pseudo, grantee, valid_until, consent_hash):
        return self.submit(persona, "PIP:PutConsent", consent_id, service_request_id, patient_pseudo, grantee,
                           valid_until, consent_hash)

    def put_resource(self, persona, report_id, service_request_id, patient_pseudo, report_hash, label, lab_id):
        return self.submit(persona, "PIP:PutResource", report_id, service_request_id, patient_pseudo, report_hash,
                           label, lab_id)

    # --- PDP -------------------------------------------------------------
    def request_access(self, persona: str, report_id: str, action: str = "read"):
        return self.submit(persona, "PDP:RequestAccess", report_id, action)
