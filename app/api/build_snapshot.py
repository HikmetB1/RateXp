"""The dashboard's whole view in one payload: feedback, their transcripts, and stats.

Transcripts are looked up by the shown feedback's request_id/session_id, not fetched as
"the newest N" - any rating stored without a transcript would otherwise push the two
lists out of step, and rows would show no trajectory though one exists.
"""

from __future__ import annotations

import json

from api.record_schemas import Feedback, Transcript
from api.trim_result_rows import jsonable
from load_config import LIST_VIEW_LIMIT, TOP_SKILLS_LIMIT
from modules.read.adapters.read_adapter_interface import ReadAdapter


def row_to_feedback(r) -> Feedback:
    return Feedback(
        created_at=jsonable(r[0]),
        session_id=r[1],
        skill_name=r[2],
        agent=r[3],
        score=r[4],
        comment=r[5],
        request_id=r[6],
    )


def row_to_transcript(r) -> Transcript:
    return Transcript(
        created_at=jsonable(r[0]),
        session_id=r[1],
        skill_name=r[2],
        agent=r[3],
        schema_version=r[4],
        atif=r[5] if isinstance(r[5], dict) else json.loads(r[5]),
        request_id=r[6],
    )


def transcripts_for(read: ReadAdapter, feedback_rows: list[tuple]) -> list[tuple]:
    """Transcript rows belonging to `feedback_rows`, matched by request_id / session_id."""
    request_ids = [r[6] for r in feedback_rows if r[6]]
    session_ids = [r[1] for r in feedback_rows if r[1]]
    return read.select_transcripts_by_ids(request_ids, session_ids)


def build_snapshot(read: ReadAdapter) -> dict:
    """The whole live view, in the same shapes the HTTP endpoints return."""
    feedback_rows = read.select_feedback(LIST_VIEW_LIMIT)
    transcript_rows = transcripts_for(read, feedback_rows)
    return {
        "type": "snapshot",
        "feedback": [row_to_feedback(r).model_dump() for r in feedback_rows],
        "transcripts": [row_to_transcript(r).model_dump() for r in transcript_rows],
        "stats": read.select_top_skills(TOP_SKILLS_LIMIT),
    }
