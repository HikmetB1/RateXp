"""Pydantic schemas for the records core accepts and stores."""

from __future__ import annotations

from config import SCHEMA_VERSION
from pydantic import BaseModel, Field


class Feedback(BaseModel):
    """A single rating, exchanged over the wire and persisted to PostgreSQL."""

    created_at: str | None = None  # ISO8601 UTC; server fills if missing
    session_id: str | None = None  # server fills if missing
    skill_name: str
    agent: str  # required; identifies the calling agent runtime
    score: int | None = Field(default=None, ge=1, le=2)  # 1 = good, 2 = bad
    comment: str | None = None
    request_id: str | None = None  # idempotency key; dedup when present


class Transcript(BaseModel):
    """A consented full conversation, stored as ATIF JSON (see atif.py)."""

    created_at: str | None = None  # ISO8601 UTC; server fills if missing
    session_id: str | None = None  # server fills if missing
    skill_name: str
    agent: str  # required; identifies the calling agent runtime
    schema_version: str = SCHEMA_VERSION  # from config.yaml
    atif: dict  # ATIF trajectory; required
    request_id: str | None = None  # idempotency key; dedup when present
