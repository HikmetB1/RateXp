"""build_write_adapters selection + the Postgres/Dynatrace adapter mapping."""

from __future__ import annotations

import contextlib

import pytest
from models import Feedback


def test_build_write_adapters_skips_disabled_and_unbuildable(monkeypatch):
    import config
    import write_adapters

    monkeypatch.setattr(
        config,
        "WRITE_ADAPTERS",
        {
            "app_be_psql": {"enabled": False},
            "custom_psql": {"enabled": True, "dsn_env": "NOPE_DSN"},  # env unset -> skipped
            "app_be_dynatrace": {  # token unset -> skipped
                "enabled": True,
                "tenant_url_env": "NOPE_TENANT",
                "token_env": "NOPE_TOKEN",
            },
            "custom_dynatrace": {"enabled": False, "tenant_url_env": "X", "token_env": "X"},
            "bluebox": {  # token unset -> skipped
                "enabled": True,
                "endpoint_env": "NOPE_ENDPOINT",
                "token_env": "NOPE_TOKEN",
            },
        },
    )
    monkeypatch.delenv("NOPE_DSN", raising=False)
    monkeypatch.delenv("NOPE_TOKEN", raising=False)
    monkeypatch.delenv("NOPE_TENANT", raising=False)
    monkeypatch.delenv("NOPE_ENDPOINT", raising=False)
    assert write_adapters.build_write_adapters() == []  # nothing enabled-and-buildable


def test_build_write_adapters_builds_enabled_psql(monkeypatch):
    import config
    import write_adapters

    monkeypatch.setattr(
        config,
        "WRITE_ADAPTERS",
        {
            "app_be_psql": {"enabled": True},
            "custom_psql": {"enabled": False, "dsn_env": "X"},
            "app_be_dynatrace": {"enabled": False, "tenant_url_env": "X", "token_env": "X"},
            "custom_dynatrace": {"enabled": False, "tenant_url_env": "X", "token_env": "X"},
            "bluebox": {"enabled": False, "endpoint_env": "X", "token_env": "X"},
        },
    )
    built = write_adapters.build_write_adapters()
    assert [a.name for a in built] == ["app_be_psql"]  # lazy pool, no DB touched here


# --- PostgresAdapter -----------------------------------------------------------


class _FakeCursor:
    def __init__(self, calls):
        self._calls = calls

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, sql, params):
        self._calls["sql"] = sql
        self._calls["params"] = params


class _FakeConn:
    def __init__(self, calls):
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
        yield _FakeConn(self.calls)

    def close(self):
        pass


def test_postgres_adapter_writes_feedback():
    from write_adapters.utils.postgres import PostgresWriteAdapter

    adapter = PostgresWriteAdapter("app_be_psql", dsn="x", auth="password")
    adapter._pool = _FakePool()  # skip _ensure_pool (no migrations / real DB)
    adapter.write_feedback(
        Feedback(skill_name="demo", agent="cc", score=1, session_id="s", request_id="r")
    )
    assert "INSERT INTO feedback" in adapter._pool.calls["sql"]
    # params order: created_at, session_id, skill_name, agent, score, comment, request_id
    assert adapter._pool.calls["params"][2] == "demo"
    assert adapter._pool.calls["params"][4] == 1


# --- DynatraceAdapter (mapping only; no network) -------------------------------


def test_dynatrace_adapter_maps_feedback():
    pytest.importorskip("opentelemetry.sdk._logs")
    from write_adapters.utils.dynatrace import DynatraceWriteAdapter

    adapter = DynatraceWriteAdapter("app_be_dynatrace", "https://tenant.example", "tok")
    captured: list = []

    class FakeLogger:
        def emit(self, **kw):
            captured.append(kw)

    adapter._provider = object()  # skip real SDK build
    adapter._logger = FakeLogger()
    adapter.write_feedback(
        Feedback(
            skill_name="demo",
            agent="cc",
            score=2,
            comment="bad",
            session_id="s",
            request_id="r",
            created_at="2026-01-01T00:00:00Z",
        )
    )
    (kw,) = captured
    assert kw["body"].startswith("RateXp rating: bad")
    assert kw["attributes"]["ratexp.record_type"] == "feedback"
    assert kw["attributes"]["ratexp.score"] == 2
    assert kw["attributes"]["ratexp.rating"] == "bad"


def test_dynatrace_adapter_requires_tenant_and_token():
    from write_adapters.utils.dynatrace import DynatraceWriteAdapter

    with pytest.raises(RuntimeError):
        DynatraceWriteAdapter("x", "", "tok")
    with pytest.raises(RuntimeError):
        DynatraceWriteAdapter("x", "https://t", "")
    adapter = DynatraceWriteAdapter("x", "https://tenant.example/", "tok")
    assert adapter._endpoint == "https://tenant.example/api/v2/otlp/v1/logs"


# --- BlueboxAdapter ------------------------------------------------------------


def test_bluebox_accepts_either_url_form():
    from write_adapters.bluebox import BlueboxWriteAdapter

    want = "https://abc12345.live.dynatrace.com/api/v2/otlp/v1/logs"
    # `bluebox otlp-endpoint` prints the URL with /api/v2/otlp already on it; the
    # prefix must not end up doubled.
    full = BlueboxWriteAdapter("https://abc12345.live.dynatrace.com/api/v2/otlp", "tok")
    assert full._endpoint == want
    assert full.name == "bluebox"
    # A trailing slash, and a bare tenant URL, both land on the same endpoint.
    trailing = BlueboxWriteAdapter("https://abc12345.live.dynatrace.com/api/v2/otlp/", "tok")
    assert trailing._endpoint == want
    bare = BlueboxWriteAdapter("https://abc12345.live.dynatrace.com", "tok")
    assert bare._endpoint == want


def test_bluebox_leaves_the_dynatrace_adapters_alone():
    from write_adapters.app_be_dynatrace import AppBeDynatraceWriteAdapter
    from write_adapters.custom_dynatrace import CustomDynatraceWriteAdapter

    # Bluebox does its URL fix-up in its own __init__, so the shared base and the
    # two Dynatrace adapters keep taking a bare tenant URL, unchanged.
    for cls in (AppBeDynatraceWriteAdapter, CustomDynatraceWriteAdapter):
        adapter = cls("https://tenant.example", "tok")
        assert adapter._endpoint == "https://tenant.example/api/v2/otlp/v1/logs"


def test_bluebox_requires_endpoint_and_token():
    from write_adapters.bluebox import BlueboxWriteAdapter

    with pytest.raises(RuntimeError):
        BlueboxWriteAdapter("", "tok")
    with pytest.raises(RuntimeError):
        BlueboxWriteAdapter("https://abc12345.live.dynatrace.com/api/v2/otlp", "")
