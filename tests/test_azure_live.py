"""Opt-in smoke tests against the *deployed* Azure web apps.

These never run by default. Enable them only when you have a live environment:

    export RATEXP_AZURE_LIVE=1
    export RATEXP_AZURE_CORE_URL=https://ratexp-dev-core.azurewebsites.net
    export RATEXP_AZURE_APP_URL=https://ratexp-dev-app.azurewebsites.net

Without those, every test here is skipped so normal/CI runs stay green.
"""

from __future__ import annotations

import os

import pytest

AZURE_LIVE = os.environ.get("RATEXP_AZURE_LIVE") == "1"
AZURE_CORE_URL = os.environ.get("RATEXP_AZURE_CORE_URL", "").rstrip("/")
AZURE_APP_URL = os.environ.get("RATEXP_AZURE_APP_URL", "").rstrip("/")

# One marker skips the whole module unless the live env is configured.
pytestmark = pytest.mark.skipif(
    not (AZURE_LIVE and AZURE_CORE_URL and AZURE_APP_URL),
    reason="set RATEXP_AZURE_LIVE=1 + RATEXP_AZURE_CORE_URL + RATEXP_AZURE_APP_URL to run",
)


def test_azure_core_is_up(http):
    r = http.get(f"{AZURE_CORE_URL}/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_azure_core_serves_snippet(http):
    r = http.get(f"{AZURE_CORE_URL}/snippet", params={"every": 1})
    assert r.status_code == 200
    # In Azure the snippet must point back at the deployed core, over https.
    assert "https://" in r.text
    assert "/feedback" in r.text


def test_azure_dashboard_is_up(http):
    r = http.get(f"{AZURE_APP_URL}/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_azure_dashboard_shows_trajectories(http):
    """The deployed dashboard's snapshot must link feedback rows to their transcripts.

    This is the exact symptom that was reported: the live dashboard showed no
    trajectory. The snapshot's transcripts must correlate to its feedback rows.
    """
    r = http.get(f"{AZURE_APP_URL}/snapshot")
    assert r.status_code == 200
    data = r.json()
    assert data.get("feedback"), "no feedback on the deployed dashboard"

    tx_ids = {t.get("request_id") for t in data["transcripts"]} | {
        t.get("session_id") for t in data["transcripts"]
    }
    linked = [
        f
        for f in data["feedback"]
        if f.get("request_id") in tx_ids or f.get("session_id") in tx_ids
    ]
    assert linked, "no feedback row has a matching transcript - trajectories would show empty"
