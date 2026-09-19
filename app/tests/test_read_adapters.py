"""Dynatrace read adapter: DQL record mapping + source selection (no network).

The DQL client (`_dql`) is stubbed with canned records, so the mapping to the row
shapes `api/` expects is asserted without any HTTP.
"""

from __future__ import annotations

import pytest
from modules.read.adapters.read_from_dynatrace import DynatraceReadAdapter
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
            }
        ]
    )
    (row,) = a.select_feedback(10)
    # Timestamp trimmed to whole seconds + Z, matching the psql shape.
    assert row == ("2026-07-12T10:15:13Z", "s1", "demo", "cc", 2, "bad", "r1")


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


# --- PostgreSQL read adapter: SQL validation ---------------------------------


def test_postgres_validate_select():
    assert _validate_select("SELECT * FROM feedback;").startswith("SELECT")
    for bad in ("DELETE FROM feedback", "SELECT 1; DROP TABLE feedback", "   "):
        with pytest.raises(ValueError):
            _validate_select(bad)
