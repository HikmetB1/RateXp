"""Shared write path: fill defaults, size-limit, redact, then persist.

Pulled out of the old HTTP handlers so the storage logic has one home,
independent of how a record arrived. The MCP tools (see mcp_app.py) call here;
so do the unit tests. Behaviour is unchanged from the former POST handlers.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from atif import stub_if_oversized
from config import MAX_TRANSCRIPT_BYTES
from models import Feedback, Transcript
from redact import redact_atif
from store import get_store


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _fill_defaults(record: Feedback | Transcript) -> None:
    if not record.created_at:
        record.created_at = _now_iso()
    if not record.session_id:
        record.session_id = str(uuid.uuid4())
    if not record.request_id:
        record.request_id = str(uuid.uuid4())


def ingest_feedback(record: Feedback) -> None:
    """Fill defaults and persist a rating (the store dedups by request_id)."""
    _fill_defaults(record)
    get_store().append(record)


def ingest_transcript(record: Transcript) -> None:
    """Persist a trajectory: drop oversized ones to a meta-only stub, then mask PII.

    Oversized first: only a meta-only stub remains, so a few huge conversations
    can't bloat the DB or slow the dashboard. The stub carries no conversation
    text, so it skips the (costly, fail-closed) redaction call below.
    """
    _fill_defaults(record)
    record.atif = stub_if_oversized(record.atif, MAX_TRANSCRIPT_BYTES)
    if "oversized" not in record.atif:
        record.atif = redact_atif(record.atif)
    get_store().append_transcript(record)
