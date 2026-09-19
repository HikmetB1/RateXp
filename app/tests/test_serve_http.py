"""Read-only dashboard API: health, the list endpoints, and the top-skills stats."""

from __future__ import annotations

from datetime import UTC, datetime

from load_config import LIST_MAX_LIMIT, LIST_VIEW_LIMIT


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
    client, pool = app_with_fake_pool
    pool.set_select_rows([])
    client.get("/feedback")
    assert pool.store["params"] == (LIST_VIEW_LIMIT,)


def test_get_feedback_full_returns_max(app_with_fake_pool):
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
    client, pool = app_with_fake_pool
    pool.set_select_rows([])
    client.get("/transcript?full=true")
    assert pool.store["params"] == (LIST_MAX_LIMIT,)


def test_get_transcript_limit_too_high(app_with_fake_pool):
    client, _ = app_with_fake_pool
    assert client.get("/transcript?limit=1001").status_code == 422


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
