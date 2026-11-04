"""Policy Enforcement Point. It never decides: it asks the PDP (a chaincode
transaction), then enforces the answer. A PERMIT is delivered only if the
content read from FHIR still has the hash the PIP holds on-chain."""
import time
from dataclasses import dataclass, field

from . import hashing, resources
from .fabric_client import FabricClient, LedgerError
from .fhir_client import FhirClient, FhirError


@dataclass
class Enforcement:
    status: int
    permitted: bool
    reason: str
    decision: dict | None = None
    receipt: dict = field(default_factory=dict)
    hash_check: dict | None = None
    resource: dict | None = None
    audit_event_id: str | None = None
    timings: dict = field(default_factory=dict)

    def body(self) -> dict:
        body = {"permitted": self.permitted, "reason": self.reason, "httpStatus": self.status,
                "ledger": "Fabric fhir-channel", "txId": self.receipt.get("txId"),
                "blockNumber": self.receipt.get("blockNumber"),
                "decisionTrace": (self.decision or {}).get("trace", []),
                "policy": {key: (self.decision or {}).get(key) for key in ("policyId", "policyVersion", "policyHash")},
                "hashCheck": self.hash_check, "auditEventId": self.audit_event_id, "timings": self.timings}
        if self.permitted:
            body["resource"] = self.resource  # only delivered on PERMIT
        return body


def ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000, 2)


class PEP:
    def __init__(self, fhir: FhirClient, ledger: FabricClient, settings):
        self.fhir, self.ledger, self.settings = fhir, ledger, settings

    def read_report(self, report_id: str):
        report = self.fhir.read("DiagnosticReport", report_id)
        observations = [self.fhir.read(*item["reference"].split("/", 1)) for item in report.get("result", [])]
        return report, observations

    def enforce_read(self, report_id: str, persona_id: str) -> Enforcement:
        started = time.perf_counter()
        persona = self.settings.persona(persona_id)
        result = Enforcement(status=403, permitted=False, reason="")
        # 1. PEP -> PDP: RequestAccess is a submit, so the decision is on-chain.
        try:
            step = time.perf_counter()
            result.receipt = self.ledger.request_access(persona_id, report_id, "read")
            result.timings["pdpSubmitMs"] = ms(step)
            result.timings["fabric"] = result.receipt.get("timings")
            result.decision = result.receipt["result"]
            result.permitted, result.reason = result.decision["permitted"], result.decision["reason"]
        except LedgerError as error:
            # No decision could be recorded (invalid request or ledger down): deny.
            result.status, result.reason = (503 if error.kind == "unavailable" else 403), f"LEDGER_{error.kind.upper()}"
        # 2. Only on PERMIT: read FHIR, recompute the hash, compare with the PIP's.
        if result.permitted:
            try:
                step = time.perf_counter()
                report, observations = self.read_report(report_id)
                result.timings["fhirReadMs"] = ms(step)
                step = time.perf_counter()
                computed = hashing.report_hash(report, observations)
                result.timings["hashMs"] = ms(step)
                expected = result.decision.get("reportHash")
                result.hash_check = {"onChain": expected, "computed": computed, "match": computed == expected}
                if computed == expected:
                    result.status = 200
                    result.resource = {"diagnosticReport": report, "observations": observations}
                else:
                    result.permitted, result.reason = False, "HASH_MISMATCH"
            except FhirError:
                result.permitted, result.reason = False, "RESOURCE_UNAVAILABLE"
        # 3. Both outcomes are audited off-chain, pointing to the Fabric tx.
        try:
            step = time.perf_counter()
            event = resources.audit_event(persona.get("fhir"), persona_id, report_id, result.permitted, result.reason,
                                          result.receipt.get("txId"), result.receipt.get("blockNumber"))
            result.audit_event_id = self.fhir.create(event)["id"]
            result.timings["auditMs"] = ms(step)
        except FhirError:
            result.audit_event_id = None
        result.timings["totalMs"] = ms(started)
        return result
