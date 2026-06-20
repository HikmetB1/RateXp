"""Shared fixtures. Stubs the store so tests need no real database."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# core/ is laid out as flat modules - make them importable regardless of where
# pytest is invoked from.
_CORE_DIR = Path(__file__).resolve().parent.parent
if str(_CORE_DIR) not in sys.path:
    sys.path.insert(0, str(_CORE_DIR))


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch):
    """Each test starts with a clean, predictable environment."""
    for var in ("RATEXP_DB_AUTH", "DATABASE_URL"):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture(autouse=True)
def _disable_redaction(monkeypatch):
    """Keep redaction out of the way by default (config ships enabled: true).

    Tests that exercise redaction opt back in by patching `redact.REDACTION_ENABLED`
    or `ingest.redact_atif` themselves.
    """
    import redact

    monkeypatch.setattr(redact, "REDACTION_ENABLED", False)


@pytest.fixture
def store_stub(monkeypatch):
    """Swap the store singleton for a list-appender; return the captured records."""
    import store

    captured: list = []

    class StubStore:
        def append(self, record):
            captured.append(record)

        def append_transcript(self, record):
            captured.append(record)

        def close(self):
            pass

    monkeypatch.setattr(store, "_store", StubStore())
    return captured


@pytest.fixture
def client(monkeypatch, store_stub):
    """Return (TestClient, captured). The store is the stub from store_stub.

    Used by the middleware tests; the store is stubbed so importing/using the
    app needs no database.
    """
    import server
    from fastapi.testclient import TestClient
    from ratelimit import RateLimiter

    # Keep the limiter out of the way unless a test exercises it explicitly.
    monkeypatch.setattr(server, "_limiter", RateLimiter(1_000_000))
    return TestClient(server.app), store_stub
