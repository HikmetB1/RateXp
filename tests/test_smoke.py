"""Smoke checks: the two services are up and serving their basics."""

from __future__ import annotations


def test_core_healthz(core_url, http):
    r = http.get(f"{core_url}/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_dashboard_healthz(app_url, http):
    r = http.get(f"{app_url}/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_core_serves_snippet(core_url, http):
    # The snippet is what a skill fetches; every=1 forces the full survey (not
    # the sampled-out "skip" message) so it must carry the submit URL.
    r = http.get(f"{core_url}/snippet", params={"every": 1})
    assert r.status_code == 200
    assert "/feedback" in r.text
