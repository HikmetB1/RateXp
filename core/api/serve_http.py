"""Serve the hook scripts; take feedback and consented transcripts."""

from __future__ import annotations

import os
import shlex
from contextlib import asynccontextmanager
from pathlib import Path

from api.build_trajectory import jsonl_to_atif
from api.ingest_records import ingest_feedback, ingest_transcript
from api.limit_request_rate import RateLimiter
from api.record_schemas import Feedback, Transcript
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import PlainTextResponse
from load_config import (
    DEFAULT_SURVEY_EVAL,
    DEFAULT_SURVEY_EVERY,
    EVALS,
    MAX_BODY_BYTES,
    RATE_LIMIT_PER_MINUTE,
)
from modules.write.dispatch_to_adapters import WriteError, close_adapters, get_adapters
from pydantic import ValidationError
from starlette.formparsers import MultiPartException
from starlette.middleware.base import BaseHTTPMiddleware

# core/, one level up from this package. Resolved from __file__ so the working
# directory doesn't matter.
CORE_DIR = Path(__file__).resolve().parent.parent
# One hook script per coding agent. Each is installed once by the person using
# the agent, and rates the whole session or any skill's most recent run in it.
CLAUDE_SH = CORE_DIR / "ratexp-claude.sh"
CURSOR_SH = CORE_DIR / "ratexp-cursor.sh"
URL_PLACEHOLDER = "'__RATEXP_URL__'"
EVERY_PLACEHOLDER = "'__RATEXP_EVERY__'"
EVAL_PLACEHOLDER = "'__RATEXP_EVAL__'"
EVALS_PLACEHOLDER = "'__RATEXP_EVALS__'"
PUBLIC_URL = os.environ.get("RATEXP_PUBLIC_URL", "http://localhost:8000").rstrip("/")

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


def _evals_as_shell_words() -> str:
    """Every eval as one line of shell words: its name, then its fields in order."""
    lines = (
        " ".join(shlex.quote(word) for word in (name, *survey)) for name, survey in EVALS.items()
    )
    return "".join(f"\n    {line}" for line in lines) + "\n"


def _serve_hook(path: Path) -> str:
    """Render deployment settings as shell literals in a downloadable hook."""
    return (
        path.read_text(encoding="utf-8")
        .replace(URL_PLACEHOLDER, shlex.quote(PUBLIC_URL))
        .replace(EVERY_PLACEHOLDER, shlex.quote(str(DEFAULT_SURVEY_EVERY)))
        .replace(EVAL_PLACEHOLDER, shlex.quote(DEFAULT_SURVEY_EVAL))
        .replace(EVALS_PLACEHOLDER, _evals_as_shell_words())
    )


# A route each, rather than one `/{hook}.sh`: a path parameter would make the name
# a path the request picks rather than a fixed route.
@app.get("/ratexp-claude.sh", response_class=PlainTextResponse)
def get_claude_hook() -> str:
    """The Claude Code hook: rates the session, or any skill's most recent run in it."""
    return _serve_hook(CLAUDE_SH)


@app.get("/ratexp-cursor.sh", response_class=PlainTextResponse)
def get_cursor_hook() -> str:
    """The Cursor hook: rates the session, or any skill's most recent run in it."""
    return _serve_hook(CURSOR_SH)


@app.post("/feedback", status_code=status.HTTP_201_CREATED)
async def post_feedback(request: Request) -> dict[str, str]:
    """Store feedback with an optional score (1 = good, 2 = bad) and comment."""
    data = await _read_body(request)
    try:
        record = Feedback(**data)
    except ValidationError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, e.errors()) from e
    try:
        ingest_feedback(record)
    except WriteError as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e)) from e
    return {"status": "stored"}


@app.post("/transcript", status_code=status.HTTP_201_CREATED)
async def post_transcript(request: Request) -> dict[str, str]:
    """Store a consented transcript supplied as raw JSONL or an ATIF object."""
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
        ingest_transcript(record)
    except WriteError as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e)) from e
    except Exception as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"transcript ingest failed: {e!r}") from e
    return {"status": "stored"}
