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
        # Default: through Vite, which injects the API token. HORUS_GOV_LIVE_API and
        # HORUS_GOV_LIVE_TOKEN allow calling an API instance directly.
        self.api = os.environ.get("HORUS_GOV_LIVE_API", "http://127.0.0.1:5175/governance-api")
        token = os.environ.get("HORUS_GOV_LIVE_TOKEN")
        self.client = httpx.Client(base_url="http://127.0.0.1:5175", timeout=90, trust_env=False,
                                   headers={"Authorization": f"Bearer {token}"} if token else {})
        self.addCleanup(self.client.close)

    def request(self, method, path, **arguments):
        response = self.client.request(method, self.api + path, **arguments)
        response.raise_for_status()
        return response.json()

    def test_draw_local_analysis_audit_and_ledger(self):
        """Needs the Fabric ledger (tools.py ledger setup + forward), the API and Vite.
        Uses a unique comment so a fresh code hash goes through the whole flow."""
        identity = self.request("GET", "/me")
        marker = f"# live test {uuid4()}\n".encode()
        for filename, decision, score in (("clean.py", "approved", 100), ("unsafe.py", "rejected", 0)):
            content = (ROOT / "examples" / filename).read_bytes() + marker
            item = self.request("POST", "/submissions", files={"file": (filename, content)},
                                data={"organizations": '["UVA","VU","TUDELFT"]'})
            self.assertIsNone(item["selection"]["reviewer"])
            deadline = time.monotonic() + 300
            while (item["status"] in ("drawing", "assigned") or len(item["audits"]) < len(item["selection"]["eligible"]) - 1) \
                    and time.monotonic() < deadline:
                time.sleep(2)
                item = self.request("GET", f"/submissions/{item['code_hash']}")
            self.assertEqual(item["status"], decision, item)
            self.assertNotEqual(item["selection"]["reviewer"], identity["organization"])
            self.assertEqual(item["selection"]["reveals"], item["selection"]["eligible"])
            self.assertEqual(item["provenance"]["organization"], item["selection"]["reviewer"])
            self.assertEqual(item["report"]["score"], score)
            self.assertTrue(all(audit["match"] for audit in item["audits"]))
            self.assertFalse(item["disputed"])
            self.assertNotIn("FAKE_HORUS_TOKEN_FOR_STATIC_ANALYSIS_ONLY", json.dumps(item))
            self.assertTrue(self.request("POST", f"/reports/{item['code_hash']}/verify")["valid"])
            duplicate = self.request("POST", "/submissions", json={"code": content.decode(), "organizations": ["UVA", "TUDELFT"]})
            self.assertTrue(duplicate["reused"])
            events = self.request("GET", f"/ledger/events?code_hash={item['code_hash']}&limit=100")["items"]
            self.assertEqual(sum(event["event_type"] == "CodeAnalyzed" for event in events), 1)
            self.assertNotIn(identity["name"], json.dumps(events))
            self.assertNotIn('"findings"', json.dumps(events))
        status = self.request("GET", "/status")
        self.assertTrue(status["ledger_ready"] and status["blockchain"])

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