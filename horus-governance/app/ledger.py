import json
from abc import ABC, abstractmethod
from contextlib import contextmanager
from datetime import datetime, timezone
from uuid import uuid4

from sast.contracts import canonical_json, content_hash
from .storage import IntegrityError


FIELDS = {
    "CodeSubmitted": {"code_hash", "researcher_id", "researcher_org"},
    "ReviewerSelected": {"code_hash", "reviewer", "eligible", "excluded", "seed", "selection_version"},
    "CodeAnalyzed": {"code_hash", "reviewer", "image", "image_id", "image_digest", "digest_kind",
                     "rules_hash", "policy_hash", "semgrep_version", "report_hash", "score", "counts"},
    "CodeValidated": {"code_hash", "report_hash", "decision"},
    "CodeRejected": {"code_hash", "report_hash", "decision"},
    "AlgorithmRegistered": {"algorithm_id", "code_hash", "report_hash", "score", "validation_source", "executable"},
    "TrainingStarted": {"run_id", "algorithm_id", "organizations"},
}


def now():
    return datetime.now(timezone.utc).isoformat()


class LedgerBackend(ABC):
    @abstractmethod
    def verify(self):
        raise NotImplementedError

    @abstractmethod
    def events(self, event_type=None, code_hash=None, offset=0, limit=50):
        raise NotImplementedError

    @abstractmethod
    def append(self, event_type, payload):
        raise NotImplementedError

    @abstractmethod
    def get(self, tx_id):
        raise NotImplementedError


class SQLiteLedger(LedgerBackend):
    def __init__(self, store):
        self.store = store

    def check(self, connection):
        head = {"sequence": 0, "record_hash": "0" * 64}
        try:
            for row in connection.execute("SELECT * FROM events ORDER BY sequence"):
                event = json.loads(row["envelope"])
                expected_hash = event.pop("record_hash")
                if (event["sequence"] != head["sequence"] + 1 or row["sequence"] != event["sequence"]
                        or row["tx_id"] != event["tx_id"] or event["previous_hash"] != head["record_hash"]
                        or event["event_type"] not in FIELDS
                        or set(event["payload"]) != FIELDS[event["event_type"]]
                        or content_hash(canonical_json(event)) != expected_hash):
                    raise ValueError("Invalid event")
                head = {"sequence": event["sequence"], "record_hash": expected_hash}
        except (KeyError, TypeError, ValueError):
            raise IntegrityError("Ledger record integrity verification failed.") from None
        if self.store.read_anchor() != head:
            raise IntegrityError("Ledger head does not match the external anchor.")
        return head

    @contextmanager
    def transaction(self):
        with self.store.transaction() as connection:
            self.check(connection)
            yield connection
            row = connection.execute("SELECT envelope FROM events ORDER BY sequence DESC LIMIT 1").fetchone()
            head = {"sequence": 0, "record_hash": "0" * 64}
            if row:
                event = json.loads(row["envelope"])
                head = {"sequence": event["sequence"], "record_hash": event["record_hash"]}
            connection.commit()
            self.store.write_anchor(head)

    def append_in(self, connection, event_type, payload):
        if event_type not in FIELDS or set(payload) != FIELDS[event_type]:
            raise ValueError("Unexpected ledger event fields.")
        row = connection.execute("SELECT envelope FROM events ORDER BY sequence DESC LIMIT 1").fetchone()
        previous = json.loads(row["envelope"]) if row else {"sequence": 0, "record_hash": "0" * 64}
        event = {"version": 1, "sequence": previous["sequence"] + 1, "tx_id": f"local-{uuid4().hex}",
                 "event_type": event_type, "recorded_at": now(), "payload": payload,
                 "previous_hash": previous["record_hash"]}
        event["record_hash"] = content_hash(canonical_json(event))
        connection.execute("INSERT INTO events VALUES (?, ?, ?)",
                           (event["sequence"], event["tx_id"], canonical_json(event).decode()))
        return event

    def append(self, event_type, payload):
        with self.transaction() as connection:
            return self.append_in(connection, event_type, payload)

    def verify(self):
        try:
            with self.store.transaction() as connection:
                head = self.check(connection)
            return {"valid": True, **head, "backend": "sqlite-hash-chain"}
        except IntegrityError as error:
            return {"valid": False, "error": str(error), "backend": "sqlite-hash-chain"}

    def get(self, tx_id):
        with self.store.transaction() as connection:
            self.check(connection)
            row = connection.execute("SELECT envelope FROM events WHERE tx_id=?", (tx_id,)).fetchone()
        if row is None:
            raise LookupError("Ledger transaction not found.")
        return json.loads(row[0])

    def events(self, event_type=None, code_hash=None, offset=0, limit=50):
        with self.store.transaction() as connection:
            self.check(connection)
            rows = connection.execute("SELECT envelope FROM events ORDER BY sequence DESC").fetchall()
            events = [json.loads(row[0]) for row in rows]
        filtered = [event for event in events if (not event_type or event["event_type"] == event_type)
                    and (not code_hash or event["payload"].get("code_hash") == code_hash)]
        return {"items": filtered[offset:offset + limit], "total": len(filtered), "offset": offset, "limit": limit}