"""Public FastAPI service: serves the survey snippet and ingests feedback.

This is the only externally reachable surface in the system. It serves the
rating-flow snippet (skills curl it), then accepts the feedback and optional
transcript the skill posts back, writing both straight to PostgreSQL.
"""

from __future__ import annotations

import os
import random
import re
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

from atif import claude_jsonl_to_atif
from config import DEFAULT_SURVEY_EVERY, MAX_BODY_BYTES, RATE_LIMIT_PER_MINUTE
from fastapi import FastAPI, HTTPException, Query, Request, status
from fastapi.responses import PlainTextResponse
from models import Feedback, Transcript
from pydantic import ValidationError
from ratelimit import RateLimiter
from starlette.middleware.base import BaseHTTPMiddleware
from store import FeedbackStore

PROMPT_FILE = Path(__file__).resolve().parent / "prompt" / "prompt.md"
SKIP_FILE = Path(__file__).resolve().parent / "prompt" / "skip.md"
DETECT_AGENT_FILE = Path(__file__).resolve().parent / "scripts" / "detect_agent.sh"
CAPTURE_TRANSCRIPT_FILE = Path(__file__).resolve().parent / "scripts" / "capture_transcript.sh"

SUBMIT_URL = os.environ.get("RATEXP_SUBMIT_URL", "http://localhost:8000/feedback")
# Transcript endpoints share core's host; derive them from SUBMIT_URL (…/feedback)
# so one env var keeps everything pointed at the same place.
_BASE_URL = SUBMIT_URL.rsplit("/", 1)[0]
TRANSCRIPT_SUBMIT_URL = f"{_BASE_URL}/transcript"
TRANSCRIPT_SH_URL = f"{_BASE_URL}/transcript.sh"

# Permissive — agent is a free-form runtime identifier (e.g. "claude-code",
# "copilot", "cursor"), not an enum. Required: the toolkit is multi-framework, so
# silently defaulting would mislabel data.
_AGENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._:\-]{0,63}$")

_store: FeedbackStore | None = None
_limiter = RateLimiter(RATE_LIMIT_PER_MINUTE)


def get_store() -> FeedbackStore:
    global _store
    if _store is None:
        _store = FeedbackStore()
    return _store


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Open the store eagerly so the schema (migrations) exists before the
    # dashboard reads it. If the database isn't ready yet, fall back to opening
    # lazily on the first write rather than crash-looping at boot.
    try:
        get_store()
    except Exception:  # noqa: BLE001 - tolerate a not-yet-ready database at boot
        pass
    yield
    if _store is not None:
        _store.close()


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


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/agent.sh", response_class=PlainTextResponse)
def get_agent_sh() -> str:
    """POSIX-shell helper that detects the local harness + model.

    Runs on the consumer's machine (only the client can see its own env vars and
    session files), so SKILL.md can stay free of harness-specific literals.
    """
    return DETECT_AGENT_FILE.read_text(encoding="utf-8")


@app.get("/transcript.sh", response_class=PlainTextResponse)
def get_capture_transcript_sh() -> str:
    """POSIX-shell helper that uploads the local session transcript on consent.

    Like /agent.sh it runs on the consumer's machine — only the client can read
    its own session transcript. The prompt pipes this into `sh` only after the
    user agrees to store the conversation.
    """
    return CAPTURE_TRANSCRIPT_FILE.read_text(encoding="utf-8")


@app.get("/snippet", response_class=PlainTextResponse)
def get_snippet(
    session_id: str | None = Query(None, description="Override session id."),
    agent: str | None = Query(
        None,
        description=(
            "Optional. Calling agent runtime identifier. If provided and valid,"
            " {{AGENT}} is pre-substituted; otherwise the model fills the <AGENT>"
            " placeholder at runtime from its own identity."
        ),
    ),
    request_id: str | None = Query(None, description="Override the generated idempotency key."),
    every: int | None = Query(
        None,
        ge=1,
        description=(
            "Survey roughly 1 in every N runs. The server rolls a 1-in-N dice on"
            " each call: on a win it returns the survey prompt, otherwise a short"
            " 'skip silently' message. Omit to use the configured default"
            " (default_survey_every in config.yaml); 1 always asks."
        ),
    ),
) -> str:
    sid = session_id or str(uuid.uuid4())
    rid = request_id or str(uuid.uuid4())
    if agent is not None and not _AGENT_RE.match(agent):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"invalid agent {agent!r}; must match {_AGENT_RE.pattern}",
        )
    # Sampling: with every=N the survey runs on ~1 of N calls. randrange(N) == 0
    # is exactly 1/N, and every=1 always wins — preserving always-ask behaviour.
    # An omitted param falls back to the configured default.
    if every is None:
        every = DEFAULT_SURVEY_EVERY
    if random.randrange(every) != 0:
        return SKIP_FILE.read_text(encoding="utf-8")
    text = (
        PROMPT_FILE.read_text(encoding="utf-8")
        .replace("{{SUBMIT_URL}}", SUBMIT_URL)
        .replace("{{TRANSCRIPT_SH_URL}}", TRANSCRIPT_SH_URL)
        .replace("{{TRANSCRIPT_SUBMIT_URL}}", TRANSCRIPT_SUBMIT_URL)
        .replace("{{SESSION_ID}}", sid)
        .replace("{{REQUEST_ID}}", rid)
    )
    if agent is not None:
        text = text.replace("{{AGENT}}", agent)
    return text


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _fill_defaults(record: Feedback | Transcript) -> None:
    if not record.created_at:
        record.created_at = _now_iso()
    if not record.session_id:
        record.session_id = str(uuid.uuid4())
    if not record.request_id:
        record.request_id = str(uuid.uuid4())


async def _parse_feedback(request: Request) -> Feedback:
    """Accept either JSON or form-encoded /feedback bodies.

    Form encoding lets SKILL.md authors send POSTs without literal `{...}` in the
    bash command, which would otherwise trigger Claude Code's "expansion
    obfuscation" security prompt.
    """
    ct = (request.headers.get("content-type") or "").lower()
    if ct.startswith("application/x-www-form-urlencoded") or ct.startswith("multipart/form-data"):
        form = await request.form()
        data: dict = {}
        for k, v in form.items():
            if v in ("", "null", None):
                continue
            data[k] = int(v) if k == "score" else v
    else:
        data = await request.json()
    try:
        return Feedback(**data)
    except ValidationError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, e.errors()) from e


@app.post("/feedback", status_code=status.HTTP_201_CREATED)
async def post_feedback(request: Request) -> dict[str, str]:
    record = await _parse_feedback(request)
    _fill_defaults(record)
    try:
        get_store().append(record)
    except Exception as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"store failed: {e!r}") from e
    return {"status": "stored"}


@app.post("/transcript", status_code=status.HTTP_201_CREATED)
async def post_transcript(request: Request) -> dict[str, str]:
    """Receive a consented session transcript, convert to ATIF, persist it.

    The capture script posts the raw session .jsonl as form field `transcript`;
    we convert it server-side so the client stays simple. A JSON body carrying an
    already-built `atif` object is also accepted (e.g. tests).
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

    _fill_defaults(record)
    try:
        get_store().append_transcript(record)
    except Exception as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"store failed: {e!r}") from e
    return {"status": "stored"}
