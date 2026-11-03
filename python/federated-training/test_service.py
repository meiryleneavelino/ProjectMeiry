import importlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient

os.environ["ROLE"] = "coordinator"
os.environ["API_TOKEN"] = "unit-test-token"
import service


class TrainingServiceTests(unittest.TestCase):
    def test_unknown_scripts_paths_and_organizations_are_rejected(self):
        valid = {"organizations": ["UVA", "TUDELFT"]}
        for alteration in ({"algorithm": "arbitrary.py"}, {"dataset_id": "/etc/passwd"},
                           {"organizations": ["UVA", "OTHER"]}, {"organizations": ["UVA", "UVA"]},
                           {"rounds": 99}, {"image": "untrusted"}):
            with self.assertRaises(ValueError):
                service.TrainingRequest.model_validate({**valid, **alteration})

    def test_workers_have_only_their_own_read_only_dataset_and_no_api_token(self):
        job = service.worker_job("training-test", "tudelft", "trainer:test")
        pod = job["spec"]["template"]["spec"]
        self.assertFalse(pod["automountServiceAccountToken"])
        self.assertEqual(pod["volumes"][0]["persistentVolumeClaim"],
                         {"claimName": "training-data", "readOnly": True})
        self.assertTrue(pod["containers"][0]["volumeMounts"][0]["readOnly"])
        self.assertTrue(pod["containers"][0]["securityContext"]["readOnlyRootFilesystem"])
        self.assertNotIn("API_TOKEN", [value["name"] for value in pod["containers"][0]["env"]])

    def test_authentication_and_isolation_gate(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(service, "STATE_ROOT", Path(directory)):
            with TestClient(service.app) as connection:
                self.assertEqual(connection.get("/catalog").status_code, 401)
                response = connection.post("/runs", json={"organizations": ["UVA", "VU"]},
                                           headers={"Authorization": "Bearer unit-test-token"})
                self.assertEqual(response.status_code, 503)

    def test_download_requires_completed_training(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(service, "STATE_ROOT", Path(directory)):
            run_id = uuid4()
            service.write_json(service.run_path(run_id), {"id": str(run_id), "status": "failed"})
            with TestClient(service.app) as connection:
                response = connection.get(f"/runs/{run_id}/model", headers={"Authorization": "Bearer unit-test-token"})
                self.assertEqual(response.status_code, 409)

    def test_cancellation_is_not_overwritten_by_training_progress(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(service, "STATE_ROOT", Path(directory)):
            run_id = uuid4()
            service.write_json(service.run_path(run_id), {"id": str(run_id), "status": "cancelling"})
            with self.assertRaises(service.CancelledRun):
                service.publish_progress(service.run_path(run_id), {"id": str(run_id), "status": "running"})
            self.assertEqual(service.read_json(service.run_path(run_id))["status"], "cancelling")


if __name__ == "__main__":
    unittest.main()