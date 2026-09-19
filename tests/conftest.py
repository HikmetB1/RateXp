"""Shared fixtures for the whole-app (integration) test suite.

Unlike the per-service suites under core/, app/ and functions/, these
tests are black-box: they talk to *running* services over HTTP, exactly like a
real client would. Two modes:

- Local stack (default): point at the docker-compose stack on localhost. These
  tests always run; if the stack isn't up they skip with a clear hint.
- Live Azure (opt-in): set RATEXP_AZURE_LIVE=1 and the deployed URLs to smoke
  the real Azure web apps. Without those vars, the Azure tests skip.
"""

from __future__ import annotations

import os
import shlex

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


# --- core ingestion helpers (core's surface is plain HTTP) --------------------
# The shipped hook posts multipart form fields with `curl --form-string`, so the
# fixtures below put the same shape on the wire, just from Python.


def _form(fields: dict) -> dict:
    """Fields as multipart parts - what `curl --form-string name=value` sends."""
    return {name: (None, str(value)) for name, value in fields.items() if value is not None}


def baked_url(script: str) -> str:
    """The URL compiled into a copy of ratexp.sh, read off its DEFAULT_URL line.

    core serves the script with its own public URL substituted for the
    `'__RATEXP_URL__'` placeholder; shlex strips whatever quoting was used.
    """
    for line in script.splitlines():
        if line.startswith("DEFAULT_URL="):
            return (shlex.split(line.split("=", 1)[1]) or [""])[0]
    return ""


@pytest.fixture
def post_feedback(core_url, http):
    """POST a rating to core the way the hook does; returns the response."""

    def _post(**fields) -> httpx.Response:
        return http.post(f"{core_url}/feedback", files=_form(fields))

    return _post


@pytest.fixture
def post_transcript(core_url, http):
    """POST a trajectory to core; returns the response.

    Pass `transcript=<raw .jsonl>` for the hook's form upload (core converts it
    to ATIF), or `atif=<dict>` to send a ready-built trajectory as JSON.
    """

    def _post(**fields) -> httpx.Response:
        if "atif" in fields:
            return http.post(f"{core_url}/transcript", json=fields, timeout=30)
        return http.post(f"{core_url}/transcript", files=_form(fields), timeout=30)

    return _post
