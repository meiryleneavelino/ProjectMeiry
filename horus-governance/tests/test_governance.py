import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from app.reviewer import select_reviewer
from app.service import Governance
from app.settings import Settings
from app.storage import IntegrityError
from sast.contracts import AnalysisError, build_report, content_hash
from sast.docker_runner import ROOT, organizations


def clean_analyzer(code, organization):
    rules = (ROOT / "sast/rules.yaml").read_bytes()
    policy = json.loads((ROOT / "config/policy.json").read_bytes())
    envelope = build_report(code, [], policy, content_hash(rules), "1.145.0")
    envelope["provenance"] = {"organization": organization, "image": organizations()[organization]["image"],
                              "image_id": "sha256:" + "a" * 64, "digest": "sha256:" + "a" * 64,
                              "digest_kind": "docker_image_id"}
    return envelope


class GovernanceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.service = Governance(Settings(Path(self.directory.name)))

    def test_researcher_is_never_selected_and_draw_is_reproducible(self):
        for organization in ("UVA", "VU", "TUDELFT"):
            for attempt in range(100):
                seed = f"{attempt:064x}"
                draw = select_reviewer(["UVA", "VU", "TUDELFT"], organization, seed)
                self.assertNotEqual(draw["reviewer"], organization)
                self.assertNotIn(organization, draw["eligible"])
                self.assertEqual(draw, select_reviewer(["TUDELFT", "VU", "UVA"], organization, seed))
        with self.assertRaises(ValueError):
            select_reviewer(["TUDELFT"], "TUDELFT")

    def test_duplicate_and_line_endings_do_not_reanalyze(self):
        first, reused = self.service.submit(b"value=1\r\n", ["UVA", "VU", "TUDELFT"])
        self.assertFalse(reused)
        self.service.work_once(clean_analyzer)
        second, reused = self.service.submit(b"value=1\n", ["UVA", "VU", "TUDELFT"])
        self.assertTrue(reused)
        self.assertEqual(first["selection"], second["selection"])
        self.assertFalse(self.service.work_once(clean_analyzer))
        self.assertEqual(second["status"], "approved")
        self.assertFalse(self.service.catalog()[1]["executable"])

    def test_concurrent_duplicate_creates_only_one_queue_item(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda unused: self.service.submit(b"value=2\n", ["UVA", "TUDELFT"]), range(4)))
        self.assertEqual(sum(not reused for _, reused in results), 1)
        self.assertTrue(self.service.work_once(clean_analyzer))
        self.assertFalse(self.service.work_once(clean_analyzer))

    def test_changed_text_creates_new_analysis(self):
        first, _ = self.service.submit(b"value=1\n", ["UVA"])
        second, _ = self.service.submit(b"value=2\n", ["UVA"])
        self.assertNotEqual(first["code_hash"], second["code_hash"])

    def test_binary_is_rejected(self):
        with self.assertRaises(AnalysisError):
            self.service.submit(b"\0binary", ["UVA"])

    def test_report_tampering_is_detected(self):
        item, _ = self.service.submit(b"value=1\n", ["UVA"])
        self.service.work_once(clean_analyzer)
        self.assertTrue(self.service.verify_submission(item["code_hash"])["valid"])
        with self.service.store.transaction() as connection:
            connection.execute("UPDATE submissions SET report=?", ('{"score": 12}',))
        self.assertFalse(self.service.verify_submission(item["code_hash"])["valid"])
        with self.assertRaises(IntegrityError):
            self.service.submission(item["code_hash"])

    def test_events_do_not_contain_code_names_or_findings(self):
        self.service.submit(b"marker_not_for_ledger=1\n", ["UVA"])
        self.service.work_once(clean_analyzer)
        events = json.dumps(self.service.ledger.events())
        for forbidden in ("Meirylene Avelino", "marker_not_for_ledger", '"findings"'):
            self.assertNotIn(forbidden, events)

    def test_scanner_errors_never_register_algorithm(self):
        item, _ = self.service.submit(b"value=1\n", ["UVA"])
        def unavailable(code, organization):
            raise RuntimeError("Private scanner diagnostics")
        self.service.work_once(unavailable)
        result = self.service.submission(item["code_hash"])
        self.assertEqual(result["status"], "error")
        self.assertNotIn("Private scanner", result["error"])
        self.assertEqual(len(self.service.catalog()), 1)


if __name__ == "__main__":
    unittest.main()