"""What each destination does with a record: the SQL, the OTLP mapping, the URL.

Nothing here opens a connection or sends a request. Choosing which destinations
to build is in test_dispatch_to_adapters.py.
"""

from __future__ import annotations

import contextlib
import io
import json
import urllib.error

import pytest
from api.record_schemas import Feedback, Transcript
from modules.write.adapters import write_to_phoenix
from modules.write.adapters.write_to_app_be_dynatrace import AppBeDynatraceWriteAdapter
from modules.write.adapters.write_to_bluebox import BlueboxWriteAdapter
from modules.write.adapters.write_to_custom_dynatrace import CustomDynatraceWriteAdapter
from modules.write.adapters.write_to_custom_psql import CustomPostgresWriteAdapter
from modules.write.adapters.write_to_dynatrace import DynatraceWriteAdapter
from modules.write.adapters.write_to_phoenix import PhoenixWriteAdapter
from modules.write.adapters.write_to_postgres import PostgresWriteAdapter

# --- PostgreSQL ---------------------------------------------------------------


class _FakeCursor:
    def __init__(self, calls: dict):
        self._calls = calls

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, sql, params):
        self._calls["sql"] = sql
        self._calls["params"] = params


class _FakeConnection:
    def __init__(self, calls: dict):
        self._calls = calls

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def cursor(self):
        return _FakeCursor(self._calls)


class _FakePool:
    def __init__(self):
        self.calls: dict = {}

    @contextlib.contextmanager
    def connection(self):
        yield _FakeConnection(self.calls)

    def close(self):
        pass


def _postgres() -> PostgresWriteAdapter:
    adapter = PostgresWriteAdapter("app_be_psql", dsn="x", auth="password")
    adapter._pool = _FakePool()  # set directly, so no migrations and no real database
    return adapter


def test_a_rating_becomes_one_insert_with_its_columns_in_order():
    adapter = _postgres()
    adapter.write_feedback(
        Feedback(
            skill_name="demo",
            agent="claude-code",
            eval_name="human-satisfaction",
            score=1,
            comment="great",
            session_id="s",
            request_id="r",
            created_at="2026-01-01T00:00:00Z",
        )
    )
    assert "INSERT INTO feedback" in adapter._pool.calls["sql"]
    assert adapter._pool.calls["params"] == (
        "2026-01-01T00:00:00Z",
        "s",
        "demo",
        "claude-code",
        "human-satisfaction",
        1,
        "great",
        "r",
    )


def test_a_repeated_request_id_is_not_inserted_twice():
    # The hook retries on a lost response, so the request id is the idempotency
    # key. Without this clause a flaky network doubles someone's rating.
    adapter = _postgres()
    adapter.write_feedback(Feedback(skill_name="demo", agent="claude-code", request_id="r"))
    assert "ON CONFLICT (request_id)" in adapter._pool.calls["sql"]
    assert "DO NOTHING" in adapter._pool.calls["sql"]


def test_a_trajectory_is_stored_as_json():
    adapter = _postgres()
    adapter.write_transcript(
        Transcript(skill_name="demo", agent="claude-code", atif={"steps": [{"step_id": 1}]})
    )
    assert "INSERT INTO transcript" in adapter._pool.calls["sql"]
    assert json.loads(adapter._pool.calls["params"][5]) == {"steps": [{"step_id": 1}]}


def test_an_adopters_postgres_with_no_connection_string_is_refused(monkeypatch):
    monkeypatch.delenv("UNSET_DSN", raising=False)
    with pytest.raises(RuntimeError):
        CustomPostgresWriteAdapter("UNSET_DSN")


def test_an_adopters_postgres_reads_its_connection_string_from_the_named_variable(monkeypatch):
    # The secret is named in config.yaml but never written there.
    monkeypatch.setenv("ADOPTER_DSN", "postgresql://someone@elsewhere/db")
    adapter = CustomPostgresWriteAdapter("ADOPTER_DSN")
    assert adapter.name == "custom_psql"
    assert adapter._dsn == "postgresql://someone@elsewhere/db"


# --- Dynatrace and Bluebox (OTLP) ---------------------------------------------

OTLP_LOGS = "/api/v2/otlp/v1/logs"


def _with_fake_logger(adapter: DynatraceWriteAdapter) -> list[dict]:
    """Capture what the adapter would emit, skipping the real SDK pipeline."""
    emitted: list[dict] = []

    class FakeLogger:
        def emit(self, **kwargs):
            emitted.append(kwargs)

    adapter._provider = object()
    adapter._logger = FakeLogger()
    return emitted


def test_a_rating_becomes_one_otlp_log_record():
    pytest.importorskip("opentelemetry.sdk._logs")
    adapter = DynatraceWriteAdapter("app_be_dynatrace", "https://tenant.example", "tok")
    emitted = _with_fake_logger(adapter)
    adapter.write_feedback(
        Feedback(
            skill_name="demo",
            agent="claude-code",
            eval_name="human-satisfaction",
            score=2,
            comment="bad",
            session_id="s",
            request_id="r",
            created_at="2026-01-01T00:00:00Z",
        )
    )
    (record,) = emitted
    assert record["body"].startswith("RateXp rating: bad")
    attributes = record["attributes"]
    assert attributes["ratexp.record_type"] == "feedback"
    assert attributes["ratexp.eval_name"] == "human-satisfaction"
    assert attributes["ratexp.score"] == 2
    assert attributes["ratexp.rating"] == "bad"  # the number is unreadable in a log viewer
    assert attributes["ratexp.comment"] == "bad"


def test_an_unrated_run_still_becomes_a_log_record():
    pytest.importorskip("opentelemetry.sdk._logs")
    adapter = DynatraceWriteAdapter("app_be_dynatrace", "https://tenant.example", "tok")
    emitted = _with_fake_logger(adapter)
    adapter.write_feedback(Feedback(skill_name="demo", agent="claude-code"))
    (record,) = emitted
    assert "unrated" in record["body"]
    # A None attribute is dropped rather than exported as a null.
    assert "ratexp.score" not in record["attributes"]


def test_a_huge_trajectory_is_truncated_and_says_so():
    # Dynatrace rejects an oversized attribute outright, which would lose the
    # whole record instead of the tail of one field.
    pytest.importorskip("opentelemetry.sdk._logs")
    adapter = DynatraceWriteAdapter("app_be_dynatrace", "https://tenant.example", "tok")
    emitted = _with_fake_logger(adapter)
    adapter.write_transcript(
        Transcript(
            skill_name="demo",
            agent="claude-code",
            atif={"steps": [{"message": "x" * 300_000}]},
        )
    )
    attributes = emitted[0]["attributes"]
    assert attributes["ratexp.atif_truncated"] is True
    assert len(attributes["ratexp.atif"]) == 200_000


def test_a_tenant_url_or_token_that_is_missing_is_refused():
    with pytest.raises(RuntimeError):
        DynatraceWriteAdapter("app_be_dynatrace", "", "tok")
    with pytest.raises(RuntimeError):
        DynatraceWriteAdapter("app_be_dynatrace", "https://tenant.example", "")


@pytest.mark.parametrize("adapter_class", [AppBeDynatraceWriteAdapter, CustomDynatraceWriteAdapter])
def test_a_dynatrace_destination_takes_a_bare_tenant_url(adapter_class):
    adapter = adapter_class("https://tenant.example", "tok")
    assert adapter._endpoint == "https://tenant.example" + OTLP_LOGS


@pytest.mark.parametrize(
    "configured",
    [
        "https://abc12345.live.dynatrace.com/api/v2/otlp",  # what `bluebox otlp-endpoint` prints
        "https://abc12345.live.dynatrace.com/api/v2/otlp/",
        "https://abc12345.live.dynatrace.com",  # a bare tenant url, like the others
    ],
)
def test_bluebox_accepts_every_form_of_its_endpoint(configured):
    # Bluebox prints the endpoint with the prefix already on it, and the shared
    # base appends the whole path itself. Doubling it would 404 silently.
    adapter = BlueboxWriteAdapter(configured, "tok")
    assert adapter._endpoint == "https://abc12345.live.dynatrace.com" + OTLP_LOGS
    assert adapter.name == "bluebox"


def test_bluebox_without_an_endpoint_or_token_is_refused():
    with pytest.raises(RuntimeError):
        BlueboxWriteAdapter("", "tok")
    with pytest.raises(RuntimeError):
        BlueboxWriteAdapter("https://abc12345.live.dynatrace.com/api/v2/otlp", "")


# --- Arize Phoenix (REST spans) -----------------------------------------------


def _phoenix() -> tuple[PhoenixWriteAdapter, list[dict]]:
    """The adapter with its POST captured, so the span it builds is asserted, not sent."""
    adapter = PhoenixWriteAdapter("https://app.phoenix.arize.com/s/x", "key", "ratexp")
    posted: list[dict] = []
    adapter._post_span = posted.append
    return adapter, posted


def test_a_rating_becomes_one_phoenix_span():
    adapter, posted = _phoenix()
    adapter.write_feedback(
        Feedback(
            skill_name="demo",
            agent="claude-code",
            eval_name="human-satisfaction",
            score=2,
            comment="bad",
            session_id="s",
            request_id="r",
            created_at="2026-01-01T00:00:00Z",
        )
    )
    (span,) = posted
    assert span["name"] == "ratexp.feedback"
    assert span["span_kind"] == "EVALUATOR"
    assert span["start_time"] == span["end_time"] == "2026-01-01T00:00:00+00:00"
    attributes = span["attributes"]
    assert attributes["ratexp.record_type"] == "feedback"
    assert attributes["ratexp.eval_name"] == "human-satisfaction"
    assert attributes["ratexp.score"] == 2
    assert attributes["ratexp.rating"] == "bad"  # the number alone is unreadable in the UI
    assert attributes["ratexp.comment"] == "bad"


def test_an_unrated_run_still_becomes_a_span():
    adapter, posted = _phoenix()
    adapter.write_feedback(Feedback(skill_name="demo", agent="claude-code"))
    attributes = posted[0]["attributes"]
    assert attributes["ratexp.rating"] == "unrated"
    # A None attribute is dropped rather than sent as a null.
    assert "ratexp.score" not in attributes


def test_a_whole_session_rating_reaches_phoenix_without_a_skill():
    adapter, posted = _phoenix()
    adapter.write_feedback(Feedback(agent="claude-code", score=1, session_id="s"))
    attributes = posted[0]["attributes"]
    assert "ratexp.skill_name" not in attributes
    assert attributes["ratexp.agent"] == "claude-code"


def test_a_trajectory_goes_into_a_phoenix_span_whole():
    adapter, posted = _phoenix()
    adapter.write_transcript(
        Transcript(skill_name="demo", agent="claude-code", atif={"steps": [{"step_id": 1}]})
    )
    (span,) = posted
    assert span["span_kind"] == "AGENT"
    assert json.loads(span["attributes"]["ratexp.atif"]) == {"steps": [{"step_id": 1}]}


def test_the_same_request_id_always_builds_the_same_span_id():
    # This is the whole de-duplication: a retried post carries an id Phoenix
    # already has, and gets refused instead of stored a second time.
    adapter, posted = _phoenix()
    for _ in range(2):
        adapter.write_feedback(Feedback(skill_name="demo", agent="claude-code", request_id="r"))
    first, second = (span["context"] for span in posted)
    assert first == second


def test_a_rating_and_a_transcript_sharing_a_request_id_get_different_span_ids():
    adapter, posted = _phoenix()
    record = {"skill_name": "demo", "agent": "claude-code", "request_id": "r"}
    adapter.write_feedback(Feedback(**record))
    adapter.write_transcript(Transcript(**record, atif={"steps": []}))
    rating, transcript = posted
    assert rating["context"] != transcript["context"]


def test_a_record_without_a_request_id_is_never_a_duplicate():
    # Nothing to de-duplicate on, so two of them must not collide into one span.
    adapter, posted = _phoenix()
    for _ in range(2):
        adapter.write_feedback(Feedback(skill_name="demo", agent="claude-code"))
    first, second = (span["context"] for span in posted)
    assert first != second


@pytest.mark.parametrize(
    "configured",
    [
        "https://app.phoenix.arize.com/s/your-space",
        "https://app.phoenix.arize.com/s/your-space/",
        "https://app.phoenix.arize.com/s/your-space/v1/traces",  # PHOENIX_COLLECTOR_ENDPOINT
    ],
)
def test_phoenix_accepts_every_form_of_its_endpoint(configured):
    # The collector endpoint gets copied with the OTLP path on it, and the REST
    # path is appended here - doubling it up would 404 silently.
    adapter = PhoenixWriteAdapter(configured, "key", "ratexp")
    assert adapter._url == "https://app.phoenix.arize.com/s/your-space/v1/projects/ratexp/spans"
    assert adapter.name == "phoenix"


def test_a_phoenix_project_name_is_escaped_into_the_url():
    adapter = PhoenixWriteAdapter("https://phoenix.example", "key", "my project")
    assert adapter._url == "https://phoenix.example/v1/projects/my%20project/spans"


def test_phoenix_without_an_endpoint_key_or_project_is_refused():
    with pytest.raises(RuntimeError):
        PhoenixWriteAdapter("", "key", "ratexp")
    with pytest.raises(RuntimeError):
        PhoenixWriteAdapter("https://phoenix.example", "", "ratexp")
    with pytest.raises(RuntimeError):
        PhoenixWriteAdapter("https://phoenix.example", "key", "")


# What core does with each of Phoenix's answers. The fan-out reads "did not raise"
# as stored, so anything Phoenix did not take has to come back out as an exception.


class _FakeResponse:
    def __init__(self, body: dict):
        self._body = json.dumps(body).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self):
        return self._body


def _phoenix_answering(monkeypatch, answer) -> PhoenixWriteAdapter:
    """An adapter whose POST gets `answer` back: a response body, or an error raised."""

    def _urlopen(_request, timeout=None):
        if isinstance(answer, Exception):
            raise answer
        return _FakeResponse(answer)

    monkeypatch.setattr(write_to_phoenix.urllib.request, "urlopen", _urlopen)
    return PhoenixWriteAdapter("https://phoenix.example", "key", "ratexp")


def _refusal(body: dict) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        "https://phoenix.example", 400, "Bad Request", {}, io.BytesIO(json.dumps(body).encode())
    )


def test_a_span_phoenix_queued_counts_as_stored(monkeypatch):
    adapter = _phoenix_answering(monkeypatch, {"total_received": 1, "total_queued": 1})
    adapter.write_feedback(Feedback(skill_name="demo", agent="claude-code"))


def test_a_retried_post_phoenix_already_has_counts_as_stored(monkeypatch):
    adapter = _phoenix_answering(
        monkeypatch,
        _refusal({"total_queued": 0, "total_duplicates": 1, "total_invalid": 0}),
    )
    adapter.write_feedback(Feedback(skill_name="demo", agent="claude-code", request_id="r"))


def test_a_span_phoenix_rejected_as_invalid_fails(monkeypatch):
    adapter = _phoenix_answering(
        monkeypatch,
        _refusal({"total_queued": 0, "total_duplicates": 0, "total_invalid": 1}),
    )
    with pytest.raises(urllib.error.HTTPError):
        adapter.write_feedback(Feedback(skill_name="demo", agent="claude-code"))


def test_an_answer_that_queued_nothing_fails(monkeypatch):
    adapter = _phoenix_answering(monkeypatch, {"total_received": 1, "total_queued": 0})
    with pytest.raises(RuntimeError):
        adapter.write_feedback(Feedback(skill_name="demo", agent="claude-code"))
