import json
import tempfile
import unittest
from pathlib import Path

import httpx

from app.ledger import FabricLedger, LedgerError
from app.reviewer import eligible_reviewers
from app.service import MAX_SUBMISSION_BYTES, Governance
from app.settings import Settings
from fake_ledger import FakeLedger
from sast.contracts import AnalysisError


class GovernanceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.ledger = FakeLedger()
        self.service = Governance(Settings(Path(self.directory.name)), self.ledger)

    def test_eligibility_excludes_researcher_organization(self):
        self.assertEqual(eligible_reviewers(["TUDELFT", "VU", "UVA"], "TUDELFT"), ["UVA", "VU"])
        for selected in (["TUDELFT"], [], ["UVA", "UVA"], ["UNKNOWN"]):
            with self.assertRaises(ValueError):
                eligible_reviewers(selected, "TUDELFT")

    def test_server_does_not_choose_reviewer(self):
        item, reused = self.service.submit(b"value=1\n", ["UVA", "VU", "TUDELFT"])
        self.assertFalse(reused)
        self.assertEqual(item["status"], "drawing")
        self.assertIsNone(item["selection"]["reviewer"])
        self.assertEqual(item["selection"]["eligible"], ["UVA", "VU"])
        self.assertEqual(item["selection"]["excluded"], "TUDELFT")
        self.assertEqual(len(item["receipt"]["tx_id"]), 64)

    def test_duplicate_and_line_endings_reuse_ledger_record(self):
        first, _ = self.service.submit(b"value=1\r\n", ["UVA", "VU", "TUDELFT"])
        self.ledger.complete(first["code_hash"])
        second, reused = self.service.submit(b"value=1\n", ["UVA"])
        self.assertTrue(reused)
        self.assertEqual(second["status"], "approved")
        self.assertEqual(first["code_hash"], second["code_hash"])

    def test_concurrent_duplicate_conflict_is_reported_as_reuse(self):
        code = b"value=2\n"
        self.ledger.submit(code.decode(), ["UVA"])
        original = self.ledger.submission
        calls = []
        def first_missing(code_hash):
            calls.append(code_hash)
            return None if len(calls) == 1 else original(code_hash)
        self.ledger.submission = first_missing
        _, reused = self.service.submit(code, ["UVA"])
        self.assertTrue(reused)

    def test_size_binary_and_empty_input_are_rejected_before_the_ledger(self):
        for content in (b"\0binary", b"   \n", b"a" * (MAX_SUBMISSION_BYTES + 1)):
            with self.assertRaises(AnalysisError):
                self.service.submit(content, ["UVA"])
        self.assertEqual(self.ledger.tx, 0)

    def test_catalog_lists_only_undisputed_approvals_and_never_executable(self):
        approved, _ = self.service.submit(b"value=1\n", ["UVA", "VU", "TUDELFT"])
        self.ledger.complete(approved["code_hash"])
        disputed, _ = self.service.submit(b"value=2\n", ["UVA", "VU", "TUDELFT"])
        self.ledger.complete(disputed["code_hash"], audit_match=False)
        rejected, _ = self.service.submit(b"value=3\n", ["UVA"])
        self.ledger.complete(rejected["code_hash"], decision="rejected")
        catalog = self.service.catalog()
        self.assertEqual([item["code_hash"] for item in catalog], [None, approved["code_hash"]])
        self.assertTrue(catalog[0]["executable"])
        self.assertFalse(catalog[1]["executable"])
        self.assertTrue(self.service.submission(disputed["code_hash"])["disputed"])

    def test_report_verification_recomputes_hash_and_detects_tampering(self):
        item, _ = self.service.submit(b"value=1\n", ["UVA", "VU", "TUDELFT"])
        self.ledger.complete(item["code_hash"])
        result = self.service.verify_submission(item["code_hash"])
        self.assertTrue(result["valid"])
        self.assertEqual(result["audits"], [{"organization": "VU", "match": True}])
        self.ledger.items[item["code_hash"]]["analysis"]["report_json"] = '{"score":12}'
        self.assertFalse(self.service.verify_submission(item["code_hash"])["valid"])

    def test_events_do_not_contain_code_names_or_findings(self):
        self.service.submit(b"marker_not_for_ledger=1\n", ["UVA"])
        events = json.dumps(self.ledger.events())
        for forbidden in ("Meirylene Avelino", "marker_not_for_ledger", '"findings"'):
            self.assertNotIn(forbidden, events)


class FabricLedgerClientTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.token = Path(self.directory.name) / "token"
        self.token.write_text("gateway-token-for-tests")

    def client(self, handler):
        return FabricLedger("http://gateway.invalid", self.token, httpx.MockTransport(handler))

    def test_token_errors_and_not_found(self):
        def handler(request):
            self.assertEqual(request.headers["authorization"], "Bearer gateway-token-for-tests")
            if request.url.path.startswith("/submissions/"):
                return httpx.Response(404, json={"kind": "notfound", "detail": "submission not found"})
            return httpx.Response(409, json={"kind": "conflict", "detail": "this code hash was already submitted"})
        ledger = self.client(handler)
        self.assertIsNone(ledger.submission("0" * 64))
        with self.assertRaises(LedgerError) as raised:
            ledger.submit("x", ["UVA"])
        self.assertEqual((raised.exception.status, raised.exception.kind), (409, "conflict"))

    def test_missing_credentials_and_unreachable_gateway(self):
        missing = FabricLedger("http://gateway.invalid", Path(self.directory.name) / "absent")
        with self.assertRaises(LedgerError):
            missing.status()
        def unreachable(request):
            raise httpx.ConnectError("refused", request=request)
        with self.assertRaises(LedgerError) as raised:
            self.client(unreachable).status()
        self.assertEqual(raised.exception.status, 503)


if __name__ == "__main__":
    unittest.main()
