"""Build the set of enabled destination adapters from config.yaml ``adapters``.

Each of the four destinations is built only when its ``enabled`` flag is true. A
destination that is enabled but can't be built (e.g. a Dynatrace adapter with no
token, or a custom PostgreSQL with no DSN) is logged and skipped, never crashing
startup - consistent with the best-effort, independent fan-out in dispatch.py.
"""

from __future__ import annotations

import logging
import os

from .base import WriteAdapter

logger = logging.getLogger(__name__)


def build_write_adapters() -> list[WriteAdapter]:
    from config import WRITE_ADAPTERS

    built: list[WriteAdapter] = []
    for name, cfg in WRITE_ADAPTERS.items():
        if not cfg.get("enabled"):
            continue
        try:
            built.append(_build_one(name, cfg))
        except Exception:  # noqa: BLE001 - one bad destination mustn't stop the rest
            logger.warning("adapter %s is enabled but could not be built; skipping", name, exc_info=True)
    return built


def _build_one(name: str, cfg: dict) -> WriteAdapter:
    if name == "app_be_psql":
        from .app_be_psql import AppBePostgresWriteAdapter

        return AppBePostgresWriteAdapter()
    if name == "custom_psql":
        from .custom_psql import CustomPostgresWriteAdapter

        return CustomPostgresWriteAdapter(cfg["dsn_env"])
    if name == "app_be_dynatrace":
        from .app_be_dynatrace import AppBeDynatraceWriteAdapter

        return AppBeDynatraceWriteAdapter(
            os.environ.get(cfg["tenant_url_env"], "").strip(),
            os.environ.get(cfg["token_env"], "").strip(),
        )
    if name == "custom_dynatrace":
        from .custom_dynatrace import CustomDynatraceWriteAdapter

        return CustomDynatraceWriteAdapter(
            os.environ.get(cfg["tenant_url_env"], "").strip(),
            os.environ.get(cfg["token_env"], "").strip(),
        )
    raise RuntimeError(f"unknown adapter {name!r}")


__all__ = ["WriteAdapter", "build_write_adapters"]
