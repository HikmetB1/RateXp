"""Pydantic schemas for the dashboard API."""

from __future__ import annotations

from load_config import SCHEMA_VERSION
from modules.read.clone_dashboard_from_base import read_label_groups
from pydantic import BaseModel, Field, create_model


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
    # The labels core gave the rating, {group: value} (see core/modules/labeling/); its
    # conversation's, when stored, win over them group by group.
    labels: dict[str, str] = {}


class Transcript(BaseModel):
    """A stored full conversation, returned as ATIF JSON (see core/api/build_trajectory.py)."""

    created_at: str | None = None
    session_id: str | None = None
    skill_name: str | None = None  # absent when the rating is for a whole session
    agent: str
    schema_version: str = SCHEMA_VERSION
    atif: dict
    request_id: str | None = None
    # The labels core gave the conversation, {group: value} (see core/modules/labeling/).
    labels: dict[str, str] = {}


class QueryRequest(BaseModel):
    """A read-only query from the dashboard's filter box, in the active read source's
    language (SQL for PostgreSQL, DQL for Dynatrace). The read adapter validates it and
    runs it read-only, timed and row-capped."""

    query: str  # a read-only query in the source's language
    limit: int | None = None  # optional row cap; clamped to query_max_rows
    full: bool = False  # true = Download trajectories (up to list_max_limit); else the view


class _FixedPanelFilters(BaseModel):
    type: str | None = None  # "skill" or "session": a session rating is one with no skill
    skill: str | None = None
    agent: str | None = None
    eval: str | None = None
    since: str | None = None

    def params(self) -> dict:
        # "" (an empty query-string value) binds as NULL too, which the fragment reads as "all".
        return {key: value or None for key, value in self.model_dump().items()}


# An admin names the label groups in core/config.yaml, so their filters are fields made
# from that file: the image copies it in (see app/ratexp/Dockerfile).
PanelFilters = create_model(
    "PanelFilters",
    __base__=_FixedPanelFilters,
    __doc__="""What the Dashboard view's filter row picked: type, skill, agent, eval, one
    filter per label group, named as the group, and since. None means all; ``since`` is ISO
    8601 (PostgreSQL casts it).""",
    **{group: (str | None, None) for group in read_label_groups()},
)


class PanelRequest(BaseModel):
    """One Dashboard panel to run, by its id, with the filters to apply."""

    panel: str
    filters: PanelFilters = PanelFilters()
