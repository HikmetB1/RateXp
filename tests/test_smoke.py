"""Smoke checks: the two services are up and serving their basics."""

from __future__ import annotations

import uuid

import pytest


def test_core_healthz(core_url, http):
    r = http.get(f"{core_url}/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_dashboard_healthz(app_url, http):
    r = http.get(f"{app_url}/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


@pytest.mark.parametrize("hook", ["ratexp-claude.sh", "ratexp-cursor.sh"])
def test_core_serves_the_hook_scripts(core_url, http, hook):
    # Each hook is fetched from here, so it must arrive ready to run: a bash
    # script with core's own URL, survey frequency and evals already baked in.
    r = http.get(f"{core_url}/{hook}")
    assert r.status_code == 200
    assert r.text.startswith("#!/bin/bash")
    assert "__RATEXP_" not in r.text


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
