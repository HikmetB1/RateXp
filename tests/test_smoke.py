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


def test_core_serves_mcp_tools(mcp_tools):
    # The MCP server is what a skill connects to; it must advertise the three
    # tools the feedback flow uses.
    assert {"feedback", "submit_feedback", "submit_trajectory"} <= set(mcp_tools)
