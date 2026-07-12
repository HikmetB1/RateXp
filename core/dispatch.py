"""Fan a record out to every enabled write adapter.

core validates and redacts a record once (see ingest.py), then calls here to send
it to each configured destination (see write_adapters/). Every adapter is
independent and best-effort: a failure in one is logged and the rest still run, and
the request still succeeds. The built adapter list is held for the process lifetime;
server.py opens it at boot and closes it at shutdown.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from write_adapters import build_write_adapters

if TYPE_CHECKING:
    from models import Feedback, Transcript
    from write_adapters import WriteAdapter

logger = logging.getLogger(__name__)

_adapters: list[WriteAdapter] | None = None


def get_adapters() -> list[WriteAdapter]:
    global _adapters
    if _adapters is None:
        _adapters = build_write_adapters()
    return _adapters


def write_feedback(record: Feedback) -> None:
    for adapter in get_adapters():
        try:
            adapter.write_feedback(record)
        except Exception:  # noqa: BLE001 - independent, non-fatal fan-out
            logger.warning("adapter %s failed writing feedback", adapter.name, exc_info=True)


def write_transcript(record: Transcript) -> None:
    for adapter in get_adapters():
        try:
            adapter.write_transcript(record)
        except Exception:  # noqa: BLE001
            logger.warning("adapter %s failed writing transcript", adapter.name, exc_info=True)


def close_adapters() -> None:
    global _adapters
    if _adapters is not None:
        for adapter in _adapters:
            try:
                adapter.close()
            except Exception:  # noqa: BLE001
                logger.warning("adapter %s failed on close", adapter.name, exc_info=True)
        _adapters = None
