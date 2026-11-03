import json
import re

from sast.contracts import (build_report, canonical_json, content_hash, normalize_code,
                            verify_report)
from sast.docker_runner import ROOT, analyze_in_docker, organizations
from .ledger import SQLiteLedger, now
from .reviewer import KNOWN_ORGANIZATIONS, select_reviewer
from .storage import IntegrityError, Store


BUILTIN = "logistic-regression-v1"


class Governance:
    def __init__(self, settings):
        if (settings.organization not in KNOWN_ORGANIZATIONS
                or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{7,63}", settings.pseudonym)):
            raise ValueError("Invalid server-side researcher configuration.")
        self.settings = settings
        self.store = Store(settings.state_root)
        self.ledger = SQLiteLedger(self.store)
        with self.ledger.transaction() as connection:
            if not connection.execute("SELECT 1 FROM algorithms WHERE id=?", (BUILTIN,)).fetchone():
                connection.execute("INSERT INTO algorithms VALUES (?, ?, ?, ?, ?, ?, ?)",
                                   (BUILTIN, "Logistic regression (FedAvg)", None, 100, 1, "builtin-trusted", None))
                self.ledger.append_in(connection, "AlgorithmRegistered", {
                    "algorithm_id": BUILTIN, "code_hash": None, "report_hash": None,
                    "score": 100, "validation_source": "builtin-trusted", "executable": True})

    def submit(self, content, selected):
        code = normalize_code(content)
        selection = select_reviewer(selected, self.settings.organization)
        code_hash = content_hash(code)
        with self.ledger.transaction() as connection:
            existing = connection.execute("SELECT 1 FROM submissions WHERE code_hash=?", (code_hash,)).fetchone()
            if not existing:
                if connection.execute("SELECT COUNT(*) FROM submissions WHERE status IN ('queued','running')").fetchone()[0] >= 20:
                    raise ValueError("The analysis queue is full. Try again later.")
                connection.execute("""INSERT INTO submissions
                    (code_hash,code,status,researcher_id,researcher_org,reviewer,selection,created_at)
                    VALUES (?, ?, 'queued', ?, ?, ?, ?, ?)""",
                                   (code_hash, code, self.settings.pseudonym, self.settings.organization,
                                    selection["reviewer"], canonical_json(selection).decode(), now()))
                self.ledger.append_in(connection, "CodeSubmitted", {
                    "code_hash": code_hash, "researcher_id": self.settings.pseudonym,
                    "researcher_org": self.settings.organization})
                self.ledger.append_in(connection, "ReviewerSelected", {"code_hash": code_hash, **selection})
        return self.submission(code_hash), bool(existing)

    def submission(self, code_hash):
        with self.ledger.transaction() as connection:
            row = connection.execute("SELECT * FROM submissions WHERE code_hash=?", (code_hash,)).fetchone()
            if row is None:
                raise LookupError("Submission not found.")
            item = {"code_hash": row["code_hash"], "status": row["status"],
                    "selection": json.loads(row["selection"]), "created_at": row["created_at"],
                    "report": json.loads(row["report"]) if row["report"] else None,
                    "report_hash": row["report_hash"],
                    "provenance": json.loads(row["provenance"]) if row["provenance"] else None,
                    "error": row["error"]}
        events = self.ledger.events(code_hash=code_hash, limit=500)["items"]
        item["tx_ids"] = {event["event_type"]: event["tx_id"] for event in events}
        if item["report"] and not self.verify_submission(code_hash)["valid"]:
            raise IntegrityError("Stored report integrity verification failed.")
        return item

    def verify_submission(self, code_hash):
        with self.ledger.transaction() as connection:
            row = connection.execute("SELECT report,report_hash FROM submissions WHERE code_hash=?", (code_hash,)).fetchone()
        if row is None or not row["report"]:
            raise LookupError("No stored report for this submission.")
        events = self.ledger.events(code_hash=code_hash, limit=500)["items"]
        analyzed = next((event for event in events if event["event_type"] == "CodeAnalyzed"), None)
        try:
            report = json.loads(row["report"])
            actual_hash = content_hash(canonical_json(report))
            expected_hash = analyzed["payload"]["report_hash"] if analyzed else None
            valid = row["report_hash"] == expected_hash and verify_report(report, expected_hash)
        except (ValueError, TypeError):
            actual_hash, expected_hash, valid = None, None, False
        return {"valid": valid, "code_hash": code_hash, "expected_hash": expected_hash,
                "actual_hash": actual_hash, "tx_id": analyzed["tx_id"] if analyzed else None}

    def catalog(self):
        with self.ledger.transaction() as connection:
            rows = connection.execute("SELECT * FROM algorithms ORDER BY executable DESC,name").fetchall()
        events = self.ledger.events(event_type="AlgorithmRegistered", limit=500)["items"]
        transactions = {event["payload"]["algorithm_id"]: event["tx_id"] for event in events}
        return [{**dict(row), "executable": bool(row["executable"]),
                 "registration_tx_id": transactions.get(row["id"])} for row in rows]

    def work_once(self, analyzer=analyze_in_docker):
        with self.ledger.transaction() as connection:
            row = connection.execute("SELECT * FROM submissions WHERE status='queued' ORDER BY created_at LIMIT 1").fetchone()
            if row is None:
                return False
            connection.execute("UPDATE submissions SET status='running' WHERE code_hash=?", (row["code_hash"],))
            job = dict(row)
        try:
            envelope = analyzer(bytes(job["code"]), job["reviewer"])
            report, provenance = envelope["report"], envelope["provenance"]
            rules_bytes = (ROOT / "sast/rules.yaml").read_bytes()
            rules = {rule["id"]: rule for rule in json.loads(rules_bytes)["rules"]}
            policy = json.loads((ROOT / "config/policy.json").read_bytes())
            if any(finding["message"] != rules[finding["rule_id"]]["message"]
                   or finding["severity"] != rules[finding["rule_id"]]["metadata"]["horus_severity"]
                   for finding in report["findings"]):
                raise ValueError("Unexpected scanner finding")
            expected = build_report(bytes(job["code"]), report["findings"], policy,
                                    content_hash(rules_bytes), "1.145.0")
            if (expected["report"] != report or expected["report_hash"] != envelope["report_hash"]
                    or provenance["organization"] != job["reviewer"]
                    or provenance["image"] != organizations()[job["reviewer"]]["image"]
                    or not re.fullmatch(r"sha256:[0-9a-f]{64}", provenance["digest"])):
                raise ValueError("Unexpected scanner report")
            with self.ledger.transaction() as connection:
                connection.execute("""UPDATE submissions SET status=?,report=?,report_hash=?,provenance=?
                    WHERE code_hash=?""", (report["decision"], canonical_json(report).decode(),
                                          envelope["report_hash"], canonical_json(provenance).decode(), job["code_hash"]))
                self.ledger.append_in(connection, "CodeAnalyzed", {
                    "code_hash": job["code_hash"], "reviewer": job["reviewer"], "image": provenance["image"],
                    "image_id": provenance["image_id"], "image_digest": provenance["digest"],
                    "digest_kind": provenance["digest_kind"], "rules_hash": report["rules_hash"],
                    "policy_hash": report["policy_hash"], "semgrep_version": report["semgrep_version"],
                    "report_hash": envelope["report_hash"], "score": report["score"], "counts": report["counts"]})
                approved = report["decision"] == "approved"
                self.ledger.append_in(connection, "CodeValidated" if approved else "CodeRejected", {
                    "code_hash": job["code_hash"], "report_hash": envelope["report_hash"], "decision": report["decision"]})
                if approved:
                    algorithm_id = f"submitted-{job['code_hash']}"
                    connection.execute("INSERT INTO algorithms VALUES (?, ?, ?, ?, ?, ?, ?)",
                                       (algorithm_id, f"Submitted algorithm {job['code_hash'][:12]}", job["code_hash"],
                                        report["score"], 0, "semgrep", envelope["report_hash"]))
                    self.ledger.append_in(connection, "AlgorithmRegistered", {
                        "algorithm_id": algorithm_id, "code_hash": job["code_hash"],
                        "report_hash": envelope["report_hash"], "score": report["score"],
                        "validation_source": "semgrep", "executable": False})
        except IntegrityError:
            raise
        except Exception:
            with self.ledger.transaction() as connection:
                connection.execute("UPDATE submissions SET status='error',error=? WHERE code_hash=?",
                                   ("Analysis could not complete safely; no approval was issued.", job["code_hash"]))
        return True