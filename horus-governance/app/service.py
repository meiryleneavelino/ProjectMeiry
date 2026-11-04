"""Governance service of the Horus API.

What changed with the Fabric ledger:
- The server no longer draws the reviewer, runs analyses or writes history.
- A submission becomes a SubmitCode transaction signed by the researcher's
  Fabric identity (through the gateway). The chaincode reads the researcher's
  organization from the certificate.
- The eligible organizations' SAST agents run commit-reveal, the drawn one
  analyzes in its own namespace and records a signed report; the others audit.
- This module reads that state from the ledger and presents it to the UI.
"""
import hashlib
import json
import re

from sast.contracts import AnalysisError, content_hash, normalize_code
from .ledger import FabricLedger, LedgerError
from .reviewer import KNOWN_ORGANIZATIONS, eligible_reviewers
from .storage import Store


BUILTIN = "logistic-regression-v1"
# Code plus Kubernetes object overhead must fit one ConfigMap in the analyzing
# organization's namespace; the chaincode enforces the same limit.
MAX_SUBMISSION_BYTES = 900 * 1024
PENDING = ("drawing", "assigned")


class Governance:
    def __init__(self, settings, ledger=None):
        if (settings.organization not in KNOWN_ORGANIZATIONS
                or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{7,63}", settings.pseudonym)):
            raise ValueError("Invalid server-side researcher configuration.")
        self.settings = settings
        self.store = Store(settings.state_root)
        self.ledger = ledger or FabricLedger(settings.ledger_url, settings.ledger_token_file)

    def submit(self, content, selected):
        code = normalize_code(content)
        if len(code) > MAX_SUBMISSION_BYTES:
            raise AnalysisError("invalid_size", f"Code must not exceed {MAX_SUBMISSION_BYTES} bytes.")
        eligible_reviewers(selected, self.settings.organization)
        code_hash = content_hash(code)
        existing = self.ledger.submission(code_hash)
        if existing:
            return self.present(existing), True
        try:
            result = self.ledger.submit(code.decode("utf-8"), selected)
        except LedgerError as error:
            # A concurrent request may have submitted the same hash first.
            if error.status == 409 and (existing := self.ledger.submission(code_hash)):
                return self.present(existing), True
            raise
        item = self.present(result["result"])
        item["receipt"] = result["receipt"]
        return item, False

    @staticmethod
    def present(raw):
        analysis, failure = raw.get("analysis"), raw.get("failure")
        report = json.loads(analysis["report_json"]) if analysis else None
        return {
            "code_hash": raw["code_hash"], "status": raw["status"], "created_at": raw["created_at"],
            "code_bytes": raw.get("code_bytes"), "researcher_org": raw["researcher_org"],
            "researcher_id": raw["researcher_id"],
            "selection": {
                "reviewer": raw.get("reviewer") or None, "eligible": raw["eligible"],
                "excluded": raw["researcher_org"], "seed": raw.get("seed") or None,
                "selection_version": raw.get("selection_version") or None,
                "commits": sorted(raw.get("commits") or {}), "reveals": sorted(raw.get("reveals") or {}),
                "defaulted": raw.get("defaulted") or [],
            },
            "report": report, "report_hash": analysis["report_hash"] if analysis else None,
            "provenance": {"organization": analysis["organization"], "msp_id": analysis["msp_id"],
                           "image_digest": analysis["image_digest"], "tx_id": analysis["tx_id"],
                           "recorded_at": analysis["recorded_at"]} if analysis else None,
            "error": f"The reviewer reported '{failure['code']}'; no approval was issued." if failure else None,
            "audits": raw.get("audits") or [], "disputed": bool(raw.get("disputed")),
            "tx_ids": raw.get("tx_ids") or {},
        }

    def submission(self, code_hash):
        raw = self.ledger.submission(code_hash)
        if raw is None:
            raise LookupError("Submission not found.")
        return self.present(raw)

    def submissions(self):
        return [{"code_hash": item["code_hash"], "status": item["status"], "created_at": item["created_at"],
                 "reviewer": item.get("reviewer") or None, "disputed": bool(item.get("disputed"))}
                for item in self.ledger.submissions()[:50]]

    def verify_submission(self, code_hash):
        """Independent check of a stored report: its bytes hash to the recorded
        hash, the recording transaction is VALID in a block, and audits agree."""
        raw = self.ledger.submission(code_hash)
        if raw is None or not raw.get("analysis"):
            raise LookupError("No recorded analysis for this submission.")
        analysis = raw["analysis"]
        actual = hashlib.sha256(analysis["report_json"].encode("utf-8")).hexdigest()
        transaction = self.ledger.transaction(analysis["tx_id"])
        audits = raw.get("audits") or []
        return {"valid": actual == analysis["report_hash"] and transaction.get("valid") is True,
                "code_hash": code_hash, "expected_hash": analysis["report_hash"], "actual_hash": actual,
                "tx_id": analysis["tx_id"], "block_number": transaction.get("block_number"),
                "validation_code": transaction.get("validation_code"), "signed_by": analysis["msp_id"],
                "audits": [{"organization": audit["organization"], "match": audit["match"]} for audit in audits],
                "disputed": bool(raw.get("disputed"))}

    def catalog(self):
        algorithms = [{"id": BUILTIN, "name": "Logistic regression (FedAvg)", "code_hash": None, "score": 100,
                       "executable": True, "validation_source": "builtin-trusted", "report_hash": None,
                       "registration_tx_id": None}]
        for item in self.ledger.submissions():
            analysis = item.get("analysis")
            if item["status"] == "approved" and analysis and not item.get("disputed"):
                algorithms.append({"id": f"submitted-{item['code_hash']}",
                                   "name": f"Submitted algorithm {item['code_hash'][:12]}",
                                   "code_hash": item["code_hash"], "score": analysis["score"], "executable": False,
                                   "validation_source": "semgrep", "report_hash": analysis["report_hash"],
                                   "registration_tx_id": analysis["tx_id"]})
        return algorithms
