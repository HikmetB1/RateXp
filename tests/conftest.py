"""Shared fixtures for the whole-app (integration) test suite.

Unlike the per-service suites under core/, app/app-be/ and functions/, these
tests are black-box: they talk to *running* services over HTTP, exactly like a
real client would. Two modes:

- Local stack (default): point at the docker-compose stack on localhost. These
  tests always run; if the stack isn't up they skip with a clear hint.
- Live Azure (opt-in): set RATEXP_AZURE_LIVE=1 and the deployed URLs to smoke
  the real Azure web apps. Without those vars, the Azure tests skip.
"""

from __future__ import annotations

import os

import httpx
import pytest

# Where the local stack lives. Defaults match docker-compose.yml's published ports.
CORE_URL = os.environ.get("RATEXP_CORE_URL", "http://localhost:8000").rstrip("/")
APP_URL = os.environ.get("RATEXP_APP_URL", "http://localhost:8001").rstrip("/")

# Deployed Azure endpoints for the opt-in live smoke tests.
AZURE_LIVE = os.environ.get("RATEXP_AZURE_LIVE") == "1"
AZURE_CORE_URL = os.environ.get("RATEXP_AZURE_CORE_URL", "").rstrip("/")
AZURE_APP_URL = os.environ.get("RATEXP_AZURE_APP_URL", "").rstrip("/")


def _reachable(url: str) -> bool:
    """True if the service answers /healthz with 200."""
    try:
        return httpx.get(f"{url}/healthz", timeout=3).status_code == 200
    except httpx.HTTPError:
        return False


@pytest.fixture(scope="session")
def core_url() -> str:
    """Base URL of the running core service, or skip if it isn't up."""
    if not _reachable(CORE_URL):
        pytest.skip(f"core not reachable at {CORE_URL} - run `docker compose up -d` first")
    return CORE_URL


@pytest.fixture(scope="session")
def app_url() -> str:
    """Base URL of the running dashboard service, or skip if it isn't up."""
    if not _reachable(APP_URL):
        pytest.skip(f"dashboard not reachable at {APP_URL} - run `docker compose up -d` first")
    return APP_URL


@pytest.fixture
def http() -> httpx.Client:
    """A short-timeout HTTP client, closed automatically after each test."""
    with httpx.Client(timeout=10) as client:
        yield client
