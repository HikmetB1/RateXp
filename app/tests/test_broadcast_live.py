"""The /ws live feed: a snapshot on connect, and the off switch."""

from __future__ import annotations

import pytest


def test_ws_sends_snapshot_on_connect(app_with_fake_pool):
    client, pool = app_with_fake_pool
    pool.set_select_rows([])  # all three snapshot queries return empty
    with client.websocket_connect("/ws") as ws:
        msg = ws.receive_json()
    assert msg["type"] == "snapshot"
    assert msg["feedback"] == []
    assert msg["transcripts"] == []
    assert msg["stats"] == []


def test_ws_disabled_closes(app_with_fake_pool, monkeypatch):
    client, _ = app_with_fake_pool
    from api import serve_http

    monkeypatch.setattr(serve_http, "WS_ENABLED", False)
    with pytest.raises(Exception):  # noqa: B017 - any disconnect/close is fine
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()
