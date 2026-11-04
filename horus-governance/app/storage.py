"""Local operational state of the Horus API.

Only idempotency records for training requests live here. Governance history
(submissions, draws, analyses, audits, training starts) lives on the Fabric
ledger. A governance.sqlite3 from the previous SQLite hash-chain version may
still contain old tables; they are left untouched and no longer read.
"""
import fcntl
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path


class Store:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.database = self.root / "governance.sqlite3"
        with self.transaction() as connection:
            connection.execute("""CREATE TABLE IF NOT EXISTS training_requests (
                request_id TEXT PRIMARY KEY, payload TEXT NOT NULL, status TEXT NOT NULL,
                created_at TEXT NOT NULL, run_id TEXT UNIQUE, result TEXT)""")
            columns = {row[1] for row in connection.execute("PRAGMA table_info(training_requests)")}
            if "ledger_tx" not in columns:
                connection.execute("ALTER TABLE training_requests ADD COLUMN ledger_tx TEXT")
        os.chmod(self.database, 0o600)

    def connect(self):
        connection = sqlite3.connect(self.database, timeout=30)
        connection.row_factory = sqlite3.Row
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
