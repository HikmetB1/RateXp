"""Opt-in checks against the *deployed* Azure web apps.

These never run by default. Enable them only when you have a live environment:

    export RATEXP_AZURE_LIVE=1
    export RATEXP_AZURE_CORE_URL=https://ratexp-dev-core.azurewebsites.net
    export RATEXP_AZURE_APP_URL=https://ratexp-dev-app.azurewebsites.net

Without those, every test here is skipped so normal/CI runs stay green.

Read-only on purpose: the other two files store rows, so pointing them at a
deployed stack with RATEXP_CORE_URL / RATEXP_APP_URL would leave test data on a
real dashboard. Both tests below need their service to answer, so a service that
is down fails the run without a separate health check.
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


def test_azure_core_sends_the_plugin_its_surveys(http):
    """The deployed core must answer the plugin's hooks at session start.

    Without this answer the plugin's hooks ask no survey at all.
    """
    r = http.get(f"{AZURE_CORE_URL}/hook-settings")
    assert r.status_code == 200
    body = r.json()
    assert body["default_eval"] in {e["name"] for e in body["evals"]}


def test_azure_dashboard_links_feedback_to_its_trajectory(http):
    """The deployed dashboard's snapshot must carry the transcripts of the rows it shows.

    /snapshot is what the UI renders, so a feedback row whose transcript is
    missing from the same payload opens with an empty trajectory.
    """
    r = http.get(f"{AZURE_APP_URL}/snapshot")
    assert r.status_code == 200
    data = r.json()
    if not data["feedback"]:
        pytest.skip("nothing rated on the deployed dashboard yet")

    # The dashboard pairs a rating with its trajectory by request_id alone.
    tx_ids = {t["request_id"] for t in data["transcripts"]} - {None}
    assert any(f["request_id"] in tx_ids for f in data["feedback"]), (
        "no feedback row has a matching transcript - trajectories would show empty"
    )
