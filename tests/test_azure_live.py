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
from conftest import baked_url

AZURE_LIVE = os.environ.get("RATEXP_AZURE_LIVE") == "1"
AZURE_CORE_URL = os.environ.get("RATEXP_AZURE_CORE_URL", "").rstrip("/")
AZURE_APP_URL = os.environ.get("RATEXP_AZURE_APP_URL", "").rstrip("/")

# One marker skips the whole module unless the live env is configured.
pytestmark = pytest.mark.skipif(
    not (AZURE_LIVE and AZURE_CORE_URL and AZURE_APP_URL),
    reason="set RATEXP_AZURE_LIVE=1 + RATEXP_AZURE_CORE_URL + RATEXP_AZURE_APP_URL to run",
)


def test_azure_core_serves_the_hook_script(http):
    """The deployed core must hand out a runnable hook that points back at itself.

    A skill installs its hook from here, so a leftover placeholder - or a stale
    RATEXP_PUBLIC_URL - would send every rating to the wrong place, or nowhere.
    """
    r = http.get(f"{AZURE_CORE_URL}/ratexp-skill.sh")
    assert r.status_code == 200
    assert "__RATEXP_URL__" not in r.text
    assert baked_url(r.text).rstrip("/") == AZURE_CORE_URL


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

    # Either id links the two; both are optional, so a missing one must not match.
    tx_ids = {t["request_id"] for t in data["transcripts"]}
    tx_ids |= {t["session_id"] for t in data["transcripts"]}
    tx_ids.discard(None)
    assert any(f["request_id"] in tx_ids or f["session_id"] in tx_ids for f in data["feedback"]), (
        "no feedback row has a matching transcript - trajectories would show empty"
    )
