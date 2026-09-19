"""POST /query: the dashboard's filter box, its row caps, and the Download rule."""

from __future__ import annotations

from load_config import LIST_VIEW_LIMIT, QUERY_MAX_ROWS


def test_query_select_returns_columns_and_rows(app_with_fake_pool):
    client, pool = app_with_fake_pool
    pool.set_columns(["skill_name", "score"])
    pool.set_select_rows([("demo", 2), ("other", 1)])
    r = client.post("/query", json={"query": "SELECT skill_name, score FROM feedback"})
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
    assert client.post("/query", json={"query": "DELETE FROM feedback"}).status_code == 400


def test_query_rejects_multiple_statements(app_with_fake_pool):
    client, _ = app_with_fake_pool
    assert client.post("/query", json={"query": "SELECT 1; DROP TABLE feedback"}).status_code == 400


def test_query_rejects_write_keyword_in_cte(app_with_fake_pool):
    client, _ = app_with_fake_pool
    sql = "WITH x AS (DELETE FROM feedback RETURNING *) SELECT * FROM x"
    assert client.post("/query", json={"query": sql}).status_code == 400


def test_query_rejects_empty(app_with_fake_pool):
    client, _ = app_with_fake_pool
    assert client.post("/query", json={"query": "   "}).status_code == 400


def test_query_truncated_when_more_rows_than_shown(app_with_fake_pool):
    client, pool = app_with_fake_pool
    pool.set_columns(["n"])
    pool.set_select_rows([(1,), (2,), (3,)])
    r = client.post("/query", json={"query": "SELECT n FROM feedback", "limit": 2})
    assert r.status_code == 200
    body = r.json()
    assert body["row_count"] == 2
    assert body["truncated"] is True  # 3 matched, only 2 shown


def test_query_default_caps_at_view_limit(app_with_fake_pool):
    client, pool = app_with_fake_pool
    pool.set_columns(["created_at"])
    pool.set_select_rows([(f"2026-06-{i:02d}T00:00:00Z",) for i in range(1, LIST_VIEW_LIMIT + 5)])
    body = client.post("/query", json={"query": "SELECT created_at FROM feedback"}).json()
    assert body["row_count"] == LIST_VIEW_LIMIT  # trimmed to the view
    assert body["truncated"] is True


def test_query_filter_returns_most_recent_first(app_with_fake_pool):
    """A filter shows the newest view-limit rows, newest on top - regardless of SQL order."""
    client, pool = app_with_fake_pool
    pool.set_columns(["skill_name", "created_at"])
    # Days 01..12 handed back oldest-first; the view should flip to newest-first and trim.
    pool.set_select_rows([("demo", f"2026-06-{i:02d}T00:00:00Z") for i in range(1, 13)])
    body = client.post("/query", json={"query": "SELECT * FROM feedback"}).json()
    assert body["row_count"] == LIST_VIEW_LIMIT
    assert body["rows"][0]["created_at"] == "2026-06-12T00:00:00Z"  # newest on top
    assert body["rows"][-1]["created_at"] == "2026-06-03T00:00:00Z"


def test_query_returns_rows_own_transcripts(app_with_fake_pool, monkeypatch):
    """A filter carries its rows' transcripts, looked up by their request_id/session_id."""
    client, pool = app_with_fake_pool
    pool.set_columns(["skill_name", "created_at", "request_id", "session_id"])
    pool.set_select_rows([("handoff", "2026-06-10T00:00:00Z", "req1", "sess1")])
    captured = {}

    def fake_transcripts(req_ids, sess_ids):
        captured["req"], captured["sess"] = req_ids, sess_ids
        return [
            (
                "2026-06-10T00:00:00Z",
                "sess1",
                "handoff",
                "claude",
                "ATIF-v1.7",
                {"steps": []},
                "req1",
            )
        ]

    monkeypatch.setattr(client.app.state.read, "select_transcripts_by_ids", fake_transcripts)
    body = client.post(
        "/query",
        json={"query": "SELECT skill_name, created_at, request_id, session_id FROM feedback"},
    ).json()
    assert captured == {"req": ["req1"], "sess": ["sess1"]}  # ids taken from the shown rows
    assert len(body["transcripts"]) == 1
    assert body["transcripts"][0]["request_id"] == "req1"


def test_query_full_skips_transcripts(app_with_fake_pool, monkeypatch):
    """Download (full=true) fetches transcripts separately, so /query doesn't bundle them."""
    client, pool = app_with_fake_pool
    pool.set_columns(["skill_name", "created_at", "request_id"])
    pool.set_select_rows([("handoff", "2026-06-10T00:00:00Z", "req1")])

    def boom(*_):
        raise AssertionError("transcripts must not be fetched for a full export")

    monkeypatch.setattr(client.app.state.read, "select_transcripts_by_ids", boom)
    body = client.post("/query", json={"query": "SELECT * FROM feedback", "full": True}).json()
    assert body["transcripts"] == []


def test_query_full_caps_at_max_rows(app_with_fake_pool):
    client, pool = app_with_fake_pool
    pool.set_columns(["n"])
    pool.set_select_rows([(1,)])
    client.post("/query", json={"query": "SELECT n FROM feedback", "full": True})
    assert pool.store["params"] == (QUERY_MAX_ROWS,)


def test_query_full_single_skill_exports_all(app_with_fake_pool):
    """Download of a query that resolves to ONE skill returns every row, uncapped by the view."""
    client, pool = app_with_fake_pool
    pool.set_columns(["skill_name", "created_at"])
    rows = [("demo", f"2026-06-{i:02d}T00:00:00Z") for i in range(1, LIST_VIEW_LIMIT + 5)]
    pool.set_select_rows(rows)
    r = client.post(
        "/query", json={"query": "SELECT skill_name, created_at FROM feedback", "full": True}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["row_count"] == len(rows)  # all of the one skill, past the view limit
    assert body["truncated"] is False


def test_query_full_multiple_skills_trims_to_recent(app_with_fake_pool):
    """Download of a multi-skill query keeps only the view-limit most-recent rows."""
    client, pool = app_with_fake_pool
    pool.set_columns(["skill_name", "created_at"])
    # Two skills, days 01..12 in arbitrary order; expect the newest LIST_VIEW_LIMIT back.
    rows = [(("a" if i % 2 else "b"), f"2026-06-{i:02d}T00:00:00Z") for i in range(1, 13)]
    pool.set_select_rows(rows)
    r = client.post(
        "/query", json={"query": "SELECT skill_name, created_at FROM feedback", "full": True}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["row_count"] == LIST_VIEW_LIMIT
    assert body["truncated"] is True  # more rows existed than were returned
    assert body["rows"][0]["created_at"] == "2026-06-12T00:00:00Z"  # newest first
    assert body["rows"][-1]["created_at"] == "2026-06-03T00:00:00Z"


def test_query_full_without_skill_column_trims_to_recent(app_with_fake_pool):
    """A full query whose shape has no skill_name is treated as multi-skill and trimmed."""
    client, pool = app_with_fake_pool
    pool.set_columns(["n"])
    pool.set_select_rows([(i,) for i in range(LIST_VIEW_LIMIT + 3)])
    r = client.post("/query", json={"query": "SELECT n FROM feedback", "full": True})
    assert r.status_code == 200
    body = r.json()
    assert body["row_count"] == LIST_VIEW_LIMIT
    assert body["truncated"] is True


def test_query_filter_does_not_apply_download_rule(app_with_fake_pool):
    """Running a filter (full omitted) returns the multi-skill rows as-is - rule is Download-only."""
    client, pool = app_with_fake_pool
    pool.set_columns(["skill_name"])
    pool.set_select_rows([("a",), ("b",)])
    r = client.post("/query", json={"query": "SELECT skill_name FROM feedback", "limit": 50})
    assert r.status_code == 200
    assert r.json()["row_count"] == 2  # both skills kept; no trimming


def test_query_disabled_returns_403(app_with_fake_pool, monkeypatch):
    client, _ = app_with_fake_pool
    from api import serve_http

    monkeypatch.setattr(serve_http, "QUERY_ENABLED", False)
    assert client.post("/query", json={"query": "SELECT 1"}).status_code == 403
