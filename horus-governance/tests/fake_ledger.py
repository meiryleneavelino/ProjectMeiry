"""In-memory stand-in for the Fabric gateway used by API/service tests.

It reproduces the gateway's JSON shapes and the rules that matter to the API
(duplicate hashes conflict, researcher organization excluded). The chaincode
rules themselves are tested in Go (ledger/governance, ledger/internal/agent).
"""
import hashlib
import json
from datetime import datetime, timezone

from app.ledger import LedgerError


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


class FakeLedger:
    def __init__(self, researcher="TUDELFT"):
        self.researcher = researcher
        self.items, self.codes, self.event_log, self.trainings = {}, {}, [], {}
        self.tx = 0
        self.fail_training = False

    def _tx(self):
        self.tx += 1
        return f"{self.tx:064x}"

    def _event(self, tx_id, event_type, subject="", **payload):
        self.event_log.append({"tx_id": tx_id, "event_type": event_type, "code_hash": subject, "payload": payload,
                               "recorded_at": f"2026-11-03T12:00:{len(self.event_log):02d}.000000000Z",
                               "msp_id": "TudelftMSP", "organization": self.researcher})

    def status(self):
        return {"backend": "hyperledger-fabric", "peer": "peer0.tudelft.svc.cluster.local:7051", "msp_id": "TudelftMSP",
                "height": 7, "current_block_hash": "ab" * 32, "previous_block_hash": "cd" * 32,
                "config": {"channel": "horus-governance"}}

    def submissions(self):
        return sorted(self.items.values(), key=lambda item: item["created_at"], reverse=True)

    def submission(self, code_hash):
        return self.items.get(code_hash)

    def submit(self, code, organizations):
        code_hash = digest(code)
        if code_hash in self.items:
            raise LedgerError("this code hash was already submitted", 409, "conflict")
        eligible = sorted(organization for organization in organizations if organization != self.researcher)
        if not eligible:
            raise LedgerError("select at least one reviewer outside the researcher's organization", 422, "invalid")
        tx_id = self._tx()
        item = {"code_hash": code_hash, "code_bytes": len(code.encode()), "status": "drawing",
                "researcher_org": self.researcher, "researcher_id": "r" * 32, "selected": sorted(organizations),
                "eligible": eligible, "created_at": datetime.now(timezone.utc).isoformat(), "commits": {}, "reveals": {},
                "defaulted": [], "seed": "", "reviewer": "", "selection_version": "", "analysis": None,
                "failure": None, "audits": [], "disputed": False, "tx_ids": {"CodeSubmitted": tx_id}}
        if len(eligible) == 1:
            item.update(status="assigned", reviewer=eligible[0], selection_version="single-eligible-v1")
        self.items[code_hash], self.codes[code_hash] = item, code
        self._event(tx_id, "CodeSubmitted", code_hash, code_hash=code_hash)
        return {"receipt": {"tx_id": tx_id, "block_number": self.tx}, "result": json.loads(json.dumps(item))}

    def complete(self, code_hash, decision="approved", reviewer=None, audit_match=True):
        """Simulate what the agents do: draw, analyze, audit."""
        item = self.items[code_hash]
        item["reviewer"] = reviewer or item["reviewer"] or item["eligible"][0]
        report = {"schema_version": 1, "code_hash": code_hash, "rules_hash": "1" * 64, "policy_hash": "2" * 64,
                  "semgrep_version": "1.145.0", "score": 100 if decision == "approved" else 0,
                  "counts": {"high": 0, "medium": 0, "low": 0}, "findings": [], "decision": decision,
                  "reasons": ["No high-severity findings and security score meets policy."]}
        report_json = json.dumps(report, sort_keys=True, separators=(",", ":"))
        tx_id = self._tx()
        item["analysis"] = {"organization": item["reviewer"], "msp_id": item["reviewer"].title() + "MSP",
                            "report_json": report_json, "report_hash": digest(report_json), "decision": decision,
                            "score": report["score"], "image_digest": "sha256:" + "a" * 64, "tx_id": tx_id,
                            "recorded_at": "2026-11-03T12:01:00.000000000Z"}
        item["status"] = decision
        item["tx_ids"]["CodeAnalyzed"] = tx_id
        self._event(tx_id, "CodeAnalyzed", code_hash, report_hash=digest(report_json))
        others = [organization for organization in item["eligible"] if organization != item["reviewer"]]
        for organization in others:
            item["audits"].append({"organization": organization, "match": audit_match,
                                   "report_hash": digest(report_json) if audit_match else "f" * 64})
            item["disputed"] = item["disputed"] or not audit_match

    def events(self):
        return list(self.event_log)

    def transaction(self, tx_id):
        return {"tx_id": tx_id, "valid": True, "validation_code": "VALID", "block_number": int(tx_id, 16)}

    def record_training(self, run_id, algorithm_id, organizations):
        if self.fail_training:
            raise LedgerError("Ledger gateway is unreachable.")
        if run_id not in self.trainings:
            tx_id = self._tx()
            self.trainings[run_id] = {"run_id": run_id, "algorithm_id": algorithm_id,
                                      "organizations": organizations, "tx_id": tx_id}
            self._event(tx_id, "TrainingStarted", "", run_id=run_id)
        return {"receipt": {"tx_id": self.trainings[run_id]["tx_id"]}, "result": self.trainings[run_id]}
