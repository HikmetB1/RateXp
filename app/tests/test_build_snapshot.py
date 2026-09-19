"""GET /snapshot and the feedback-to-transcript matching behind it."""

from __future__ import annotations

from datetime import UTC, datetime

from api.build_snapshot import transcripts_for
from load_config import LIST_MAX_LIMIT


def test_snapshot_returns_correlated_shape(app_with_fake_pool):
    client, pool = app_with_fake_pool
    pool.set_select_rows([])  # all snapshot queries empty
    r = client.get("/snapshot")
    assert r.status_code == 200
    assert r.json() == {"type": "snapshot", "feedback": [], "transcripts": [], "stats": []}


def test_transcripts_for_queries_by_feedback_ids(app_with_fake_pool):
    client, pool = app_with_fake_pool

    # A feedback row is (created_at, session_id, ..., request_id): match on both ids.
    feedback = [
        (datetime(2026, 5, 25, tzinfo=UTC), "sess-1", "demo", "claude-code", 2, "ok", "req-1")
    ]
    pool.set_select_rows(
        [
            (
                datetime(2026, 5, 25, tzinfo=UTC),
                "sess-1",
                "demo",
                "claude-code",
                "ATIF-v1.7",
                {"steps": []},
                "req-1",
            )
        ]
    )
    rows = transcripts_for(client.app.state.read, feedback)
    assert pool.store["params"] == (["req-1"], ["sess-1"], LIST_MAX_LIMIT)
    assert len(rows) == 1 and rows[0][6] == "req-1"


def test_transcripts_for_empty_feedback_skips_query(app_with_fake_pool):
    client, pool = app_with_fake_pool

    pool.store.pop("params", None)
    assert transcripts_for(client.app.state.read, []) == []
    assert "params" not in pool.store  # no query issued when there are no ids
