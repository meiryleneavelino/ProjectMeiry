import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import manage


class PortabilityTests(unittest.TestCase):
    def test_isolated_paths_and_context(self):
        self.assertEqual(manage.ROOT.name, "Scattered-Directive")
        self.assertEqual(manage.CONTEXT, "kind-scattered-training")
        with patch.object(manage, "tools") as tools:
            manage.kubectl("get", "pods")
            self.assertEqual(tools.call_args.args[:3], ("kubectl", "--context", "kind-scattered-training"))
        with patch.object(manage, "WORKSPACE", "/custom/scattered/"):
            self.assertEqual(manage.container_path("charts/federated-training"),
                             "/custom/scattered/charts/federated-training")

    def test_local_access_is_stable_and_private(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(manage, "LOCAL", Path(directory)):
            manage.prepare_access()
            access = json.loads((manage.LOCAL / "access.json").read_text())
            manage.prepare_access()
            self.assertEqual(access, json.loads((manage.LOCAL / "access.json").read_text()))
            self.assertEqual(access["url"], "http://127.0.0.1:8096/api/v1/ml")
            values = json.loads((manage.LOCAL / "integrated-values.json").read_text())
            self.assertEqual(values["image"], manage.IMAGE)
            self.assertEqual(values["integrated"]["image"], manage.DYNAMOS_IMAGE)
            for name in ("access.json", "api-token", "integrated-values.json"):
                self.assertEqual((manage.LOCAL / name).stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()