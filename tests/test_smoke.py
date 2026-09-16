"""Smoke checks: the two services are up and serving their basics."""

from __future__ import annotations

import uuid


def test_core_healthz(core_url, http):
    r = http.get(f"{core_url}/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_dashboard_healthz(app_url, http):
    r = http.get(f"{app_url}/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_core_serves_the_hook_script(core_url, http):
    # A skill's ratexp.sh is fetched from here, so it must arrive ready to run:
    # a bash script with core's own URL already baked in.
    r = http.get(f"{core_url}/ratexp.sh")
    assert r.status_code == 200
    assert r.text.startswith("#!/bin/bash")
    assert "__RATEXP_URL__" not in r.text


def test_core_accepts_a_feedback_post(core_url, post_feedback):
    # The hook's whole job ends in this one request - the minimal form it sends.
    r = post_feedback(
        skill_name=f"smoke-{uuid.uuid4().hex[:8]}",
        agent="claude-code",
        session_id=str(uuid.uuid4()),
        request_id=str(uuid.uuid4()),
        score=1,
    )
    assert r.status_code == 201
    assert r.json() == {"status": "stored"}
