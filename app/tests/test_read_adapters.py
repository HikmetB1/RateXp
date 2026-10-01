"""Read adapters: record mapping, filter-box handling, source selection (no network).

Each source's client (`_dql` for Dynatrace, `_spans` for Phoenix) is stubbed with
canned records, so the mapping to the row shapes `api/` expects is asserted
without any HTTP.
"""

from __future__ import annotations

import pytest
from modules.read.adapters.read_from_dynatrace import DynatraceReadAdapter
from modules.read.adapters.read_from_phoenix import PhoenixReadAdapter
from modules.read.adapters.read_from_postgres import _validate_select
from modules.read.open_read_source import open_read_source


def _adapter(records):
    a = DynatraceReadAdapter("app_be_dynatrace", "https://tenant.example", "tok")
    a._dql = lambda query: records  # stub the DQL client
    return a


def test_select_feedback_maps_records():
    a = _adapter(
        [
            {
                "timestamp": "2026-07-12T10:15:13.000000000Z",
                "ratexp.session_id": "s1",
                "ratexp.skill_name": "demo",
                "ratexp.agent": "cc",
                "ratexp.score": 2,
                "ratexp.comment": "bad",
                "ratexp.request_id": "r1",
                "ratexp.eval_name": "human-satisfaction",
            }
        ]
    )
    (row,) = a.select_feedback(10)
    # Timestamp trimmed to whole seconds + Z, matching the psql shape.
    assert row == (
        "2026-07-12T10:15:13Z",
        "s1",
        "demo",
        "cc",
        2,
        "bad",
        "r1",
        "human-satisfaction",
    )


def test_select_top_skills_maps():
    a = _adapter([{"skill_name": "demo", "total": 5, "good": 4, "bad": 1}])
    assert a.select_top_skills(10) == [{"skill_name": "demo", "total": 5, "good": 4, "bad": 1}]


def test_transcript_valid_atif_parsed():
    a = _adapter(
        [
            {
                "timestamp": "2026-07-12T10:15:13Z",
                "ratexp.session_id": "s1",
                "ratexp.skill_name": "demo",
                "ratexp.agent": "cc",
                "ratexp.schema_version": "ATIF-v1.7",
                "ratexp.atif": '{"schema_version":"ATIF-v1.7","steps":[]}',
                "ratexp.request_id": "r1",
            }
        ]
    )
    (row,) = a.select_transcript(10)
    assert row[5] == {"schema_version": "ATIF-v1.7", "steps": []}


def test_transcript_truncated_atif_becomes_stub():
    a = _adapter(
        [
            {
                "timestamp": "2026-07-12T10:15:13Z",
                "ratexp.session_id": "s1",
                "ratexp.skill_name": "demo",
                "ratexp.agent": "cc",
                "ratexp.schema_version": "ATIF-v1.7",
                "ratexp.atif": '{"steps":[{"message":"hi',  # truncated -> invalid JSON
                "ratexp.request_id": "r1",
            }
        ]
    )
    (row,) = a.select_transcript(10)
    assert row[5]["dynatrace_truncated"] is True
    assert row[5]["steps"] == []


def test_dynatrace_run_query_executes_dql_and_maps():
    a = DynatraceReadAdapter("app_be_dynatrace", "https://tenant.example", "tok")
    captured = {}

    def _dql(query):
        captured["query"] = query
        return [{"skill_name": "demo", "n": 3}]

    a._dql = _dql
    columns, rows = a.run_query('fetch logs | filter ratexp.record_type == "feedback"', 50, 5000)
    assert columns == ["skill_name", "n"]
    assert rows == [("demo", 3)]
    assert "| limit 50" in captured["query"]  # row cap enforced


def test_dynatrace_run_query_normalizes_columns():
    a = DynatraceReadAdapter("app_be_dynatrace", "https://tenant.example", "tok")
    a._dql = lambda q: [
        {
            "timestamp": "2026-07-12T10:00:00.000000000Z",
            "ratexp.skill_name": "demo",
            "ratexp.score": "2",  # DQL may return the attribute as a string
            "content": "x",
        }
    ]
    cols, rows = a.run_query('fetch logs | filter ratexp.record_type == "feedback"', 10, 5000)
    # ratexp. prefix stripped, timestamp -> created_at (trimmed), score coerced to int.
    assert cols == ["created_at", "skill_name", "score", "content"]
    assert rows == [("2026-07-12T10:00:00Z", "demo", 2, "x")]


def test_dynatrace_run_query_rejects_non_dql():
    a = _adapter([])
    with pytest.raises(ValueError):
        a.run_query("SELECT 1", 50, 5000)  # not a DQL read verb
    with pytest.raises(ValueError):
        a.run_query("   ", 50, 5000)


def test_dynatrace_query_language_is_dql():
    assert DynatraceReadAdapter("x", "https://t", "tok").query_language == "DQL"


def test_transcripts_by_ids_empty_skips_query():
    a = DynatraceReadAdapter("app_be_dynatrace", "https://tenant.example", "tok")

    def _boom(_query):
        raise AssertionError("must not query when there are no ids")

    a._dql = _boom
    assert a.select_transcripts_by_ids([], []) == []


def test_requires_query_url_and_token():
    with pytest.raises(RuntimeError):
        DynatraceReadAdapter("x", "", "tok")
    with pytest.raises(RuntimeError):
        DynatraceReadAdapter("x", "https://t", "")


def test_open_read_source_selects_by_config(monkeypatch):
    import load_config

    # app_be_dynatrace enabled (app_be_psql would hit a real DB); env provides creds.
    monkeypatch.setattr(load_config, "READ_ADAPTER_PROVIDER", "app_be_dynatrace")
    monkeypatch.setattr(
        load_config,
        "READ_ADAPTERS",
        {"app_be_dynatrace": {"query_url_env": "RD_URL", "token_env": "RD_TOK"}},
    )
    monkeypatch.setenv("RD_URL", "https://tenant.example")
    monkeypatch.setenv("RD_TOK", "tok")
    assert open_read_source().name == "app_be_dynatrace"


# --- Arize Phoenix read adapter: span mapping and the filter box --------------


def _span(start_time="2026-07-12T10:15:13+00:00", span_id="Span:1", **attributes) -> dict:
    return {
        "id": span_id,
        "start_time": start_time,
        "attributes": {f"ratexp.{k}": v for k, v in attributes.items()},
    }


def _phoenix(spans: list, captured: dict | None = None) -> PhoenixReadAdapter:
    adapter = PhoenixReadAdapter("https://phoenix.example", "key", "ratexp")

    def _spans(params, timeout=30.0):
        if captured is not None:
            captured.update(params)
        return spans

    adapter._spans = _spans  # stub the Phoenix client
    return adapter


def test_phoenix_select_feedback_maps_spans():
    a = _phoenix(
        [
            _span(
                record_type="feedback",
                session_id="s1",
                skill_name="demo",
                agent="cc",
                score=2,
                comment="bad",
                request_id="r1",
                eval_name="human-satisfaction",
            )
        ]
    )
    (row,) = a.select_feedback(10)
    # Timestamp trimmed to whole seconds + Z, matching the psql shape.
    assert row == (
        "2026-07-12T10:15:13Z",
        "s1",
        "demo",
        "cc",
        2,
        "bad",
        "r1",
        "human-satisfaction",
    )


def test_phoenix_rows_come_back_newest_first():
    # Phoenix answers in ingest order and takes no sort parameter, so a backfilled
    # record would otherwise sit at the top of the dashboard.
    a = _phoenix(
        [
            _span(start_time="2026-07-10T09:00:00+00:00", skill_name="older"),
            _span(start_time="2026-07-12T09:00:00+00:00", skill_name="newer"),
        ]
    )
    assert [row[2] for row in a.select_feedback(10)] == ["newer", "older"]


def test_phoenix_transcript_atif_parsed():
    a = _phoenix(
        [
            _span(
                session_id="s1",
                skill_name="demo",
                agent="cc",
                schema_version="ATIF-v1.7",
                atif='{"schema_version":"ATIF-v1.7","steps":[]}',
                request_id="r1",
            )
        ]
    )
    (row,) = a.select_transcript(10)
    assert row[5] == {"schema_version": "ATIF-v1.7", "steps": []}


def test_phoenix_transcript_with_no_trajectory_becomes_a_stub():
    a = _phoenix([_span(skill_name="demo", schema_version="ATIF-v1.7")])
    (row,) = a.select_transcript(10)
    assert row[5] == {"schema_version": "ATIF-v1.7", "steps": []}


def test_phoenix_top_skills_are_tallied_here():
    # Phoenix cannot group or count, so the panel is built from the spans themselves.
    a = _phoenix(
        [
            _span(skill_name="demo", score=1),
            _span(skill_name="demo", score=2),
            _span(skill_name="other", score=1),
        ]
    )
    assert a.select_top_skills(10) == [
        {"skill_name": "demo", "total": 2, "good": 1, "bad": 1},
        {"skill_name": "other", "total": 1, "good": 1, "bad": 0},
    ]


def test_phoenix_top_skills_leaves_out_whole_session_ratings():
    # A session rating names no skill, so it would otherwise tally under a blank one.
    a = _phoenix([_span(skill_name="demo", score=1), _span(score=1)])
    assert a.select_top_skills(10) == [{"skill_name": "demo", "total": 1, "good": 1, "bad": 0}]


def test_phoenix_transcripts_by_ids_matches_either_id():
    a = _phoenix([_span(request_id="r1", session_id="s1"), _span(request_id="r2", session_id="s2")])
    assert [row[6] for row in a.select_transcripts_by_ids(["r2"], [])] == ["r2"]
    assert [row[6] for row in a.select_transcripts_by_ids([], ["s1"])] == ["r1"]


def test_phoenix_transcripts_by_ids_empty_skips_query():
    a = PhoenixReadAdapter("https://phoenix.example", "key", "ratexp")

    def _boom(params, timeout=30.0):
        raise AssertionError("must not query when there are no ids")

    a._spans = _boom
    assert a.select_transcripts_by_ids([], []) == []


def test_phoenix_filter_box_becomes_query_params():
    captured: dict = {}
    a = _phoenix([], captured)
    a.run_query("record_type:feedback skill_name:demo limit:5", 50, 5000)
    assert captured["attribute"] == ["ratexp.record_type:feedback", "ratexp.skill_name:demo"]
    assert captured["limit"] == 5


def test_phoenix_filter_box_cannot_ask_for_more_rows_than_allowed():
    captured: dict = {}
    a = _phoenix([], captured)
    a.run_query("limit:5000", 50, 5000)
    assert captured["limit"] == 50


def test_phoenix_filter_box_names_its_columns_like_the_preview():
    a = _phoenix([_span(skill_name="demo", score=2)])
    columns, rows = a.run_query("record_type:feedback", 10, 5000)
    # ratexp. prefix stripped, start_time -> created_at (trimmed).
    assert columns == ["created_at", "score", "skill_name"]
    assert rows == [("2026-07-12T10:15:13Z", 2, "demo")]


def test_phoenix_filter_box_rejects_anything_that_is_not_key_value():
    a = _phoenix([])
    for bad in ("SELECT 1", "   ", "limit:many"):
        with pytest.raises(ValueError):
            a.run_query(bad, 50, 5000)


def test_phoenix_query_language_is_its_own_filters():
    assert PhoenixReadAdapter("https://p", "key", "ratexp").query_language == "Phoenix filters"


def test_phoenix_change_signature_of_an_empty_project():
    assert _phoenix([]).change_signature() == ()


@pytest.mark.parametrize(
    "configured",
    [
        "https://app.phoenix.arize.com/s/your-space",
        "https://app.phoenix.arize.com/s/your-space/",
        "https://app.phoenix.arize.com/s/your-space/v1/traces",  # PHOENIX_COLLECTOR_ENDPOINT
    ],
)
def test_phoenix_accepts_every_form_of_its_endpoint(configured):
    a = PhoenixReadAdapter(configured, "key", "ratexp")
    assert a._url == "https://app.phoenix.arize.com/s/your-space/v1/projects/ratexp/spans"


def test_phoenix_requires_an_endpoint_key_and_project():
    with pytest.raises(RuntimeError):
        PhoenixReadAdapter("", "key", "ratexp")
    with pytest.raises(RuntimeError):
        PhoenixReadAdapter("https://p", "", "ratexp")
    with pytest.raises(RuntimeError):
        PhoenixReadAdapter("https://p", "key", "")


def test_open_read_source_selects_phoenix(monkeypatch):
    import load_config

    monkeypatch.setattr(load_config, "READ_ADAPTER_PROVIDER", "phoenix")
    monkeypatch.setattr(
        load_config,
        "READ_ADAPTERS",
        {
            "phoenix": {
                "endpoint_env": "PH_URL",
                "api_key_env": "PH_KEY",
                "project_env": "PH_PROJECT",
            }
        },
    )
    monkeypatch.setenv("PH_URL", "https://app.phoenix.arize.com/s/your-space")
    monkeypatch.setenv("PH_KEY", "key")
    monkeypatch.setenv("PH_PROJECT", "ratexp")
    assert open_read_source().name == "phoenix"


# --- PostgreSQL read adapter: SQL validation ---------------------------------


def test_postgres_validate_select():
    assert _validate_select("SELECT * FROM feedback;").startswith("SELECT")
    for bad in ("DELETE FROM feedback", "SELECT 1; DROP TABLE feedback", "   "):
        with pytest.raises(ValueError):
            _validate_select(bad)
