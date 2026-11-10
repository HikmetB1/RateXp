"""Read-only dashboard API: health, meta and the list endpoints."""

from __future__ import annotations

from datetime import UTC, datetime

from load_config import CORE_URL, LIST_MAX_LIMIT, LIST_VIEW_LIMIT


def test_healthz(app_with_fake_pool):
    client, _ = app_with_fake_pool
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_meta_names_the_core_the_install_popup_points_at(app_with_fake_pool):
    client, _ = app_with_fake_pool
    assert client.get("/meta").json()["core_url"] == CORE_URL


def test_meta_gives_the_download_popup_the_configured_row_limits(app_with_fake_pool):
    client, _ = app_with_fake_pool
    meta = client.get("/meta").json()
    assert (meta["list_view_limit"], meta["list_max_limit"]) == (LIST_VIEW_LIMIT, LIST_MAX_LIMIT)


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
                "human-satisfaction",
            )
        ]
    )
    r = client.get("/feedback")
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 1
    assert rows[0]["skill_name"] == "demo"
    assert rows[0]["name"] == "demo"
    assert rows[0]["eval_name"] == "human-satisfaction"  # the dashboard's Eval column
    assert rows[0]["score"] == 2
    assert rows[0]["request_id"] == "req-1"


def test_get_feedback_names_a_session_rating_by_its_session(app_with_fake_pool):
    client, pool = app_with_fake_pool
    pool.set_select_rows(
        [
            (
                datetime(2026, 5, 25, 12, 0, 0, tzinfo=UTC),
                "sess-1",
                None,
                "claude-code",
                1,
                None,
                None,
                None,
            )
        ]
    )
    rows = client.get("/feedback").json()
    assert rows[0]["skill_name"] is None
    assert rows[0]["name"] == "sess-1"
    assert rows[0]["eval_name"] is None, "a rating that named no eval shows none"


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
                "backend",
                "python",
                "feat",
            )
        ]
    )
    r = client.get("/transcript")
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 1
    assert rows[0]["skill_name"] == "goodbye"
    assert rows[0]["atif"] == {"schema_version": "ATIF-v1.7", "steps": []}
    labels = (rows[0]["business_case"], rows[0]["language"], rows[0]["task_type"])
    assert labels == ("backend", "python", "feat")


def test_get_transcript_full_returns_max(app_with_fake_pool):
    client, pool = app_with_fake_pool
    pool.set_select_rows([])
    client.get("/transcript?full=true")
    assert pool.store["params"] == (LIST_MAX_LIMIT,)


def test_get_transcript_limit_too_high(app_with_fake_pool):
    client, _ = app_with_fake_pool
    assert client.get("/transcript?limit=1001").status_code == 422
