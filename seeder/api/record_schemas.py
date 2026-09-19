"""The two shapes a seeded run produces, and the one thing both submissions agree on.

``Rating`` doubles as the agent's ``response_format`` (see
modules/agent/run_skill_task.py), so its field descriptions are prompt text the
model actually reads - keep them instructive. ``SeededRun`` carries the identity
core needs to match a rating to its trajectory, so both posts must send the same one.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class SeededRun(BaseModel):
    """Who ran what, and under which ids - stamped on both posts to core."""

    skill_name: str
    agent: str
    session_id: str
    request_id: str


class Rating(BaseModel):
    """The agent's verdict on the skill it just used, as core's /feedback expects it."""

    score: int = Field(description="1 if the skill was good to use, 2 if it was bad.")
    comment: str = Field(
        description="One or two sentences saying exactly what was good or bad about the skill."
    )
