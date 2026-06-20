"""Full round-trip: feedback submitted via MCP shows up on the dashboard.

This is the one test that proves the whole app works together - core writes to
PostgreSQL (through its MCP tools), the dashboard reads the same database back
out.
"""

from __future__ import annotations

import time
import uuid


def _find(rows: list[dict], skill_name: str) -> dict | None:
    return next((r for r in rows if r.get("skill_name") == skill_name), None)


def test_feedback_round_trip(core_url, app_url, http, mcp_call):
    # A unique skill name so we can pick our row out of the dashboard list.
    skill = f"e2e-{uuid.uuid4().hex[:8]}"

    # 1. Core stores it via the submit_feedback MCP tool.
    ok, _ = mcp_call(
        "submit_feedback",
        {
            "session_id": str(uuid.uuid4()),
            "request_id": str(uuid.uuid4()),
            "skill_name": skill,
            "agent": "claude-code",
            "score": 2,
            "comment": "end-to-end ok",
        },
    )
    assert ok

    # 2. The dashboard reads it back (retry briefly to absorb write/read lag).
    row = None
    for _ in range(5):
        listed = http.get(f"{app_url}/feedback", params={"full": "true"})
        assert listed.status_code == 200
        row = _find(listed.json(), skill)
        if row:
            break
        time.sleep(0.5)

    assert row is not None, f"{skill} never appeared on the dashboard"
    assert row["score"] == 2
    assert row["comment"] == "end-to-end ok"


def test_top_skills_counts_our_feedback(core_url, app_url, http, mcp_call):
    skill = f"e2e-{uuid.uuid4().hex[:8]}"

    # One good (2) and one bad (1) rating for the same skill.
    for score in (2, 1):
        ok, _ = mcp_call(
            "submit_feedback",
            {
                "session_id": str(uuid.uuid4()),
                "request_id": str(uuid.uuid4()),
                "skill_name": skill,
                "agent": "claude-code",
                "score": score,
            },
        )
        assert ok

    entry = None
    for _ in range(5):
        r = http.get(f"{app_url}/stats/top-skills", params={"limit": 100})
        assert r.status_code == 200
        entry = next((s for s in r.json()["skills"] if s.get("skill_name") == skill), None)
        if entry:
            break
        time.sleep(0.5)

    assert entry is not None, f"{skill} missing from top-skills"
    assert entry["total"] >= 2  # both ratings counted


def test_trajectory_round_trip(core_url, app_url, http, mcp_call):
    """A feedback row and its stored transcript must stay linked on the dashboard.

    The dashboard's /snapshot is what the UI shows; it must return the feedback row
    together with the matching transcript (the "Trajectory"). This guards the bug
    where snapshot fetched the newest transcripts unrelated to the shown feedback.
    """
    session_id = str(uuid.uuid4())
    request_id = str(uuid.uuid4())
    skill = f"e2e-{uuid.uuid4().hex[:8]}"
    shared = {"session_id": session_id, "request_id": request_id, "skill_name": skill, "agent": "claude-code"}

    # Submit the rating, then its consented transcript - same ids, as a real run does.
    ok, _ = mcp_call("submit_feedback", {**shared, "score": 2})
    assert ok
    atif = {
        "agent": {"name": "claude-code", "model_name": "test"},
        "session_id": session_id,
        "steps": [{"source": "user", "message": "do the thing", "step_id": 1}],
    }
    ok, _ = mcp_call("submit_trajectory", {**shared, "atif": atif})
    assert ok

    # The dashboard snapshot must carry our feedback AND its transcript, linked by id.
    fb = tx = None
    for _ in range(5):
        snap = http.get(f"{app_url}/snapshot")
        assert snap.status_code == 200
        data = snap.json()
        fb = _find(data["feedback"], skill)
        tx = next((t for t in data["transcripts"] if t.get("request_id") == request_id), None)
        if fb and tx:
            break
        time.sleep(0.5)

    assert fb is not None, "feedback row missing from snapshot"
    assert tx is not None, "trajectory missing - feedback and transcript not linked in snapshot"
    assert tx["session_id"] == session_id
    assert tx["atif"]["steps"][0]["message"] == "do the thing"
