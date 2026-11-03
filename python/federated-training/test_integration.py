import base64
import hashlib
import hmac
import json
import time
import unittest

from integration import verify_capability


class DYNAMOSApprovalTests(unittest.TestCase):
    def test_approval_is_bound_to_parameters_and_signature(self):
        parameters = {"algorithm": "logistic-regression-v1", "organizations": ["UVA", "TUDELFT"],
                      "dataset_id": "synthetic-local-v1", "rounds": 3, "local_epochs": 2}
        key = "sandbox-test-key" * 4
        grant = {"run_id": "example", "user": "researcher", "expires_at": int(time.time()) + 100, "request": parameters}
        encoded = base64.urlsafe_b64encode(json.dumps(grant, separators=(",", ":")).encode()).decode().rstrip("=")
        signature = base64.urlsafe_b64encode(hmac.new(key.encode(), encoded.encode(), hashlib.sha256).digest()).decode().rstrip("=")
        token = encoded + "." + signature
        self.assertEqual(verify_capability(token, key, parameters)["user"], "researcher")
        with self.assertRaises(ValueError):
            verify_capability(token, key, {**parameters, "organizations": ["UVA", "VU"]})
        with self.assertRaises(ValueError):
            verify_capability(token, key + "modified", parameters)
        with self.assertRaises(ValueError):
            verify_capability(None, key, parameters)


if __name__ == "__main__":
    unittest.main()