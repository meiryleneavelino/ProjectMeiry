import ast
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from contracts import (AnalysisError, MAX_CODE_BYTES, SEVERITIES, build_report,
                       canonical_json, content_hash, normalize_code)


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_VERSION = "1.145.0"


def run_semgrep(arguments, timeout):
    try:
        result = subprocess.run(["semgrep", *arguments], capture_output=True,
                                text=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise AnalysisError("scanner_unavailable", "Static analysis could not complete safely.") from None
    if result.returncode != 0:
        raise AnalysisError("scanner_failed", "Static analysis failed; no approval was issued.")
    return result.stdout


def analyze(content):
    code = normalize_code(content)
    try:
        ast.parse(code.decode("utf-8"), filename="submission.py", mode="exec")
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        raise AnalysisError("invalid_python", "The script must contain valid Python syntax; no approval was issued.") from None
    organization = os.environ.get("HORUS_ORGANIZATION", "")
    if organization not in ("UVA", "VU", "TUDELFT"):
        raise AnalysisError("invalid_organization", "A configured analysis organization is required.")
    rules_path = ROOT / "sast" / "rules.yaml"
    rules_bytes = rules_path.read_bytes()
    rules = {rule["id"]: rule for rule in json.loads(rules_bytes)["rules"]}
    policy = json.loads((ROOT / "config" / "policy.json").read_bytes())
    version = run_semgrep(["--version", "--disable-version-check"], 15).strip()
    if version != EXPECTED_VERSION:
        raise AnalysisError("scanner_version", "The installed static analyzer version is not approved.")
    with tempfile.TemporaryDirectory(prefix="horus-sast-", dir="/tmp") as directory:
        target = Path(directory) / "submission.py"
        target.write_bytes(code)
        output = run_semgrep([
            "scan", "--config", str(rules_path), "--json", "--quiet", "--strict",
            "--metrics=off", "--disable-version-check", "--disable-nosem",
            "--no-git-ignore", "--no-rewrite-rule-ids", "--oss-only",
            "--jobs=1", "--timeout=10", "--max-memory=512",
            "--max-target-bytes=1048576", str(target),
        ], 90)
        try:
            raw = json.loads(output)
        except (ValueError, TypeError):
            raise AnalysisError("invalid_scanner_output", "Static analysis returned an invalid result.") from None
        if raw.get("errors") or len(raw.get("paths", {}).get("scanned", [])) != 1:
            raise AnalysisError("incomplete_scan", "The whole script must be analyzed before a decision.")
        findings = []
        for result in raw.get("results", []):
            rule = rules.get(result.get("check_id"))
            start = result.get("start", {})
            if (not rule or rule["metadata"].get("horus_severity") not in SEVERITIES
                    or not isinstance(start.get("line"), int) or start["line"] < 1
                    or not isinstance(start.get("col"), int) or start["col"] < 1):
                raise AnalysisError("invalid_finding", "Static analysis returned an invalid finding.")
            findings.append({
                "rule_id": rule["id"], "line": start["line"], "column": start["col"],
                "severity": rule["metadata"]["horus_severity"], "message": rule["message"],
            })
    result = build_report(code, findings, policy, content_hash(rules_bytes), version)
    result["provenance"] = {"organization": organization}
    return result


def main():
    try:
        result = analyze(sys.stdin.buffer.read(MAX_CODE_BYTES + 1))
        sys.stdout.buffer.write(canonical_json(result) + b"\n")
        return 0
    except AnalysisError as error:
        result = {"error": {"code": error.code, "message": str(error)}}
    except Exception:
        result = {"error": {"code": "analysis_failed", "message": "Static analysis failed; no approval was issued."}}
    sys.stdout.buffer.write(canonical_json(result) + b"\n")
    return 2


if __name__ == "__main__":
    sys.exit(main())