"""The /ws fan-out: one loop reads, every connected dashboard gets the same snapshot.

Cost tracks writes rather than viewers - the loop touches the read source only while
someone is connected, and rebuilds the snapshot only when the source's change signature
moves.
"""

from __future__ import annotations

import asyncio

from api.build_snapshot import build_snapshot
from fastapi import WebSocket
from load_config import WS_BROADCAST_INTERVAL_MS
from modules.read.adapters.read_adapter_interface import ReadAdapter


class Hub:
    """Tracks connected dashboards and pushes a message to all of them."""

    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def add(self, ws: WebSocket) -> None:
        async with self._lock:
            self._clients.add(ws)

    async def remove(self, ws: WebSocket) -> None:
        async with self._lock:
            self._clients.discard(ws)

    @property
    def empty(self) -> bool:
        return not self._clients

    async def broadcast(self, message: dict) -> None:
        async with self._lock:
            targets = list(self._clients)
        dead: list[WebSocket] = []
        for ws in targets:
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)  # send failed - the socket is gone
        if dead:
            async with self._lock:
                for ws in dead:
                    self._clients.discard(ws)


hub = Hub()


async def broadcast_changes(read: ReadAdapter) -> None:
    """Push a fresh snapshot to every client whenever `read`'s data changes."""
    interval = WS_BROADCAST_INTERVAL_MS / 1000
    last_sig: tuple | None = None
    while True:
        await asyncio.sleep(interval)
        if hub.empty:
            continue  # nobody watching - don't touch the read source
        try:
            sig = await asyncio.to_thread(read.change_signature)
        except Exception:
            continue  # transient hiccup; try again next interval
        if sig == last_sig:
            continue  # no new data since the last push
        last_sig = sig
        try:
            snapshot = await asyncio.to_thread(build_snapshot, read)
        except Exception:
            continue
        await hub.broadcast(snapshot)
