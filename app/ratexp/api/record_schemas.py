"""Pydantic schemas for the dashboard API."""

from __future__ import annotations

from load_config import SCHEMA_VERSION
from pydantic import BaseModel, Field


class Feedback(BaseModel):
    """A single stored rating, as the dashboard returns it."""

    created_at: str | None = None  # ISO8601 UTC
    session_id: str | None = None
    skill_name: str | None = None  # absent when the rating is for a whole session
    name: str | None = None  # the skill_name, or the session_id for a whole-session rating
    agent: str
    eval_name: str | None = None  # the eval (survey) the rating answered
    score: int | None = Field(default=None, ge=1, le=2)  # 1 = good, 2 = bad
    comment: str | None = None
    request_id: str | None = None


class Transcript(BaseModel):
    """A stored full conversation, returned as ATIF JSON (see core/api/build_trajectory.py)."""

    created_at: str | None = None
    session_id: str | None = None
    skill_name: str | None = None  # absent when the rating is for a whole session
    agent: str
    schema_version: str = SCHEMA_VERSION
    atif: dict
    request_id: str | None = None
    # The labels core gave the conversation (see core/modules/labeling/); None when unlabeled.
    business_case: str | None = None
    language: str | None = None
    task_type: str | None = None


class QueryRequest(BaseModel):
    """A read-only query from the dashboard's filter box, in the active read source's
    language (SQL for PostgreSQL, DQL for Dynatrace). The read adapter validates it and
    runs it read-only, timed and row-capped."""

    query: str  # a read-only query in the source's language
    limit: int | None = None  # optional row cap; clamped to query_max_rows
    full: bool = False  # true = full export (up to query_max_rows); else the view


class PanelFilters(BaseModel):
    """What the Dashboard view's filter row picked. None means all; ``since`` is ISO 8601
    (PostgreSQL casts it)."""

    type: str | None = None  # "skill" or "session": a session rating is one with no skill
    skill: str | None = None
    agent: str | None = None
    eval: str | None = None
    business_case: str | None = None  # the three labels core gives a stored conversation
    language: str | None = None
    task_type: str | None = None
    since: str | None = None

    def params(self) -> dict:
        # "" (an empty query-string value) binds as NULL too, which the fragment reads as "all".
        return {key: value or None for key, value in self.model_dump().items()}


class PanelRequest(BaseModel):
    """One Dashboard panel to run, by its id, with the filters to apply."""

    panel: str
    filters: PanelFilters = PanelFilters()
