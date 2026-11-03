import fcntl
import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from sast.contracts import canonical_json


class IntegrityError(ValueError):
    pass


class Store:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.database = self.root / "governance.sqlite3"
        self.anchor = self.root / "ledger-head.json"
        with self.transaction() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS events (
                    sequence INTEGER PRIMARY KEY, tx_id TEXT UNIQUE NOT NULL, envelope TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS submissions (
                    code_hash TEXT PRIMARY KEY, code BLOB NOT NULL, status TEXT NOT NULL,
                    researcher_id TEXT NOT NULL, researcher_org TEXT NOT NULL,
                    reviewer TEXT NOT NULL, selection TEXT NOT NULL, created_at TEXT NOT NULL,
                    report TEXT, report_hash TEXT, provenance TEXT, error TEXT);
                CREATE TABLE IF NOT EXISTS algorithms (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, code_hash TEXT UNIQUE,
                    score INTEGER NOT NULL, executable INTEGER NOT NULL,
                    validation_source TEXT NOT NULL, report_hash TEXT);
                CREATE TABLE IF NOT EXISTS training_requests (
                    request_id TEXT PRIMARY KEY, payload TEXT NOT NULL, status TEXT NOT NULL,
                    created_at TEXT NOT NULL, run_id TEXT UNIQUE, result TEXT);
            """)
            if not self.anchor.exists() and connection.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0:
                self.write_anchor({"sequence": 0, "record_hash": "0" * 64})
        os.chmod(self.database, 0o600)

    def connect(self):
        connection = sqlite3.connect(self.database, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    @contextmanager
    def transaction(self):
        with (self.root / "writer.lock").open("a+b") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            connection = self.connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                yield connection
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
            finally:
                connection.close()

    def write_anchor(self, head):
        temporary = self.root / f".head-{uuid4().hex}"
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as target:
            target.write(canonical_json(head))
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary, self.anchor)

    def read_anchor(self):
        try:
            return json.loads(self.anchor.read_bytes())
        except (OSError, ValueError):
            raise IntegrityError("Ledger head anchor is missing or invalid.") from None