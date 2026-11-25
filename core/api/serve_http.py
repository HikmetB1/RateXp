"""Serve the plugin's hook settings and the docs site; take feedback and consented
transcripts."""

from __future__ import annotations

import json
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from api.build_trajectory import jsonl_to_atif
from api.ingest_records import ingest_feedback, ingest_transcript
from api.limit_request_rate import RateLimiter
from api.record_schemas import Feedback, Transcript
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles
from load_config import (
    DEFAULT_SURVEY_EVAL,
    DEFAULT_SURVEY_EVERY,
    EVALS,
    MAX_BODY_BYTES,
    RATE_LIMIT_PER_MINUTE,
)
from modules.redaction.redact_trajectory import warm_up_redaction
from modules.write.dispatch_to_adapters import WriteError, close_adapters, get_adapters
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool
from starlette.formparsers import MultiPartException
from starlette.middleware.base import BaseHTTPMiddleware

# core/, one level up from this package. Resolved from __file__ so the working
# directory doesn't matter.
CORE_DIR = Path(__file__).resolve().parent.parent
# The Claude Code plugin's manifest, in plugins/ beside core/ in the repo. The Dockerfile
# copies it to the same place beside /app, so this path holds in the image too. The Cursor
# plugin always has the same version.
PLUGIN_MANIFEST = CORE_DIR.parent / "plugins" / "claude-code" / ".claude-plugin" / "plugin.json"
# The newest plugin version. A hook from an older plugin shows the user how to update.
PLUGIN_VERSION: str = json.loads(PLUGIN_MANIFEST.read_text(encoding="utf-8"))["version"]

_limiter = RateLimiter(RATE_LIMIT_PER_MINUTE)
BODY_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Build the enabled write adapters now so PostgreSQL migrations run before the
    # dashboard reads. Adapter build is best-effort (a bad one is skipped), so this
    # never crash-loops at boot.
    try:
        get_adapters()
    except Exception:  # noqa: BLE001 - a destination may not be ready at boot
        pass
    # In the background, so core answers /healthz while presidio loads its models.
    threading.Thread(target=warm_up_redaction, name="warm-up-redaction", daemon=True).start()
    yield
    close_adapters()


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

        # Enforce the cap for streamed uploads without Content-Length too.
        if request.method in BODY_METHODS:
            body = bytearray()
            async for chunk in request.stream():
                body += chunk
                if len(body) > MAX_BODY_BYTES:
                    return PlainTextResponse("request body too large", status_code=413)
            # Starlette replays the cached body to the route.
            request._body = bytes(body)

        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        return response


app.add_middleware(SecurityMiddleware)


async def _read_body(request: Request) -> dict:
    """Read JSON (seeder) or text form fields (hook), normalizing an optional score."""
    ct = (request.headers.get("content-type") or "").lower()
    if not ct.startswith(("application/x-www-form-urlencoded", "multipart/form-data")):
        try:
            data = await request.json()
        except (ValueError, RecursionError) as e:  # bad syntax, bad UTF-8, absurd nesting
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "body is not valid JSON"
            ) from e
        if not isinstance(data, dict):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "JSON body must be an object")
        return data
    try:
        # A transcript is one text field and may exceed Starlette's default 1 MiB.
        async with request.form(max_part_size=MAX_BODY_BYTES) as form:
            data = {name: value for name, value in form.multi_items() if isinstance(value, str)}
    except (ValueError, MultiPartException) as e:  # truncated or malformed parts
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "body is not a valid form") from e
    score = data.pop("score", "").strip()
    if score:
        if score not in {"1", "2"}:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "score must be 1 or 2")
        data["score"] = int(score)
    return data


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/hook-settings")
def get_hook_settings() -> dict:
    """What the plugin's hooks ask for at session start: the evals, the default eval,
    how many turns pass between surveys, and the newest plugin version."""
    return {
        "plugin_version": PLUGIN_VERSION,
        "every": DEFAULT_SURVEY_EVERY,
        "default_eval": DEFAULT_SURVEY_EVAL,
        "evals": [{"name": name, **survey._asdict()} for name, survey in EVALS.items()],
    }


@app.post("/feedback", status_code=status.HTTP_201_CREATED)
async def post_feedback(request: Request) -> dict[str, str]:
    """Store feedback with an optional score (1 = good, 2 = bad) and comment, labeled."""
    data = await _read_body(request)
    try:
        record = Feedback(**data)
    except ValidationError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, e.errors()) from e
    # Labeling waits on a model; in a worker thread, so other requests go on meanwhile.
    try:
        await run_in_threadpool(ingest_feedback, record)
    except WriteError as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e)) from e
    return {"status": "stored"}


@app.post("/transcript", status_code=status.HTTP_201_CREATED)
async def post_transcript(request: Request) -> dict[str, str]:
    """Store a consented transcript supplied as raw JSONL or an ATIF object. The rating's
    score and comment may come along: core labels the conversation with them, and stores
    neither on the transcript."""
    data = await _read_body(request)
    raw = data.pop("transcript", None)
    if raw is not None:
        raw = str(raw)
        if not raw.strip():
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "empty transcript")
        session_id = str(data.get("session_id") or "") or None
        data["atif"] = jsonl_to_atif(raw, session_id=session_id, agent=str(data.get("agent") or ""))
    try:
        record = Transcript(**data)
    except ValidationError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, e.errors()) from e
    # ingest_transcript size-limits, redacts (fail-closed), then stores. A dropped
    # upload is a 502; nothing accepting it is a 503. The rating is already safe.
    try:
        await run_in_threadpool(ingest_transcript, record)
    except WriteError as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e)) from e
    except Exception as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"transcript ingest failed: {e!r}") from e
    return {"status": "stored"}


# The docs site docs-server/ builds. core's Dockerfile builds it into the image at the
# same path relative to core/ as on a dev machine. Mounted last so it never shadows a
# route above, and only where it was built, so core still starts without it.
GUIDE_DIR = CORE_DIR.parent / "docs-server" / "site"
if GUIDE_DIR.is_dir():
    app.mount("/guide", StaticFiles(directory=GUIDE_DIR, html=True), name="guide")
