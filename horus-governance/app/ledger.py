"""Client for the Hyperledger Fabric governance ledger.

The Horus API does not keep the governance history itself any more. It calls
the researcher gateway (Go service in the researcher organization's namespace),
which signs transactions with the researcher's Fabric identity and reads from
that organization's own peer. The ledger content is replicated on the peers of
UVA, VU and TUDELFT; no single server holds the authoritative copy.
"""
import httpx


EVENT_TYPES = (
    "ConfigInitialized", "CodeSubmitted", "SeedCommitted", "SeedRevealed", "DrawForced", "ReviewerSelected",
    "CodeAnalyzed", "CodeValidated", "CodeRejected", "AlgorithmRegistered", "AnalysisFailed",
    "AnalysisAudited", "TrainingStarted",
)


class LedgerError(ValueError):
    """A ledger answer that the API forwards with an HTTP status."""

    def __init__(self, message, status=503, kind="unavailable"):
        super().__init__(message)
        self.status = status
        self.kind = kind


class FabricLedger:
    backend = "hyperledger-fabric"

    def __init__(self, url, token_file, transport=None):
        self.url = url.rstrip("/")
        self.token_file = token_file
        self.transport = transport

    def _request(self, method, path, **arguments):
        try:
            token = self.token_file.read_text().strip()
        except OSError:
            raise LedgerError("Ledger gateway credentials are unavailable. Run 'python3 tools.py ledger setup'.") from None
        try:
            with httpx.Client(timeout=120, trust_env=False, transport=self.transport,
                              headers={"Authorization": f"Bearer {token}"}) as client:
                response = client.request(method, self.url + path, **arguments)
        except httpx.HTTPError:
            raise LedgerError("Ledger gateway is unreachable. Is 'python3 tools.py ledger forward' running?") from None
        try:
            body = response.json()
        except ValueError:
            body = None
        if not response.is_success:
            detail = body.get("detail") if isinstance(body, dict) else None
            kind = body.get("kind", "unavailable") if isinstance(body, dict) else "unavailable"
            raise LedgerError(detail or f"Ledger gateway error ({response.status_code})", response.status_code, kind)
        return body

    def status(self):
        return self._request("GET", "/status")

    def config(self):
        return self._request("GET", "/config")

    def submissions(self):
        return self._request("GET", "/submissions") or []

    def submission(self, code_hash):
        try:
            return self._request("GET", f"/submissions/{code_hash}")
        except LedgerError as error:
            if error.status == 404:
                return None
            raise

    def submit(self, code, organizations):
        return self._request("POST", "/submissions", json={"code": code, "organizations": organizations})

    def events(self):
        return self._request("GET", "/events") or []

    def transaction(self, tx_id):
        return self._request("GET", f"/transactions/{tx_id}")

    def record_training(self, run_id, algorithm_id, organizations):
        return self._request("POST", "/training-starts", json={
            "run_id": run_id, "algorithm_id": algorithm_id, "organizations": organizations})
