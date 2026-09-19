"""Fan a record out to every enabled write adapter, and build that adapter list.

core validates and redacts a record once (see api/ingest_records.py), then calls
here to send it to each configured destination (see adapters/). Every adapter is
independent: a failure in one is logged and the rest still run. The fan-out is
at-least-one - if no destination accepted the record we raise WriteError, which
api/serve_http.py turns into HTTP 503, so a caller is never told "stored" when
nothing was. The built adapter list is held for the process lifetime;
api/serve_http.py opens it at boot and closes it at shutdown.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

    from api.record_schemas import Feedback, Transcript
    from modules.write.adapters.write_adapter_interface import WriteAdapter

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


def build_write_adapters() -> list[WriteAdapter]:
    """Build the destinations whose ``enabled`` flag is true in config.yaml.

    A destination that is enabled but can't be built (an OTLP adapter with no
    token, a custom PostgreSQL with no DSN) is logged and skipped rather than
    raising, so one half-configured destination never stops core from starting.
    """
    from load_config import WRITE_ADAPTERS

    built: list[WriteAdapter] = []
    for name, cfg in WRITE_ADAPTERS.items():
        if not cfg.get("enabled"):
            continue
        try:
            built.append(_build_one(name, cfg))
        except Exception:  # noqa: BLE001 - one bad destination mustn't stop the rest
            logger.warning(
                "adapter %s is enabled but could not be built; skipping", name, exc_info=True
            )
    return built


def _build_one(name: str, cfg: dict) -> WriteAdapter:
    """Construct one destination. Secrets come from the env vars cfg names."""
    if name == "app_be_psql":
        from modules.write.adapters.write_to_app_be_psql import AppBePostgresWriteAdapter

        return AppBePostgresWriteAdapter()
    if name == "custom_psql":
        from modules.write.adapters.write_to_custom_psql import CustomPostgresWriteAdapter

        return CustomPostgresWriteAdapter(cfg["dsn_env"])
    if name == "app_be_dynatrace":
        from modules.write.adapters.write_to_app_be_dynatrace import AppBeDynatraceWriteAdapter

        return AppBeDynatraceWriteAdapter(
            os.environ.get(cfg["tenant_url_env"], "").strip(),
            os.environ.get(cfg["token_env"], "").strip(),
        )
    if name == "custom_dynatrace":
        from modules.write.adapters.write_to_custom_dynatrace import CustomDynatraceWriteAdapter

        return CustomDynatraceWriteAdapter(
            os.environ.get(cfg["tenant_url_env"], "").strip(),
            os.environ.get(cfg["token_env"], "").strip(),
        )
    if name == "bluebox":
        from modules.write.adapters.write_to_bluebox import BlueboxWriteAdapter

        return BlueboxWriteAdapter(
            os.environ.get(cfg["endpoint_env"], "").strip(),
            os.environ.get(cfg["token_env"], "").strip(),
        )
    raise RuntimeError(f"unknown adapter {name!r}")
