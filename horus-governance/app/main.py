import hmac
import json
import re
from time import time
from typing import Literal
from uuid import UUID

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.datastructures import UploadFile

from sast.contracts import AnalysisError, MAX_CODE_BYTES, validate_filename
from .ledger import FIELDS
from .service import Governance
from .settings import Settings
from .storage import IntegrityError
from .training_bridge import TrainingBridge, TrainingError


Organization = Literal["UVA", "VU", "TUDELFT"]


class SubmissionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str
    organizations: list[Organization] = Field(min_length=1, max_length=3)


class TrainingInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    algorithm: str
    organizations: list[Organization] = Field(min_length=2, max_length=3)
    dataset_id: Literal["synthetic-local-v1"]
    rounds: int = Field(ge=1, le=10)
    local_epochs: int = Field(ge=1, le=5)


class BoundedBody:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        chunks, size = [], 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            size += len(chunk)
            if size > 6 * MAX_CODE_BYTES + 65536:
                return await JSONResponse({"detail": "Request body is too large."}, status_code=413)(scope, receive, send)
            chunks.append(chunk)
            if not message.get("more_body", False):
                break
        delivered = False
        async def replay():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": b"".join(chunks), "more_body": False}
            return await receive()
        await self.app(scope, replay, send)


def create_app(settings=None, transport=None):
    settings = settings or Settings.load()
    governance = Governance(settings)
    bridge = TrainingBridge(governance, transport)
    token = settings.token()
    app = FastAPI(title="Horus governance", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.governance = governance
    app.add_middleware(BoundedBody)

    @app.middleware("http")
    async def authentication(request: Request, call_next):
        if request.url.path != "/health":
            if not hmac.compare_digest(request.headers.get("authorization", ""), f"Bearer {token}"):
                return JSONResponse({"detail": "Authentication required."}, status_code=401)
            origin = request.headers.get("origin")
            if origin and origin not in ("http://127.0.0.1:5175", "http://localhost:5175"):
                return JSONResponse({"detail": "Origin not permitted."}, status_code=403)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, error):
        return JSONResponse({"detail": "Invalid request fields or values."}, status_code=422)

    @app.exception_handler(IntegrityError)
    async def integrity_error(request, error):
        return JSONResponse({"detail": str(error)}, status_code=409)

    @app.exception_handler(AnalysisError)
    async def analysis_error(request, error):
        return JSONResponse({"detail": str(error)}, status_code=422)

    @app.exception_handler(TrainingError)
    async def training_error(request, error):
        return JSONResponse({"detail": str(error)}, status_code=error.status)

    @app.exception_handler(LookupError)
    async def missing(request, error):
        return JSONResponse({"detail": str(error)}, status_code=404)

    @app.exception_handler(ValueError)
    async def invalid(request, error):
        return JSONResponse({"detail": "Invalid input or no eligible reviewer."}, status_code=422)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/me")
    def me():
        return {"name": settings.name, "organization": settings.organization, "pseudonym": settings.pseudonym}

    @app.get("/status")
    def status():
        verification = governance.ledger.verify()
        try:
            heartbeat = json.loads((settings.state_root / "worker-status.json").read_bytes())
            worker_ready = 0 <= time() - heartbeat["updated_at"] < 180
        except (OSError, ValueError, KeyError, TypeError):
            worker_ready = False
        return {"ledger": verification, "worker_ready": worker_ready, "mode": "local-development", "blockchain": False}

    @app.get("/algorithms")
    def algorithms():
        return governance.catalog()

    @app.get("/submissions")
    def submissions():
        with governance.ledger.transaction() as connection:
            rows = connection.execute("SELECT code_hash,status,created_at FROM submissions ORDER BY created_at DESC LIMIT 50").fetchall()
        return [dict(row) for row in rows]

    @app.post("/submissions")
    async def submit(request: Request):
        try:
            if request.headers.get("content-type", "").startswith("multipart/form-data"):
                async with request.form(max_files=1, max_fields=1) as form:
                    if set(form) != {"file", "organizations"} or len(form.multi_items()) != 2:
                        raise HTTPException(422, "Only file and organizations are accepted.")
                    uploaded = form["file"]
                    if not isinstance(uploaded, UploadFile):
                        raise HTTPException(422, "An uploaded .py or .txt file is required.")
                    validate_filename(uploaded.filename)
                    content = await uploaded.read(MAX_CODE_BYTES + 1)
                    selected = json.loads(form["organizations"])
            else:
                data = SubmissionInput.model_validate(await request.json())
                content, selected = data.code.encode("utf-8", errors="strict"), data.organizations
        except (UnicodeError, json.JSONDecodeError):
            raise HTTPException(422, "Valid UTF-8 text and organization fields are required.") from None
        item, reused = governance.submit(content, selected)
        return JSONResponse({**item, "reused": reused}, status_code=200 if reused else 202)

    def checked_hash(code_hash):
        if not re.fullmatch(r"[0-9a-f]{64}", code_hash):
            raise HTTPException(422, "A SHA-256 code hash is required.")
        return code_hash

    @app.get("/submissions/{code_hash}")
    def submission(code_hash: str):
        return governance.submission(checked_hash(code_hash))

    @app.post("/reports/{code_hash}/verify")
    def verify(code_hash: str):
        return governance.verify_submission(checked_hash(code_hash))

    @app.get("/ledger/events")
    def events(event_type: str | None = None, code_hash: str | None = None, offset: int = 0, limit: int = 50):
        if event_type and event_type not in FIELDS:
            raise HTTPException(422, "Unknown event type.")
        if code_hash:
            checked_hash(code_hash)
        if offset < 0 or not 1 <= limit <= 100:
            raise HTTPException(422, "Invalid pagination.")
        return governance.ledger.events(event_type, code_hash, offset, limit)

    @app.post("/ledger/verify")
    def verify_chain():
        return governance.ledger.verify()

    @app.get("/ledger/events/{tx_id}")
    def event_detail(tx_id: str):
        if not re.fullmatch(r"local-[0-9a-f]{32}", tx_id):
            raise HTTPException(422, "Invalid transaction ID.")
        return governance.ledger.get(tx_id)

    @app.post("/training/runs", status_code=202)
    def start_training(data: TrainingInput, idempotency_key: str = Header()):
        if len(set(data.organizations)) != len(data.organizations):
            raise HTTPException(422, "Organizations must be distinct.")
        return bridge.start(data.model_dump(), idempotency_key)

    @app.get("/training/requests/{request_id}")
    def request_status(request_id: UUID):
        return bridge.request_status(str(request_id))

    @app.post("/training/requests/{request_id}/reconcile")
    def reconcile(request_id: UUID, run_id: UUID):
        return bridge.reconcile(str(request_id), str(run_id))

    return app