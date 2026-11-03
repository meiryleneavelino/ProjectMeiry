import json
import os
import subprocess
import unittest
from pathlib import Path
from uuid import uuid4

from sast.contracts import (AnalysisError, build_report, canonical_json,
                            content_hash, normalize_code, validate_filename, verify_report)
from sast.docker_runner import DOCKER, analyze_in_docker, container_options, docker_json


ROOT = Path(__file__).resolve().parents[1]
POLICY = json.loads((ROOT / "config" / "policy.json").read_text())


class ContractTests(unittest.TestCase):
    def test_report_tampering_is_detected(self):
        envelope = build_report(b"value=1\n", [], POLICY, "rules", "version")
        self.assertTrue(verify_report(envelope["report"], envelope["report_hash"]))
        envelope["report"]["score"] = 42
        self.assertFalse(verify_report(envelope["report"], envelope["report_hash"]))

    def test_normalization_changes_only_line_endings(self):
        self.assertEqual(normalize_code(b"value = 1\r\nvalue += 1\r"),
                         b"value = 1\nvalue += 1\n")
        self.assertNotEqual(content_hash(normalize_code(b"value=1\n")),
                            content_hash(normalize_code(b"value = 1\n")))

    def test_binary_invalid_utf8_empty_and_oversize_are_rejected(self):
        for content in (b"\0text", b"text\x1b[0m", b"\xff", b"", b" \n", b"a" * (1024 * 1024 + 1)):
            with self.subTest(content_size=len(content)), self.assertRaises(AnalysisError):
                normalize_code(content)
        self.assertEqual(len(normalize_code(b"a" * (1024 * 1024))), 1024 * 1024)

    def test_filename_extension(self):
        for name in ("example.py", "example.txt", "example.PY"):
            validate_filename(name)
        for name in ("example.exe", "example.py.exe", "example", "example.py\0"):
            with self.assertRaises(AnalysisError):
                validate_filename(name)

    def test_scoring_and_deterministic_order(self):
        findings = [
            {"rule_id": severity, "line": line, "column": 1,
             "severity": severity, "message": "Fixed message."}
            for line, severity in enumerate(("high", "medium", "low"), start=1)
        ]
        first = build_report(b"value=1\n", findings, POLICY, "rules", "version")
        second = build_report(b"value=1\n", list(reversed(findings)), POLICY, "rules", "version")
        self.assertEqual(first, second)
        self.assertEqual(first["report"]["score"], 63)
        self.assertEqual(first["report"]["decision"], "rejected")
        self.assertEqual(first["report_hash"], content_hash(canonical_json(first["report"])))

    def test_clean_report_and_high_finding_threshold(self):
        clean = build_report(b"value=1\n", [], POLICY, "rules", "version")["report"]
        self.assertEqual((clean["score"], clean["decision"]), (100, "approved"))
        finding = {"rule_id": "high", "line": 1, "column": 1,
                   "severity": "high", "message": "Fixed message."}
        report = build_report(b"value=1\n", [finding], POLICY, "rules", "version")["report"]
        self.assertEqual(report["score"], 75)
        self.assertEqual(report["decision"], "rejected")
        report = build_report(b"value=1\n", [finding] * 5, POLICY, "rules", "version")["report"]
        self.assertEqual(report["score"], 0)


@unittest.skipUnless(os.environ.get("HORUS_SAST_DOCKER_TESTS") == "1", "Enable real Docker/Semgrep tests explicitly")
class DockerTests(unittest.TestCase):
    def test_examples_are_deterministic_across_all_organizations(self):
        for filename, decision, score in (("clean.py", "approved", 100), ("unsafe.py", "rejected", 0)):
            with self.subTest(filename=filename):
                code = (ROOT / "examples" / filename).read_bytes()
                results = [analyze_in_docker(code, organization) for organization in ("UVA", "VU", "TUDELFT")]
                self.assertEqual(len({result["report_hash"] for result in results}), 1)
                self.assertEqual(results[0]["report"]["decision"], decision)
                self.assertEqual(results[0]["report"]["score"], score)
                self.assertEqual({result["provenance"]["organization"] for result in results}, {"UVA", "VU", "TUDELFT"})
                self.assertNotIn("FAKE_HORUS_TOKEN_FOR_STATIC_ANALYSIS_ONLY", canonical_json(results).decode())
                self.assertNotIn("submission.py", canonical_json(results).decode())

    def test_all_required_categories_and_aliases(self):
        code = b'''import os
import pickle
import subprocess as processes
import yaml
import socket
import requests as network
import urllib.request
from http.client import HTTPConnection
import httpx
import aiohttp
from pickle import loads as restore
import builtins as dynamic
dynamic.compile("value=1", "<text>", "exec")
eval("value")
exec("value=1")
pickle.load(stream)
restore(serialized)
yaml.load(text)
processes.run(["echo", "example"])
os.system("echo example")
open("/etc/horus-test", "w")
from pathlib import Path
Path("/etc/horus-test").write_text("example")
API_TOKEN = "DO_NOT_COPY_THIS_TEST_CREDENTIAL"
'''
        report = analyze_in_docker(code, "UVA")["report"]
        rules = {finding["rule_id"] for finding in report["findings"]}
        self.assertTrue({"horus.dynamic-code", "horus.pickle-deserialization", "horus.unsafe-yaml",
                         "horus.process-execution", "horus.network-import", "horus.file-write-path",
                         "horus.hardcoded-secret"}.issubset(rules), rules)
        network_lines = {finding["line"] for finding in report["findings"] if finding["rule_id"] == "horus.network-import"}
        self.assertTrue({5, 6, 7, 8, 9, 10}.issubset(network_lines), network_lines)
        self.assertNotIn("DO_NOT_COPY_THIS_TEST_CREDENTIAL", canonical_json(report).decode())

    def test_safe_yaml_and_static_tmp_writes(self):
        code = b'''import yaml
from pathlib import Path
yaml.safe_load(text)
yaml.load(text, Loader=yaml.SafeLoader)
yaml.load(text, yaml.CSafeLoader)
open("/tmp/horus-output", "w")
Path("/tmp/horus-output").write_text("example")
'''
        report = analyze_in_docker(code, "UVA")["report"]
        self.assertEqual(report["findings"], [])
        self.assertEqual(report["score"], 100)

    def test_traversal_and_dynamic_file_destinations_are_flagged(self):
        code = b'''open("/tmp/../etc/horus-test", "w")
open(destination, mode="w")
'''
        report = analyze_in_docker(code, "UVA")["report"]
        self.assertEqual({finding["line"] for finding in report["findings"]
                          if finding["rule_id"] == "horus.file-write-path"}, {1, 2})

    def test_suppressions_do_not_hide_findings(self):
        report = analyze_in_docker(b'eval("value")  # nosemgrep: horus.dynamic-code\n', "UVA")["report"]
        self.assertEqual(report["decision"], "rejected")

    def test_unresolved_destinations_and_dynamic_modes_fail_policy(self):
        code = b'''from pathlib import Path
target = Path("/etc/horus-output")
target.write_text("example")
open("/etc/horus-output", mode=mode)
import os
os.open("/etc/horus-output", os.O_WRONLY)
'''
        report = analyze_in_docker(code, "UVA")["report"]
        self.assertEqual(report["decision"], "rejected")
        self.assertTrue({3, 4, 6}.issubset({finding["line"] for finding in report["findings"]
                                         if finding["severity"] == "high"}), report["findings"])

    def test_submitted_code_is_not_executed(self):
        report = analyze_in_docker(b'raise RuntimeError("USER_CODE_MUST_NOT_EXECUTE")\n', "UVA")["report"]
        self.assertEqual(report["decision"], "approved")

    def test_invalid_python_fails_closed(self):
        with self.assertRaises(AnalysisError):
            analyze_in_docker(b"def broken(:\n", "UVA")

    def test_binary_is_rejected_before_starting_a_container(self):
        with self.assertRaises(AnalysisError):
            analyze_in_docker(b"\0binary", "UVA")

    def test_effective_container_isolation(self):
        name = f"horus-sast-test-{uuid4().hex}"
        image_id = docker_json("image", "inspect", "horus-sast-uva:local")[0]["Id"]
        try:
            subprocess.run([DOCKER, "create", "--interactive", *container_options(name), image_id],
                           check=True, capture_output=True)
            inspected = docker_json("inspect", name)[0]
            host = inspected["HostConfig"]
            self.assertEqual(host["NetworkMode"], "none")
            self.assertTrue(host["ReadonlyRootfs"])
            self.assertFalse(host["Privileged"])
            self.assertEqual(host["CapDrop"], ["ALL"])
            self.assertIn("no-new-privileges:true", host["SecurityOpt"])
            self.assertEqual(host["PidsLimit"], 128)
            self.assertEqual(host["Memory"], 768 * 1024 * 1024)
            self.assertEqual(inspected["Config"]["User"], "10001:10001")
            self.assertEqual(inspected["Mounts"], [])
        finally:
            subprocess.run([DOCKER, "rm", "--force", name], check=False, capture_output=True)


if __name__ == "__main__":
    unittest.main()