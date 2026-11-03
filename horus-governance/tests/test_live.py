import json
import os
import time
import unittest
from pathlib import Path
from uuid import uuid4

import httpx


ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.environ.get("HORUS_GOV_LIVE_TESTS") == "1", "Enable local live governance tests explicitly")
class LiveTests(unittest.TestCase):
    def setUp(self):
        self.client = httpx.Client(base_url="http://127.0.0.1:5175", timeout=90, trust_env=False)
        self.addCleanup(self.client.close)

    def request(self, method, path, **arguments):
        response = self.client.request(method, "/governance-api" + path, **arguments)
        response.raise_for_status()
        return response.json()

    def test_analysis_catalog_deduplication_and_audit(self):
        identity = self.request("GET", "/me")
        for filename, decision, score in (("clean.py", "approved", 100), ("unsafe.py", "rejected", 0)):
            content = (ROOT / "examples" / filename).read_bytes()
            item = self.request("POST", "/submissions", files={"file": (filename, content)},
                                data={"organizations": '["UVA","VU","TUDELFT"]'})
            deadline = time.monotonic() + 150
            while item["status"] in ("queued", "running") and time.monotonic() < deadline:
                time.sleep(0.25)
                item = self.request("GET", f"/submissions/{item['code_hash']}")
            self.assertEqual(item["status"], decision, item)
            self.assertNotEqual(item["selection"]["reviewer"], identity["organization"])
            self.assertEqual(item["report"]["score"], score)
            self.assertNotIn("FAKE_HORUS_TOKEN_FOR_STATIC_ANALYSIS_ONLY", json.dumps(item))
            self.assertTrue(self.request("POST", f"/reports/{item['code_hash']}/verify")["valid"])
            duplicate = self.request("POST", "/submissions", json={"code": content.decode(), "organizations": ["UVA", "TUDELFT"]})
            self.assertTrue(duplicate["reused"])
            self.assertEqual(duplicate["report_hash"], item["report_hash"])
            events = self.request("GET", f"/ledger/events?code_hash={item['code_hash']}")["items"]
            self.assertEqual(sum(event["event_type"] == "CodeAnalyzed" for event in events), 1)
            self.assertNotIn(identity["name"], json.dumps(events))
            self.assertNotIn('"findings"', json.dumps(events))
        self.assertTrue(self.request("POST", "/ledger/verify")["valid"])
        self.assertTrue(self.request("GET", "/status")["worker_ready"])

    @unittest.skipUnless(os.environ.get("HORUS_GOV_LIVE_TRAINING") == "1", "Enable actual training explicitly")
    def test_existing_training_and_training_started_event(self):
        runs = self.client.get("/training-api/runs").raise_for_status().json()
        if any(run["status"] not in ("completed", "failed", "cancelled", "interrupted") for run in runs):
            self.skipTest("Another training run is active")
        payload = {"algorithm": "logistic-regression-v1", "organizations": ["UVA", "VU", "TUDELFT"],
                   "dataset_id": "synthetic-local-v1", "rounds": 3, "local_epochs": 2}
        headers = {"Idempotency-Key": str(uuid4())}
        run = self.request("POST", "/training/runs", json=payload, headers=headers)
        self.assertEqual(self.request("POST", "/training/runs", json=payload, headers=headers)["id"], run["id"])
        deadline = time.monotonic() + 600
        while run["status"] not in ("completed", "failed", "cancelled", "interrupted") and time.monotonic() < deadline:
            time.sleep(1)
            run = self.client.get(f"/training-api/runs/{run['id']}").raise_for_status().json()
        self.assertEqual(run["status"], "completed", run)
        self.assertEqual(run["completed_rounds"], 3)
        model = self.client.get(f"/training-api/runs/{run['id']}/model").raise_for_status().json()
        self.assertEqual(model["format"], "dynamos-logistic-regression-v1")
        events = self.request("GET", "/ledger/events?event_type=TrainingStarted&limit=100")["items"]
        self.assertEqual(sum(event["payload"]["run_id"] == run["id"] for event in events), 1)
        print(f"Live governed training completed: {run['id']}")


if __name__ == "__main__":
    unittest.main()