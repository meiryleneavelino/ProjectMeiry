import json
from datetime import datetime, timezone
from uuid import UUID

import httpx

from sast.contracts import canonical_json
from .ledger import LedgerError
from .service import BUILTIN


def now():
    return datetime.now(timezone.utc).isoformat()


class TrainingError(ValueError):
    def __init__(self, message, status=409):
        super().__init__(message)
        self.status = status


class TrainingBridge:
    """Starts the built-in training through the existing training API and records
    TrainingStarted on the Fabric ledger. Local SQLite only keeps idempotency."""

    def __init__(self, governance, transport=None):
        self.governance = governance
        self.transport = transport

    def client(self):
        try:
            token = self.governance.settings.training_token_file.read_text().strip()
        except OSError:
            raise TrainingError("Training credentials are unavailable.", 503) from None
        return httpx.Client(timeout=75, trust_env=False, transport=self.transport,
                            headers={"Authorization": f"Bearer {token}"})

    def start(self, payload, request_id):
        request_id = str(UUID(request_id))
        if payload["algorithm"] != BUILTIN:
            raise TrainingError("This validated algorithm is catalog-only. Execution awaits the sandbox phase.", 422)
        serialized = canonical_json(payload).decode()
        with self.governance.store.transaction() as connection:
            existing = connection.execute("SELECT * FROM training_requests WHERE request_id=?", (request_id,)).fetchone()
            if existing:
                if existing["payload"] != serialized:
                    raise TrainingError("This request key belongs to different parameters.")
                if existing["status"] != "completed":
                    raise TrainingError("This request is pending, failed or uncertain. Inspect it instead of resending.")
            else:
                connection.execute("INSERT INTO training_requests (request_id,payload,status,created_at) "
                                   "VALUES (?, ?, 'pending', ?)", (request_id, serialized, now()))
        if existing:
            return self.record(request_id)
        try:
            with self.client() as client:
                response = client.post(self.governance.settings.training_url + "/runs", json=payload)
            if not response.is_success:
                with self.governance.store.transaction() as connection:
                    connection.execute("UPDATE training_requests SET status='failed' WHERE request_id=?", (request_id,))
                raise TrainingError("The training API rejected this request.", response.status_code if response.status_code < 500 else 503)
            result = response.json()
            UUID(result["id"])
            return self.confirm(request_id, result)
        except TrainingError:
            with self.governance.store.transaction() as connection:
                connection.execute("UPDATE training_requests SET status='failed' WHERE request_id=? AND status='pending'", (request_id,))
            raise
        except Exception:
            with self.governance.store.transaction() as connection:
                connection.execute("UPDATE training_requests SET status='unknown' WHERE request_id=? AND status='pending'", (request_id,))
            raise TrainingError("Training outcome is uncertain. Inspect the training history; do not blindly retry.", 503) from None

    def confirm(self, request_id, result):
        with self.governance.store.transaction() as connection:
            connection.execute("UPDATE training_requests SET status='completed',run_id=?,result=? WHERE request_id=? "
                               "AND status!='completed'", (result["id"], canonical_json(result).decode(), request_id))
        return self.record(request_id)

    def record(self, request_id):
        """Write TrainingStarted to the ledger once. The chaincode is idempotent per
        run ID, so repeating the same request after a ledger outage is safe."""
        with self.governance.store.transaction() as connection:
            row = connection.execute("SELECT * FROM training_requests WHERE request_id=?", (request_id,)).fetchone()
        result, payload = json.loads(row["result"]), json.loads(row["payload"])
        if row["ledger_tx"]:
            return result
        try:
            recorded = self.governance.ledger.record_training(result["id"], payload["algorithm"], payload["organizations"])
        except LedgerError:
            raise TrainingError(f"Training run {result['id']} started, but TrainingStarted could not be written to "
                                "the ledger. Repeat the same request (same Idempotency-Key) to record it.", 503) from None
        with self.governance.store.transaction() as connection:
            connection.execute("UPDATE training_requests SET ledger_tx=? WHERE request_id=?",
                               (recorded["result"]["tx_id"], request_id))
        return result

    def request_status(self, request_id):
        with self.governance.store.transaction() as connection:
            row = connection.execute("SELECT request_id,status,created_at,run_id,ledger_tx FROM training_requests "
                                     "WHERE request_id=?", (str(UUID(request_id)),)).fetchone()
        if not row:
            raise LookupError("Training request not found.")
        return dict(row)

    def reconcile(self, request_id, run_id):
        request_id, run_id = str(UUID(request_id)), str(UUID(run_id))
        with self.governance.store.transaction() as connection:
            row = connection.execute("SELECT * FROM training_requests WHERE request_id=?", (request_id,)).fetchone()
        if not row or row["status"] not in ("pending", "unknown"):
            raise TrainingError("Only pending or uncertain requests can be reconciled.")
        with self.client() as client:
            response = client.get(self.governance.settings.training_url + f"/runs/{run_id}")
        if not response.is_success:
            raise TrainingError("The training run could not be verified.")
        result, expected = response.json(), json.loads(row["payload"])
        created_at = result.get("created_at")
        try:
            created_seconds = float(created_at) if isinstance(created_at, (int, float)) else datetime.fromisoformat(created_at).timestamp()
        except (ValueError, TypeError):
            raise TrainingError("Run creation time could not be verified.") from None
        if (result.get("id") != run_id or any(result.get(key) != value for key, value in expected.items())
                or created_seconds < datetime.fromisoformat(row["created_at"]).timestamp()):
            raise TrainingError("Run identity, parameters or creation time do not match this request.")
        return self.confirm(request_id, result)
