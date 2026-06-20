"""Public service: hosts the RateXp MCP server, a health check, and transcript upload.

This is the only externally reachable surface in the system. Skills point their
MCP client at /mcp; the MCP tools (see mcp_app.py) take the rating and write it to
PostgreSQL. The consented trajectory is too large to flow through the model, so it
is uploaded straight here over plain HTTP (POST /transcript) by a small helper
script we serve at /upload_transcript.sh.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from atif import claude_jsonl_to_atif
from config import MAX_BODY_BYTES, RATE_LIMIT_PER_MINUTE
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import PlainTextResponse
from ingest import ingest_transcript
from mcp_app import mcp
from models import Transcript
from pydantic import ValidationError
from ratelimit import RateLimiter
from starlette.middleware.base import BaseHTTPMiddleware
from store import close_store, get_store

UPLOAD_TRANSCRIPT_SH = Path(__file__).resolve().parent / "scripts" / "upload_transcript.sh"

_limiter = RateLimiter(RATE_LIMIT_PER_MINUTE)


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Open the store now so migrations run before the dashboard reads. If the DB
    # isn't ready, open lazily on first write instead of crash-looping at boot.
    try:
        get_store()
    except Exception:  # noqa: BLE001 - DB may not be ready at boot
        pass
    # A mounted sub-app's lifespan isn't run for us, so drive the MCP session
    # manager here for the life of the app (the mount below created it).
    async with mcp.session_manager.run():
        yield
    close_store()


app = FastAPI(title="ratexp-core", version="1.0.0", lifespan=lifespan)


class SecurityMiddleware(BaseHTTPMiddleware):
    """Caps request body size, rate-limits per client IP, adds safe headers."""

    async def dispatch(self, request: Request, call_next):
        length = request.headers.get("content-length")
        if length is not None and length.isdigit() and int(length) > MAX_BODY_BYTES:
            return PlainTextResponse("request body too large", status_code=413)

        client_ip = (request.client.host if request.client else "") or "unknown"
        if not _limiter.allow(client_ip):
            return PlainTextResponse("rate limit exceeded", status_code=429)

        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        return response


app.add_middleware(SecurityMiddleware)

# Streamable-HTTP MCP at /mcp. This call creates the session manager that the
# lifespan above runs; it must execute at import time (it does, here).
app.mount("/mcp", mcp.streamable_http_app())


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/upload_transcript.sh", response_class=PlainTextResponse)
def get_upload_transcript_sh() -> str:
    """POSIX-shell helper that uploads the local session transcript on consent.

    Runs on the consumer's machine (only it can read its own transcript). The
    prompt pipes it into `sh` so the raw .jsonl goes up behind a single approval,
    never through the model's context.
    """
    return UPLOAD_TRANSCRIPT_SH.read_text(encoding="utf-8")


@app.post("/transcript", status_code=status.HTTP_201_CREATED)
async def post_transcript(request: Request) -> dict[str, str]:
    """Receive a consented session transcript, convert to ATIF, persist it.

    The helper posts the raw .jsonl as form field `transcript`; we convert it
    server-side. A JSON body with a ready-built `atif` also works (tests / the
    seeder's MCP path mirrors this).
    """
    ct = (request.headers.get("content-type") or "").lower()
    if ct.startswith("application/x-www-form-urlencoded") or ct.startswith("multipart/form-data"):
        form = await request.form()
        raw = str(form.get("transcript") or "")
        if not raw.strip():
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "empty transcript")
        session_id = (str(form.get("session_id")) if form.get("session_id") else None) or None
        agent = str(form.get("agent") or "unknown")
        data: dict = {
            "session_id": session_id,
            "skill_name": str(form.get("skill_name") or "unknown"),
            "agent": agent,
            "atif": claude_jsonl_to_atif(raw, session_id=session_id, agent=agent),
            "request_id": (str(form.get("request_id")) if form.get("request_id") else None) or None,
        }
    else:
        data = await request.json()
    try:
        record = Transcript(**data)
    except ValidationError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, e.errors()) from e
    # ingest_transcript size-limits, redacts (fail-closed), then stores. Any
    # failure means the upload is dropped - the rating is already safe.
    try:
        ingest_transcript(record)
    except Exception as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"transcript ingest failed: {e!r}") from e
    return {"status": "stored"}
