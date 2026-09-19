"""Shared write path: fill defaults, size-limit, redact, then persist.

One home for the storage logic, independent of how a record arrived. The POST
handlers in api/serve_http.py call here; so do the unit tests.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from api.build_trajectory import stub_if_oversized
from api.record_schemas import Feedback, Transcript
from load_config import MAX_TRANSCRIPT_BYTES
from modules.redaction.redact_trajectory import redact_atif
from modules.write.dispatch_to_adapters import write_feedback, write_transcript


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
    """Fill defaults and fan the rating out to every enabled destination.

    Each destination is independent (see modules/write/dispatch_to_adapters.py): a failing one is logged and
    never blocks the others, but a WriteError is raised if none accepted the rating.
    """
    _fill_defaults(record)
    write_feedback(record)


def ingest_transcript(record: Transcript) -> None:
    """Persist a trajectory: drop oversized ones to a meta-only stub, then mask PII.

    Oversized first: only a meta-only stub remains, so a few huge conversations
    can't bloat the DB or slow the dashboard. The stub carries no conversation
    text, so it skips the (costly, fail-closed) redaction call below. Raises
    WriteError if no destination accepted the trajectory (see modules/write/dispatch_to_adapters.py).
    """
    _fill_defaults(record)
    record.atif = stub_if_oversized(record.atif, MAX_TRANSCRIPT_BYTES)
    if "oversized" not in record.atif:
        record.atif = redact_atif(record.atif)
    write_transcript(record)
