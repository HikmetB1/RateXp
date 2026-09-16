"""Fan a record out to every enabled write adapter.

core validates and redacts a record once (see ingest.py), then calls here to send
it to each configured destination (see write_adapters/). Every adapter is
independent: a failure in one is logged and the rest still run. The fan-out is
at-least-one - if no destination accepted the record we raise WriteError, which
server.py turns into HTTP 503, so a caller is never told "stored" when nothing was.
The built adapter list is held for the process lifetime; server.py opens it at boot
and closes it at shutdown.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from write_adapters import build_write_adapters

if TYPE_CHECKING:
    from collections.abc import Callable

    from models import Feedback, Transcript
    from write_adapters import WriteAdapter

logger = logging.getLogger(__name__)

_adapters: list[WriteAdapter] | None = None


class WriteError(RuntimeError):
    """No enabled destination accepted the record."""


def get_adapters() -> list[WriteAdapter]:
    global _adapters
    if _adapters is None:
        _adapters = build_write_adapters()
    return _adapters


def _fan_out(kind: str, send: Callable[[WriteAdapter], None]) -> None:
    """Send to every adapter, log each failure, raise if none accepted the record."""
    accepted = 0
    for adapter in get_adapters():
        try:
            send(adapter)
        except Exception:  # noqa: BLE001 - independent fan-out; the rest still run
            logger.warning("adapter %s failed writing %s", adapter.name, kind, exc_info=True)
        else:
            accepted += 1
    if accepted == 0:
        raise WriteError(f"no destination accepted the {kind}")


def write_feedback(record: Feedback) -> None:
    _fan_out("feedback", lambda adapter: adapter.write_feedback(record))


def write_transcript(record: Transcript) -> None:
    _fan_out("transcript", lambda adapter: adapter.write_transcript(record))


def close_adapters() -> None:
    global _adapters
    if _adapters is not None:
        for adapter in _adapters:
            try:
                adapter.close()
            except Exception:  # noqa: BLE001
                logger.warning("adapter %s failed on close", adapter.name, exc_info=True)
        _adapters = None
