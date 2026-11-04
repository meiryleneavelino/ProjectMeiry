import json
import tempfile
import time
import unittest
from pathlib import Path
from uuid import uuid4

import httpx

from app.service import Governance
from app.settings import Settings
from app.training_bridge import TrainingBridge, TrainingError
from fake_ledger import FakeLedger


class TrainingBridgeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        token = root / "training-token"
        token.write_text("test-training-token")
        self.ledger = FakeLedger()
        self.service = Governance(Settings(root, training_token_file=token), self.ledger)
        self.payload = {"algorithm": "logistic-regression-v1", "organizations": ["UVA", "VU", "TUDELFT"],
                        "dataset_id": "synthetic-local-v1", "rounds": 3, "local_epochs": 2}

    def test_timeout_cannot_blindly_duplicate_training(self):
        calls = []
        def timeout(request):
            calls.append(request)
            raise httpx.ReadTimeout("Simulated timeout", request=request)
        bridge = TrainingBridge(self.service, httpx.MockTransport(timeout))
        key = str(uuid4())
        with self.assertRaises(TrainingError):
            bridge.start(self.payload, key)
        self.assertEqual(bridge.request_status(key)["status"], "unknown")
        with self.assertRaises(TrainingError):
            bridge.start(self.payload, key)
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.ledger.trainings, {})

    def test_reconciliation_checks_actual_run_parameters_and_timestamp(self):
        run_id = str(uuid4())
        def upstream(request):
            if request.method == "POST":
                raise httpx.ReadTimeout("Simulated timeout", request=request)
            return httpx.Response(200, json={**self.payload, "id": run_id, "created_at": time.time()})
        bridge = TrainingBridge(self.service, httpx.MockTransport(upstream))
        key = str(uuid4())
        with self.assertRaises(TrainingError):
            bridge.start(self.payload, key)
        result = bridge.reconcile(key, run_id)
        self.assertEqual(result["id"], run_id)
        self.assertEqual(bridge.request_status(key)["status"], "completed")
        self.assertEqual(list(self.ledger.trainings), [run_id])

    def test_different_parameters_cannot_reuse_start_key(self):
        def upstream(request):
            return httpx.Response(202, json={"id": str(uuid4()), "status": "queued"})
        bridge = TrainingBridge(self.service, httpx.MockTransport(upstream))
        key = str(uuid4())
        bridge.start(self.payload, key)
        with self.assertRaises(TrainingError):
            bridge.start({**self.payload, "rounds": 1}, key)

    def test_ledger_outage_is_recorded_on_repeat_without_second_run(self):
        calls = []
        def upstream(request):
            calls.append(request)
            return httpx.Response(202, json={"id": str(uuid4()), "status": "queued"})
        bridge = TrainingBridge(self.service, httpx.MockTransport(upstream))
        key = str(uuid4())
        self.ledger.fail_training = True
        with self.assertRaises(TrainingError) as raised:
            bridge.start(self.payload, key)
        self.assertEqual(raised.exception.status, 503)
        self.assertIsNone(bridge.request_status(key)["ledger_tx"])
        self.ledger.fail_training = False
        result = bridge.start(self.payload, key)
        self.assertEqual(len(calls), 1)
        self.assertEqual(list(self.ledger.trainings), [result["id"]])
        self.assertIsNotNone(bridge.request_status(key)["ledger_tx"])


if __name__ == "__main__":
    unittest.main()