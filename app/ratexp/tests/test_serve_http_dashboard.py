"""The Dashboard view's endpoints: GET /dashboard, POST /dashboard/panel, GET /dashboard/export.

The dashboard files are small fixtures written per test, shaped exactly like
core/modules/dashboard/dashboard_for_app.yaml, so the tests hold whatever the real files say.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
import yaml
from load_config import LIST_MAX_LIMIT
from modules.read import clone_dashboard_from_base

FILTERS_SQL = (
    "(%(type)s::text IS NULL OR "
    "CASE WHEN skill_name IS NULL THEN 'session' ELSE 'skill' END = %(type)s) AND "
    "(%(skill)s::text IS NULL OR COALESCE(skill_name, '(none)') = %(skill)s) AND "
    "(%(agent)s::text IS NULL OR split_part(agent, ' ', 1) = %(agent)s) AND "
    "(%(eval)s::text IS NULL OR COALESCE(eval_name, '(none)') = %(eval)s) AND "
    "(%(since)s::timestamptz IS NULL OR created_at >= %(since)s)"
)
BASE = {
    "panels": {
        "good_bad_over_time": {"title": "Good vs bad per day", "kind": "line"},
        "feedback": {"title": "Feedback", "kind": "table"},
    }
}
# The skill, agent and eval dropdowns, narrowed to the picked type's values.
TYPE_WHERE = (
    "WHERE %(type)s::text IS NULL "
    "OR CASE WHEN skill_name IS NULL THEN 'session' ELSE 'skill' END = %(type)s"
)
APP = {
    "name": "RateXp",
    "filters": {
        "sql": FILTERS_SQL,
        "values": {
            "type": "SELECT type FROM (VALUES ('skill'), ('session')) AS types (type)",
            "skill": f"SELECT DISTINCT COALESCE(skill_name, '(none)') FROM feedback {TYPE_WHERE}",
            "agent": f"SELECT DISTINCT split_part(agent, ' ', 1) FROM feedback {TYPE_WHERE}",
            "eval": f"SELECT DISTINCT COALESCE(eval_name, '(none)') FROM feedback {TYPE_WHERE}",
        },
    },
    "download": {
        "sql": (
            "SELECT created_at, session_id, skill_name, agent, eval_name, score, comment, request_id, "
            "business_case, language, task_type "
            "FROM feedback_with_labels WHERE {filters} ORDER BY created_at DESC LIMIT %(limit)s"
        )
    },
    "panels": {
        "total_ratings": {
            "title": "Total ratings",
            "kind": "number",
            "sql": "SELECT count(*) AS value FROM feedback WHERE {filters}",
        },
        "good_bad_over_time": {
            "sql": (
                "SELECT date_trunc('day', created_at) AS day, count(*) FILTER (WHERE score = 1) AS good, "
                "count(*) FILTER (WHERE score = 2) AS bad FROM feedback WHERE {filters} "
                "GROUP BY day ORDER BY day"
            )
        },
        "feedback": {
            "sql": (
                "SELECT created_at, session_id, skill_name, agent, score, atif FROM (SELECT "
                "f.created_at, f.session_id, f.skill_name, f.agent, f.eval_name, f.score, t.atif "
                "FROM feedback f LEFT JOIN transcript t ON t.request_id = f.request_id) s "
                "WHERE {filters} ORDER BY created_at DESC LIMIT 10"
            )
        },
    },
}
ALL = {
    "type": None,
    "skill": None,
    "agent": None,
    "eval": None,
    "business_case": None,
    "language": None,
    "task_type": None,
    "since": None,
}


@pytest.fixture
def dashboard_files(tmp_path, monkeypatch):
    (tmp_path / "dashboard_base.yaml").write_text(yaml.safe_dump(BASE, sort_keys=False))
    (tmp_path / "dashboard_for_app.yaml").write_text(yaml.safe_dump(APP, sort_keys=False))
    monkeypatch.setattr(clone_dashboard_from_base, "DASHBOARD_DIR", tmp_path)


# --- GET /dashboard -----------------------------------------------------------


def test_dashboard_lists_the_dropdown_values_and_the_panels(app_with_fake_pool, dashboard_files):
    client, pool = app_with_fake_pool
    pool.set_select_rows([("demo",), ("other",)])  # answers each of the four values queries
    body = client.get("/dashboard").json()
    assert body["available"] is True
    assert body["filters"] == {
        "type": ["demo", "other"],
        "skill": ["demo", "other"],
        "agent": ["demo", "other"],
        "eval": ["demo", "other"],
    }
    assert body["panels"] == [
        {"id": "total_ratings", "title": "Total ratings", "kind": "number"},
        {"id": "good_bad_over_time", "title": "Good vs bad per day", "kind": "line"},
        {"id": "feedback", "title": "Feedback", "kind": "table"},
    ]
    assert body["download_limit"] == LIST_MAX_LIMIT  # what the Download button promises
    assert pool.store["params"] == {"type": None}  # no type picked: every value


def test_a_picked_type_narrows_the_dropdown_values(
    app_with_fake_pool, dashboard_files, monkeypatch
):
    client, _ = app_with_fake_pool
    seen = []

    def run_dashboard_sql(sql, params, timeout_ms):
        seen.append((sql, params))
        return ["value"], [("session",)] if "VALUES" in sql else [("cursor",)]

    monkeypatch.setattr(client.app.state.read, "run_dashboard_sql", run_dashboard_sql)
    body = client.get("/dashboard", params={"type": "session"}).json()
    assert body["filters"] == {
        "type": ["session"],
        "skill": ["cursor"],
        "agent": ["cursor"],
        "eval": ["cursor"],
    }
    assert [params for _, params in seen] == [{"type": "session"}] * 4
    # "" is what an "All" pick sends: every value.
    seen.clear()
    client.get("/dashboard", params={"type": ""})
    assert [params for _, params in seen] == [{"type": None}] * 4


def test_dashboard_is_unavailable_off_postgresql(app_with_fake_pool, dashboard_files, monkeypatch):
    client, _ = app_with_fake_pool
    monkeypatch.setattr(client.app.state.read, "query_language", "DQL")
    body = client.get("/dashboard").json()
    assert body["available"] is False
    assert body["reason"] == (
        "the Dashboard view reads from PostgreSQL only; this app reads from app_be_psql"
    )
    assert client.post("/dashboard/panel", json={"panel": "total_ratings"}).status_code == 409
    assert client.get("/dashboard/export").status_code == 409


def test_dashboard_db_error_returns_503(app_with_fake_pool, dashboard_files):
    client, pool = app_with_fake_pool
    pool.raise_on_execute = RuntimeError("connection refused")
    r = client.get("/dashboard")
    assert r.status_code == 503
    assert "db error" in r.json()["detail"]


# --- POST /dashboard/panel ----------------------------------------------------


def test_panel_runs_its_sql_with_the_filters_bound(app_with_fake_pool, dashboard_files):
    client, pool = app_with_fake_pool
    pool.set_columns(["value"])
    pool.set_select_rows([(3,)])
    r = client.post(
        "/dashboard/panel",
        json={
            "panel": "total_ratings",
            "filters": {"type": "skill", "skill": "demo", "agent": None, "eval": None},
        },
    )
    assert r.status_code == 200
    assert r.json() == {"columns": ["value"], "rows": [[3]]}
    assert pool.store["sql"] == f"SELECT count(*) AS value FROM feedback WHERE {FILTERS_SQL}"
    assert pool.store["params"] == {**ALL, "type": "skill", "skill": "demo"}


def test_panel_binds_every_name_and_passes_since_through(app_with_fake_pool, dashboard_files):
    client, pool = app_with_fake_pool
    pool.set_select_rows([])
    client.post(
        "/dashboard/panel",
        json={"panel": "good_bad_over_time", "filters": {"since": "2026-09-03T10:00:00.000Z"}},
    )
    # Every name the fragment binds is present (psycopg would otherwise raise); "" is "all".
    assert pool.store["params"] == {**ALL, "since": "2026-09-03T10:00:00.000Z"}
    client.post("/dashboard/panel", json={"panel": "good_bad_over_time", "filters": {"skill": ""}})
    assert pool.store["params"] == ALL


def test_none_is_bound_as_a_value_to_match_not_as_all(app_with_fake_pool, dashboard_files):
    # The dropdowns list "(none)" for whole-session ratings, ratings without an eval and
    # ratings without a labeled conversation; the fragment matches it against the null, so
    # it must reach the SQL as itself.
    client, pool = app_with_fake_pool
    pool.set_select_rows([])
    none = {"skill": "(none)", "eval": "(none)", "language": "(none)"}
    client.post("/dashboard/panel", json={"panel": "total_ratings", "filters": none})
    assert pool.store["params"] == {**ALL, **none}
    assert client.get("/dashboard/export", params=none).status_code == 200
    assert pool.store["params"] == {**ALL, **none, "limit": LIST_MAX_LIMIT}


def test_panel_cells_are_json_ready(app_with_fake_pool, dashboard_files):
    client, pool = app_with_fake_pool
    pool.set_columns(["day", "good", "bad", "percent_good"])
    pool.set_select_rows([(datetime(2026, 9, 3, tzinfo=UTC), 2, 1, Decimal("66.7"))])
    body = client.post("/dashboard/panel", json={"panel": "good_bad_over_time"}).json()
    assert body["rows"] == [["2026-09-03T00:00:00Z", 2, 1, 66.7]]


def test_the_feedback_panel_carries_each_ratings_conversation(app_with_fake_pool, dashboard_files):
    # The Feedback table opens a rating's trajectory from the row itself.
    client, pool = app_with_fake_pool
    pool.set_columns(["created_at", "session_id", "skill_name", "agent", "score", "atif"])
    atif = {"steps": [{"source": "user", "message": "hi"}]}
    pool.set_select_rows([(datetime(2026, 9, 3, 10, tzinfo=UTC), "s1", None, "cursor", 1, atif)])
    r = client.post("/dashboard/panel", json={"panel": "feedback", "filters": {"type": "session"}})
    assert r.json()["rows"] == [["2026-09-03T10:00:00Z", "s1", None, "cursor", 1, atif]]
    assert pool.store["params"] == {**ALL, "type": "session"}


def test_panel_unknown_id_is_404(app_with_fake_pool, dashboard_files):
    client, _ = app_with_fake_pool
    assert client.post("/dashboard/panel", json={"panel": "nope"}).status_code == 404


def test_panel_db_error_returns_503(app_with_fake_pool, dashboard_files):
    client, pool = app_with_fake_pool
    pool.raise_on_execute = RuntimeError("connection refused")
    r = client.post("/dashboard/panel", json={"panel": "total_ratings"})
    assert r.status_code == 503
    assert "db error" in r.json()["detail"]


# --- GET /dashboard/export ----------------------------------------------------

_DOWNLOAD_COLUMNS = [
    "created_at",
    "session_id",
    "skill_name",
    "agent",
    "eval_name",
    "score",
    "comment",
    "request_id",
    "business_case",
    "language",
    "task_type",
]


def _rating(session_id, skill_name, request_id, day=3, labels=(None, None, None)) -> tuple:
    return (
        datetime(2026, 9, day, 10, tzinfo=UTC),
        session_id,
        skill_name,
        "claude-code",
        "human-satisfaction",
        1,
        None,
        request_id,
        *labels,
    )


def _transcript(session_id, skill_name, request_id, atif, created_at="2026-09-03T10:00:00Z"):
    labels = (None, None, None)
    return (
        created_at,
        session_id,
        skill_name,
        "claude-code",
        "ATIF-v1.7",
        atif,
        request_id,
        *labels,
    )


def _stored_transcripts(client, monkeypatch, transcripts: list[tuple]) -> list:
    """Answer transcript lookups like the PostgreSQL adapter does: request id matches, newest
    first, capped at LIST_MAX_LIMIT. Returns the list each lookup's ids are appended to."""
    lookups = []

    def select_transcripts_by_request_ids(request_ids):
        lookups.append(request_ids)
        hits = [t for t in transcripts if t[6] in request_ids]
        return sorted(hits, key=lambda t: t[0], reverse=True)[:LIST_MAX_LIMIT]

    monkeypatch.setattr(
        client.app.state.read,
        "select_transcripts_by_request_ids",
        select_transcripts_by_request_ids,
    )
    return lookups


def test_export_pairs_each_rating_with_its_conversation(
    app_with_fake_pool, dashboard_files, monkeypatch
):
    client, pool = app_with_fake_pool
    pool.set_columns(_DOWNLOAD_COLUMNS)
    pool.set_select_rows(
        [
            _rating("s1", "demo", "r1", day=3, labels=("backend", "go", "fix")),
            _rating("s2", None, "r2", day=2),  # its own transcript was never stored
            _rating("s3", "demo", None, day=1),
        ]
    )
    lookups = _stored_transcripts(
        client,
        monkeypatch,
        [
            _transcript("s1", "demo", "r1", {"steps": ["one"]}),
            _transcript("s2", None, "r9", {"steps": ["another run"]}),
        ],
    )

    r = client.get("/dashboard/export?type=skill&skill=demo&agent=&eval=&since=")
    assert r.status_code == 200
    assert lookups == [["r1", "r2"]]
    assert pool.store["params"] == {
        **ALL,
        "type": "skill",
        "skill": "demo",
        "limit": LIST_MAX_LIMIT,
    }
    assert "{filters}" not in pool.store["sql"] and "LIMIT %(limit)s" in pool.store["sql"]
    rows = r.json()
    assert [row["name"] for row in rows] == ["demo", "s2", "demo"]
    assert rows[0] == {
        "created_at": "2026-09-03T10:00:00Z",
        "session_id": "s1",
        "skill_name": "demo",
        "name": "demo",
        "agent": "claude-code",
        "eval_name": "human-satisfaction",
        "score": 1,
        "comment": None,
        "request_id": "r1",
        "business_case": "backend",
        "language": "go",
        "task_type": "fix",
        "conversation": {"steps": ["one"]},
    }
    assert rows[1]["conversation"] is None
    assert rows[1]["language"] is None
    assert rows[2]["conversation"] is None


def test_export_never_attaches_another_ratings_conversation_from_the_same_session(
    app_with_fake_pool, dashboard_files, monkeypatch
):
    client, pool = app_with_fake_pool
    pool.set_columns(_DOWNLOAD_COLUMNS)
    pool.set_select_rows(
        [
            _rating("s1", "demo", "r-declined"),  # the user declined to store this one
            _rating("s1", "demo", "r-stored"),
            _rating("s1", None, "r-session"),  # no transcript of its own
        ]
    )
    _stored_transcripts(
        client,
        monkeypatch,
        [
            _transcript("s1", "demo", "r-stored", {"steps": ["stored"]}),
            _transcript("s1", None, "r-other-session", {"steps": ["other session"]}),
        ],
    )
    rows = client.get("/dashboard/export").json()
    assert [row["conversation"] for row in rows] == [None, {"steps": ["stored"]}, None]


def test_export_keeps_exact_matches_however_many_transcripts_their_session_holds(
    app_with_fake_pool, dashboard_files, monkeypatch
):
    client, pool = app_with_fake_pool
    pool.set_columns(_DOWNLOAD_COLUMNS)
    pool.set_select_rows(
        [
            _rating("busy", "demo", "r-missing", day=3),
            _rating("busy", "demo", "r-old", day=1),
        ]
    )
    newer_runs = [
        _transcript(
            "busy", "demo", f"r-{i}", {"steps": [i]}, f"2026-09-02T{i // 60:02d}:{i % 60:02d}:00Z"
        )
        for i in range(LIST_MAX_LIMIT)
    ]
    lookups = _stored_transcripts(
        client,
        monkeypatch,
        [_transcript("busy", "demo", "r-old", {"steps": ["own"]}, "2026-09-01T10:00:00Z")]
        + newer_runs,
    )
    rows = client.get("/dashboard/export").json()
    # Only the ratings' own request ids are asked for, so LIST_MAX_LIMIT newer runs of the
    # same session cannot fill the capped lookup ahead of the older rating's own transcript.
    assert lookups == [["r-missing", "r-old"]]
    assert [row["conversation"] for row in rows] == [None, {"steps": ["own"]}]


def test_export_db_error_returns_503(app_with_fake_pool, dashboard_files):
    client, pool = app_with_fake_pool
    pool.raise_on_execute = RuntimeError("connection refused")
    assert client.get("/dashboard/export").status_code == 503
