"""Read-only dashboard API: list, stats, query, and the live WebSocket."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest


def test_healthz(app_with_fake_pool):
    client, _ = app_with_fake_pool
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


# --- GET /feedback ------------------------------------------------------------


def test_get_feedback_returns_rows(app_with_fake_pool):
    client, pool = app_with_fake_pool
    pool.set_select_rows(
        [
            (
                datetime(2026, 5, 25, 12, 0, 0, tzinfo=UTC),
                "sess-1",
                "demo",
                "claude-code",
                2,
                "ok",
                "req-1",
            )
        ]
    )
    r = client.get("/feedback")
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 1
    assert rows[0]["skill_name"] == "demo"
    assert rows[0]["score"] == 2
    assert rows[0]["request_id"] == "req-1"


def test_get_feedback_default_uses_view_limit(app_with_fake_pool):
    from config import LIST_VIEW_LIMIT

    client, pool = app_with_fake_pool
    pool.set_select_rows([])
    client.get("/feedback")
    assert pool.store["params"] == (LIST_VIEW_LIMIT,)


def test_get_feedback_full_returns_max(app_with_fake_pool):
    from config import LIST_MAX_LIMIT

    client, pool = app_with_fake_pool
    pool.set_select_rows([])
    client.get("/feedback?full=true")
    assert pool.store["params"] == (LIST_MAX_LIMIT,)


def test_get_feedback_limit_too_low(app_with_fake_pool):
    client, _ = app_with_fake_pool
    assert client.get("/feedback?limit=0").status_code == 422


def test_get_feedback_limit_too_high(app_with_fake_pool):
    client, _ = app_with_fake_pool
    assert client.get("/feedback?limit=1001").status_code == 422


def test_get_feedback_db_error_returns_503(app_with_fake_pool):
    client, pool = app_with_fake_pool
    pool.raise_on_execute = RuntimeError("connection refused")
    r = client.get("/feedback")
    assert r.status_code == 503
    assert "db error" in r.json()["detail"]


# --- GET /transcript ----------------------------------------------------------


def test_get_transcript_returns_rows(app_with_fake_pool):
    client, pool = app_with_fake_pool
    pool.set_select_rows(
        [
            (
                datetime(2026, 5, 25, 12, 0, 0, tzinfo=UTC),
                "sess-1",
                "goodbye",
                "claude-code",
                "ATIF-v1.7",
                {"schema_version": "ATIF-v1.7", "steps": []},
                "req-1",
            )
        ]
    )
    r = client.get("/transcript")
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 1
    assert rows[0]["skill_name"] == "goodbye"
    assert rows[0]["atif"] == {"schema_version": "ATIF-v1.7", "steps": []}


def test_get_transcript_full_returns_max(app_with_fake_pool):
    from config import LIST_MAX_LIMIT

    client, pool = app_with_fake_pool
    pool.set_select_rows([])
    client.get("/transcript?full=true")
    assert pool.store["params"] == (LIST_MAX_LIMIT,)


def test_get_transcript_limit_too_high(app_with_fake_pool):
    client, _ = app_with_fake_pool
    assert client.get("/transcript?limit=1001").status_code == 422


# --- GET /snapshot ------------------------------------------------------------


def test_snapshot_returns_correlated_shape(app_with_fake_pool):
    client, pool = app_with_fake_pool
    pool.set_select_rows([])  # all snapshot queries empty
    r = client.get("/snapshot")
    assert r.status_code == 200
    assert r.json() == {"type": "snapshot", "feedback": [], "transcripts": [], "stats": []}


def test_select_transcripts_for_queries_by_feedback_ids(app_with_fake_pool):
    from config import LIST_MAX_LIMIT

    _, pool = app_with_fake_pool
    import server

    # A feedback row is (created_at, session_id, ..., request_id): match on both ids.
    feedback = [(datetime(2026, 5, 25, tzinfo=UTC), "sess-1", "demo", "claude-code", 2, "ok", "req-1")]
    pool.set_select_rows(
        [(datetime(2026, 5, 25, tzinfo=UTC), "sess-1", "demo", "claude-code", "ATIF-v1.7", {"steps": []}, "req-1")]
    )
    rows = server._select_transcripts_for(feedback)
    assert pool.store["params"] == (["req-1"], ["sess-1"], LIST_MAX_LIMIT)
    assert len(rows) == 1 and rows[0][6] == "req-1"


def test_select_transcripts_for_empty_feedback_skips_query(app_with_fake_pool):
    _, pool = app_with_fake_pool
    import server

    pool.store.pop("params", None)
    assert server._select_transcripts_for([]) == []
    assert "params" not in pool.store  # no query issued when there are no ids


# --- GET /stats/top-skills ----------------------------------------------------


def test_top_skills_returns_aggregated_rows(app_with_fake_pool):
    client, pool = app_with_fake_pool
    pool.set_select_rows([("goodbye", 5, 4, 1), ("cheerful", 3, 1, 2)])
    r = client.get("/stats/top-skills")
    assert r.status_code == 200
    assert r.json()["skills"] == [
        {"skill_name": "goodbye", "total": 5, "good": 4, "bad": 1},
        {"skill_name": "cheerful", "total": 3, "good": 1, "bad": 2},
    ]
    assert "GROUP BY skill_name" in pool.store["sql"]


def test_top_skills_empty(app_with_fake_pool):
    client, pool = app_with_fake_pool
    pool.set_select_rows([])
    r = client.get("/stats/top-skills")
    assert r.status_code == 200
    assert r.json() == {"skills": []}


def test_top_skills_limit_too_high(app_with_fake_pool):
    client, _ = app_with_fake_pool
    assert client.get("/stats/top-skills?limit=1001").status_code == 422


# --- POST /query --------------------------------------------------------------


def test_query_select_returns_columns_and_rows(app_with_fake_pool):
    client, pool = app_with_fake_pool
    pool.set_columns(["skill_name", "score"])
    pool.set_select_rows([("demo", 2), ("other", 1)])
    r = client.post("/query", json={"sql": "SELECT skill_name, score FROM feedback"})
    assert r.status_code == 200
    body = r.json()
    assert body["columns"] == ["skill_name", "score"]
    assert body["rows"] == [
        {"skill_name": "demo", "score": 2},
        {"skill_name": "other", "score": 1},
    ]
    assert body["row_count"] == 2
    assert body["truncated"] is False
    assert "AS _q LIMIT" in pool.store["sql"]


def test_query_rejects_non_select(app_with_fake_pool):
    client, _ = app_with_fake_pool
    assert client.post("/query", json={"sql": "DELETE FROM feedback"}).status_code == 400


def test_query_rejects_multiple_statements(app_with_fake_pool):
    client, _ = app_with_fake_pool
    assert client.post("/query", json={"sql": "SELECT 1; DROP TABLE feedback"}).status_code == 400


def test_query_rejects_write_keyword_in_cte(app_with_fake_pool):
    client, _ = app_with_fake_pool
    sql = "WITH x AS (DELETE FROM feedback RETURNING *) SELECT * FROM x"
    assert client.post("/query", json={"sql": sql}).status_code == 400


def test_query_rejects_empty(app_with_fake_pool):
    client, _ = app_with_fake_pool
    assert client.post("/query", json={"sql": "   "}).status_code == 400


def test_query_truncated_when_rows_hit_cap(app_with_fake_pool):
    client, pool = app_with_fake_pool
    pool.set_columns(["n"])
    pool.set_select_rows([(1,), (2,)])
    r = client.post("/query", json={"sql": "SELECT n FROM feedback", "limit": 2})
    assert r.status_code == 200
    assert r.json()["truncated"] is True


def test_query_default_caps_at_view_limit(app_with_fake_pool):
    from config import LIST_VIEW_LIMIT

    client, pool = app_with_fake_pool
    pool.set_columns(["n"])
    pool.set_select_rows([(1,)])
    client.post("/query", json={"sql": "SELECT n FROM feedback"})
    assert pool.store["params"] == (LIST_VIEW_LIMIT,)


def test_query_full_caps_at_max_rows(app_with_fake_pool):
    from config import QUERY_MAX_ROWS

    client, pool = app_with_fake_pool
    pool.set_columns(["n"])
    pool.set_select_rows([(1,)])
    client.post("/query", json={"sql": "SELECT n FROM feedback", "full": True})
    assert pool.store["params"] == (QUERY_MAX_ROWS,)


def test_query_disabled_returns_403(app_with_fake_pool, monkeypatch):
    client, _ = app_with_fake_pool
    import server

    monkeypatch.setattr(server, "QUERY_ENABLED", False)
    assert client.post("/query", json={"sql": "SELECT 1"}).status_code == 403


# --- WebSocket /ws ------------------------------------------------------------


def test_ws_sends_snapshot_on_connect(app_with_fake_pool):
    client, pool = app_with_fake_pool
    pool.set_select_rows([])  # all three snapshot queries return empty
    with client.websocket_connect("/ws") as ws:
        msg = ws.receive_json()
    assert msg["type"] == "snapshot"
    assert msg["feedback"] == []
    assert msg["transcripts"] == []
    assert msg["stats"] == []


def test_ws_disabled_closes(app_with_fake_pool, monkeypatch):
    client, _ = app_with_fake_pool
    import server

    monkeypatch.setattr(server, "WS_ENABLED", False)
    with pytest.raises(Exception):  # noqa: B017 - any disconnect/close is fine
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()
