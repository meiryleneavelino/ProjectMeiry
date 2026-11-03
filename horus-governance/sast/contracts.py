import hashlib
import hmac
import json


MAX_CODE_BYTES = 1024 * 1024
SEVERITIES = ("high", "medium", "low")


class AnalysisError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def content_hash(content):
    return hashlib.sha256(content).hexdigest()


def verify_report(report, expected_hash):
    try:
        return isinstance(expected_hash, str) and hmac.compare_digest(
            content_hash(canonical_json(report)), expected_hash)
    except (TypeError, ValueError):
        return False


def normalize_code(content):
    if not isinstance(content, bytes):
        raise AnalysisError("invalid_input", "Code must be supplied as UTF-8 bytes.")
    if not content or len(content) > MAX_CODE_BYTES:
        raise AnalysisError("invalid_size", "Code must contain between 1 byte and 1 MB.")
    try:
        text = content.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        raise AnalysisError("invalid_utf8", "Code must be valid UTF-8 text.") from None
    if any((ord(character) < 32 and character not in "\t\r\n")
           or 127 <= ord(character) <= 159 for character in text):
        raise AnalysisError("binary_content", "Binary content and control characters are not accepted.")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if not text.strip():
        raise AnalysisError("empty_code", "Code must not be empty.")
    return text.encode("utf-8")


def validate_filename(filename):
    if not isinstance(filename, str) or not filename.lower().endswith((".txt", ".py")):
        raise AnalysisError("invalid_extension", "Only .txt and .py files are accepted.")


def build_report(code, findings, policy, rules_hash, semgrep_version):
    counts = {severity: 0 for severity in SEVERITIES}
    for finding in findings:
        counts[finding["severity"]] += 1
    score = max(0, 100 - sum(counts[severity] * policy["deductions"][severity]
                             for severity in SEVERITIES))
    reasons = []
    if counts["high"] > policy["maximum_high_findings"]:
        reasons.append("High-severity findings are not permitted.")
    if score < policy["minimum_score"]:
        reasons.append("Security score is below the required minimum.")
    approved = not reasons
    if approved:
        reasons.append("No high-severity findings and security score meets policy.")
    report = {
        "schema_version": 1,
        "code_hash": content_hash(code),
        "rules_hash": rules_hash,
        "policy_hash": content_hash(canonical_json(policy)),
        "semgrep_version": semgrep_version,
        "score": score,
        "counts": counts,
        "findings": sorted(findings, key=lambda finding: (
            finding["line"], finding["column"], finding["rule_id"],
            finding["severity"], finding["message"])),
        "decision": "approved" if approved else "rejected",
        "reasons": reasons,
    }
    return {"report": report, "report_hash": content_hash(canonical_json(report))}