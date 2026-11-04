import json
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

import httpx
from fastapi.testclient import TestClient

from app.main import create_app
from app.settings import Settings
from fake_ledger import FakeLedger


class APITests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        token = root / "training-token"
        token.write_text("test-training-token")
        self.calls = []
        def training(request):
            self.calls.append(request)
            return httpx.Response(202, json={"id": str(uuid4()), "status": "queued"})
        self.ledger = FakeLedger()
        self.settings = Settings(root, training_token_file=token)
        self.app = create_app(self.settings, httpx.MockTransport(training), self.ledger)
        self.client = TestClient(self.app)
        self.client.headers["Authorization"] = f"Bearer {self.settings.token()}"

    def test_authentication_and_server_identity(self):
        self.assertEqual(self.client.get("/me", headers={"Authorization": "wrong"}).status_code, 401)
        self.assertEqual(self.client.get("/me").json()["organization"], "TUDELFT")
        response = self.client.post("/submissions", json={"code": "value=1", "organizations": ["UVA"],
                                                        "researcher_org": "UVA"})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.client.get("/me", headers={"Origin": "https://untrusted.invalid"}).status_code, 403)

    def test_upload_draw_state_duplicates_and_verification(self):
        response = self.client.post("/submissions", files={"file": ("../example.py", b"value=1\r\n")},
                                    data={"organizations": json.dumps(["UVA", "VU", "TUDELFT"])})
        self.assertEqual(response.status_code, 202, response.text)
        item = response.json()
        self.assertEqual(item["status"], "drawing")
        self.assertIsNone(item["selection"]["reviewer"])
        second = self.client.post("/submissions", json={"code": "value=1\n", "organizations": ["UVA"]})
        self.assertEqual(second.status_code, 200)
        self.assertTrue(second.json()["reused"])
        self.ledger.complete(item["code_hash"], reviewer="VU")
        result = self.client.get(f"/submissions/{item['code_hash']}").json()
        self.assertEqual((result["status"], result["provenance"]["organization"]), ("approved", "VU"))
        self.assertTrue(self.client.post(f"/reports/{item['code_hash']}/verify").json()["valid"])
        self.assertEqual(self.client.get("/submissions").json()[0]["code_hash"], item["code_hash"])

    def test_binary_extension_utf8_size_and_no_eligible_reviewer(self):
        for name, content in (("example.py", b"\0binary"), ("example.py", b"\xff"),
                              ("example.exe", b"value=1"), ("example.py", b"a" * (1048576 + 1))):
            response = self.client.post("/submissions", files={"file": (name, content)},
                                        data={"organizations": '["UVA"]'})
            self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(self.client.post("/submissions", json={"code": "value=1", "organizations": ["TUDELFT"]}).status_code, 422)

    def test_ledger_routes_status_and_errors(self):
        item = self.client.post("/submissions", json={"code": "value=1\n", "organizations": ["UVA"]}).json()
        status = self.client.get("/status").json()
        self.assertTrue(status["blockchain"])
        self.assertTrue(status["ledger_ready"])
        self.assertEqual(status["ledger"]["backend"], "hyperledger-fabric")
        events = self.client.get("/ledger/events", params={"code_hash": item["code_hash"]}).json()
        self.assertEqual(events["total"], 1)
        tx_id = events["items"][0]["tx_id"]
        detail = self.client.get(f"/ledger/transactions/{tx_id}").json()
        self.assertTrue(detail["valid"])
        self.assertEqual(detail["events"][0]["event_type"], "CodeSubmitted")
        self.assertEqual(self.client.get("/ledger/transactions/local-1").status_code, 422)
        self.assertEqual(self.client.get("/ledger/events", params={"event_type": "Nope"}).status_code, 422)
        self.assertEqual(self.client.get(f"/submissions/{'0' * 64}").status_code, 404)

    def test_new_algorithms_cannot_be_executed_and_start_is_idempotent(self):
        payload = {"algorithm": "submitted-code", "organizations": ["UVA", "TUDELFT"],
                   "dataset_id": "synthetic-local-v1", "rounds": 3, "local_epochs": 2}
        key = str(uuid4())
        self.assertEqual(self.client.post("/training/runs", json=payload, headers={"Idempotency-Key": key}).status_code, 422)
        self.assertEqual(len(self.calls), 0)
        payload["algorithm"] = "logistic-regression-v1"
        first = self.client.post("/training/runs", json=payload, headers={"Idempotency-Key": key})
        second = self.client.post("/training/runs", json=payload, headers={"Idempotency-Key": key})
        self.assertEqual(first.status_code, 202, first.text)
        self.assertEqual(first.json(), second.json())
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(json.loads(self.calls[0].content), payload)
        self.assertEqual(self.client.get("/ledger/events", params={"event_type": "TrainingStarted"}).json()["total"], 1)


if __name__ == "__main__":
    unittest.main()
