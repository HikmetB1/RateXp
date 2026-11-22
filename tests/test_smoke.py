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


def test_core_sends_the_plugin_its_surveys(core_url, http):
    # The plugin's hooks ask for these at session start; without them no survey is asked.
    r = http.get(f"{core_url}/hook-settings")
    assert r.status_code == 200
    body = r.json()
    assert body["every"] >= 1
    assert body["default_eval"] in {e["name"] for e in body["evals"]}


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


def test_core_serves_the_docs_site(core_url, http):
    # Built into core's image from the repo's markdown; the root README is its Home page.
    r = http.get(f"{core_url}/guide/")
    assert r.status_code == 200
    assert "<title>RateXp docs</title>" in r.text


@pytest.mark.parametrize("page", ["docs/custom-deploy/", "core/", "app/ratexp/"])
def test_each_docs_page_sits_at_its_repo_path(core_url, http, page):
    assert http.get(f"{core_url}/guide/{page}").status_code == 200


def test_the_docs_site_without_its_slash_redirects_to_it(core_url, http):
    # The pages link relatively, so /guide would break every link on the Home page.
    r = http.get(f"{core_url}/guide")
    assert r.is_redirect
    assert r.headers["location"].endswith("/guide/")


def test_an_unknown_docs_page_gets_the_sites_own_404(core_url, http):
    r = http.get(f"{core_url}/guide/nope/")
    assert r.status_code == 404
    assert "RateXp docs" in r.text


def test_swagger_stays_at_docs(core_url, http):
    r = http.get(f"{core_url}/docs")
    assert r.status_code == 200
    assert "swagger" in r.text.lower()
