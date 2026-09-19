"""Shared fixtures. Nothing here reaches a database, a tenant, or the network.

Two fixtures are autouse, so they apply to every test in this folder whether it
asks for them or not, and both go wrong quietly if you forget they exist:

* the database environment variables are cleared, so a developer's own
  DATABASE_URL cannot change what a test sees;
* redaction is switched off, because config.yaml ships it on. A test that wants
  redaction has to switch it back on itself (see test_redact_trajectory.py).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# pytest puts this folder on sys.path, not its parent, so `api.*` and `modules.*`
# would not resolve. Add core/ itself, the directory the container imports from.
_CORE_DIR = Path(__file__).resolve().parent.parent
if str(_CORE_DIR) not in sys.path:
    sys.path.insert(0, str(_CORE_DIR))


@pytest.fixture(autouse=True)
def _isolate_database_env(monkeypatch):
    for var in ("RATEXP_DB_AUTH", "DATABASE_URL"):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture(autouse=True)
def _disable_redaction(monkeypatch):
    from modules.redaction import redact_trajectory

    monkeypatch.setattr(redact_trajectory, "REDACTION_ENABLED", False)


@pytest.fixture
def captured_writes(monkeypatch) -> list:
    """Replace the whole fan-out with one in-memory adapter, and return what it received.

    Every record goes to each enabled destination (see
    modules/write/dispatch_to_adapters.py). Standing in for all of them with a
    single capturing adapter lets a test assert on exactly what would be sent,
    with no database, tenant or token in the way.
    """
    from modules.write import dispatch_to_adapters

    captured: list = []

    class CapturingAdapter:
        name = "capture"

        def write_feedback(self, record):
            captured.append(record)

        def write_transcript(self, record):
            captured.append(record)

        def close(self):
            pass

    monkeypatch.setattr(dispatch_to_adapters, "_adapters", [CapturingAdapter()])
    return captured


@pytest.fixture
def client(monkeypatch, captured_writes):
    """A TestClient for the HTTP surface, fan-out stubbed and rate limiting off.

    Ask for `captured_writes` alongside it to see what a request stored.
    """
    from api import serve_http
    from api.limit_request_rate import RateLimiter
    from fastapi.testclient import TestClient

    # Capacity 0 means unlimited, so an ordinary test never trips the limiter.
    monkeypatch.setattr(serve_http, "_limiter", RateLimiter(0))
    return TestClient(serve_http.app)


@pytest.fixture
def no_destination_accepts(monkeypatch, captured_writes) -> None:
    """Point the fan-out at a destination that always fails.

    Depends on `captured_writes` so it is always applied after it, whichever
    order a test lists them in. A test asking for this one is asserting on the
    refusal, so `captured_writes` stays empty for it.
    """
    from modules.write import dispatch_to_adapters

    class FailingAdapter:
        name = "failing"

        def write_feedback(self, record):
            raise RuntimeError("destination down")

        def write_transcript(self, record):
            raise RuntimeError("destination down")

        def close(self):
            pass

    monkeypatch.setattr(dispatch_to_adapters, "_adapters", [FailingAdapter()])
