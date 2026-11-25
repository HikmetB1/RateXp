"""Pydantic schemas for the records core accepts and stores."""

from __future__ import annotations

from load_config import SCHEMA_VERSION
from pydantic import BaseModel, Field


class Feedback(BaseModel):
    """A single rating, exchanged over the wire and persisted to PostgreSQL."""

    created_at: str | None = None  # ISO8601 UTC; server fills if missing
    session_id: str | None = None  # server fills if missing
    skill_name: str | None = None  # absent when the rating is for a whole session
    agent: str  # required; identifies the calling agent runtime
    eval_name: str | None = None  # the eval (survey) answered, named as in evals/
    score: int | None = Field(default=None, ge=1, le=2)  # 1 = good, 2 = bad
    comment: str | None = None
    request_id: str | None = None  # idempotency key; dedup when present
    # Core's labels, {group: value} (see modules/labeling/); a client's own are overwritten.
    labels: dict[str, str] = {}


class Transcript(BaseModel):
    """A consented full conversation, stored as ATIF JSON (see build_trajectory.py)."""

    created_at: str | None = None  # ISO8601 UTC; server fills if missing
    session_id: str | None = None  # server fills if missing
    skill_name: str | None = None  # absent when the rating is for a whole session
    agent: str  # required; identifies the calling agent runtime
    eval_name: str | None = None  # the eval (survey) the rating answered, named as in evals/
    schema_version: str = SCHEMA_VERSION  # from config.yaml
    atif: dict  # ATIF trajectory; required
    request_id: str | None = None  # idempotency key; dedup when present
    # The rating's score and comment, which the hook sends along: core labels the
    # conversation with them and stores neither on the transcript (the rating holds them).
    score: int | None = Field(default=None, ge=1, le=2)
    comment: str | None = None
    # Core's labels, {group: value} (see modules/labeling/); a client's own are overwritten.
    labels: dict[str, str] = {}
