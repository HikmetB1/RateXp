"""Pydantic schemas for the dashboard API. Self-contained per service."""

from __future__ import annotations

from config import SCHEMA_VERSION
from pydantic import BaseModel, Field


class Feedback(BaseModel):
    created_at: str | None = None  # ISO8601 UTC
    session_id: str | None = None
    skill_name: str
    agent: str
    score: int | None = Field(default=None, ge=1, le=2)  # 1 = good, 2 = bad
    comment: str | None = None
    request_id: str | None = None


class Transcript(BaseModel):
    """A stored full conversation, returned as ATIF JSON (see core/atif.py)."""

    created_at: str | None = None
    session_id: str | None = None
    skill_name: str
    agent: str
    schema_version: str = SCHEMA_VERSION
    atif: dict
    request_id: str | None = None


class QueryRequest(BaseModel):
    """A read-only SQL query from the dashboard's filter box. SELECT-only; the
    server validates and runs it in a read-only, timed, row-capped transaction."""

    sql: str  # a single SELECT (or WITH ... SELECT) statement
    limit: int | None = None  # optional row cap; clamped to query_max_rows
    full: bool = False  # true = full export (up to query_max_rows); else the view
