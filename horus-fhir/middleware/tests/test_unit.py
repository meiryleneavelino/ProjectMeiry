"""Unit tests for the hash rules and the PEP, with in-memory FHIR and ledger."""
import copy
import unittest

from app import hashing, resources
from app.fabric_client import LedgerError
from app.fhir_client import FhirError
from app.pep import PEP


class Settings:
    personas = {"phy-001": {"label": "Dra. Ana", "role": "physician", "msp": "HospitalMSP",
                            "fhir": "Practitioner/practitioner-001"}}

    def persona(self, persona_id):
        return {"id": persona_id, **self.personas[persona_id]}


class FakeFhir:
    def __init__(self):
        self.store, self.created = {}, []

    def read(self, kind, resource_id):
        if (kind, resource_id) not in self.store:
            raise FhirError(404, "gone")
        resource = copy.deepcopy(self.store[(kind, resource_id)])
        resource["meta"] = {**resource.get("meta", {}), "versionId": "1", "lastUpdated": "2026-11-04T10:00:00Z"}
        return resource

    def create(self, resource):
        self.created.append(resource)
        return {**resource, "id": str(len(self.created))}


class FakeLedger:
    def __init__(self, decision=None, error=None):
        self.decision, self.error, self.calls = decision, error, []

    def request_access(self, persona, report_id, action):
        self.calls.append((persona, report_id, action))
        if self.error:
            raise self.error
        return {"result": self.decision, "txId": "f" * 64, "blockNumber": 9, "timings": {"totalMs": 1}}


def stored_report():
    request = {"id": "sr-001", "subject": {"reference": "Patient/patient-001"},
               "code": {"coding": [{"system": "http://loinc.org", "code": "58410-2"}]}}
    report, observations, _ = resources.lab_results(request, "R", "Organization/org-lab-001",
                                                     resources.DEFAULT_RESULTS["sr-001"])
    fhir = FakeFhir()
    for item in [report, *observations]:
        fhir.store[(item["resourceType"], item["id"])] = item
    return fhir, report, observations


class HashingTest(unittest.TestCase):
    def test_canonical_json(self):
        self.assertEqual(hashing.canonical({"b": 1, "a": "é"}), '{"a":"é","b":1}'.encode())

    def test_server_meta_and_narrative_are_ignored(self):
        resource = {"resourceType": "Consent", "id": "c1", "status": "active", "meta": {"security": [{"code": "R"}]}}
        noisy = {**resource, "text": {"div": "<div/>"},
                 "meta": {"security": [{"code": "R"}], "versionId": "3", "lastUpdated": "x", "source": "#y"}}
        self.assertEqual(hashing.resource_hash(resource), hashing.resource_hash(noisy))
        self.assertNotEqual(hashing.resource_hash(resource), hashing.resource_hash({**resource, "status": "inactive"}))

    def test_report_hash_covers_observation_values(self):
        _, report, observations = stored_report()
        changed = copy.deepcopy(observations)
        changed[0]["valueQuantity"]["value"] = 7.1
        self.assertNotEqual(hashing.report_hash(report, observations), hashing.report_hash(report, changed))
        self.assertEqual(hashing.report_hash(report, observations), hashing.report_hash(report, observations[::-1]))


class PepTest(unittest.TestCase):
    def decision(self, permitted, reason, report_hash):
        return {"permitted": permitted, "reason": reason, "reportHash": report_hash, "policyId": "ConsentRequiredPolicy",
                "policyVersion": 1, "trace": [{"component": "PDP"}]}

    def test_permit_delivers_resource_and_audits(self):
        fhir, report, observations = stored_report()
        ledger = FakeLedger(self.decision(True, "PERMIT", hashing.report_hash(report, observations)))
        outcome = PEP(fhir, ledger, Settings()).enforce_read(report["id"], "phy-001")
        self.assertEqual((outcome.status, outcome.permitted), (200, True))
        self.assertEqual(outcome.body()["resource"]["diagnosticReport"]["id"], report["id"])
        audit = fhir.created[-1]
        self.assertEqual(audit["outcome"], "0")
        self.assertIn({"type": "fabricTxId", "valueString": "f" * 64}, audit["entity"][0]["detail"])

    def test_deny_never_reads_fhir_nor_returns_content(self):
        fhir, report, _ = stored_report()
        fhir.read = lambda *args: self.fail("a denied request must not read FHIR")
        outcome = PEP(fhir, FakeLedger(self.decision(False, "NO_CONSENT", None)), Settings()).enforce_read(report["id"], "phy-001")
        self.assertEqual((outcome.status, outcome.reason), (403, "NO_CONSENT"))
        self.assertNotIn("resource", outcome.body())
        self.assertEqual(fhir.created[-1]["outcome"], "4")

    def test_tampered_content_is_refused(self):
        fhir, report, observations = stored_report()
        ledger = FakeLedger(self.decision(True, "PERMIT", hashing.report_hash(report, observations)))
        fhir.store[("Observation", observations[0]["id"])]["valueQuantity"]["value"] = 99
        outcome = PEP(fhir, ledger, Settings()).enforce_read(report["id"], "phy-001")
        self.assertEqual((outcome.status, outcome.reason, outcome.hash_check["match"]), (403, "HASH_MISMATCH", False))
        self.assertNotIn("resource", outcome.body())

    def test_ledger_down_means_deny(self):
        fhir, report, _ = stored_report()
        outcome = PEP(fhir, FakeLedger(error=LedgerError(503, "unavailable", "down")), Settings()).enforce_read(report["id"], "phy-001")
        self.assertEqual((outcome.status, outcome.permitted, outcome.reason), (503, False, "LEDGER_UNAVAILABLE"))


if __name__ == "__main__":
    unittest.main()
