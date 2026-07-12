"""Build the dashboard's read source - the one with ``enabled: true`` in config.yaml
``read_adapters`` (mirrors the write side's 2×2, but single-select: exactly one on).

The four sources read back from the matching write destination: ``app_be_psql`` /
``custom_psql`` (PostgreSQL, SQL filter box) and ``app_be_dynatrace`` /
``custom_dynatrace`` (Dynatrace over DQL). ``RATEXP_READ_ADAPTER`` overrides which.
"""

from __future__ import annotations

import os

from .base import ReadAdapter


def get_read_adapter() -> ReadAdapter:
    from config import READ_ADAPTER_PROVIDER, READ_ADAPTERS

    name = READ_ADAPTER_PROVIDER
    cfg = READ_ADAPTERS.get(name) or {}
    if name == "app_be_psql":
        from .app_be_psql import AppBePostgresReadAdapter

        return AppBePostgresReadAdapter()
    if name == "custom_psql":
        from .custom_psql import CustomPostgresReadAdapter

        return CustomPostgresReadAdapter(cfg["dsn_env"])
    if name == "app_be_dynatrace":
        from .app_be_dynatrace import AppBeDynatraceReadAdapter

        return AppBeDynatraceReadAdapter(
            os.environ.get(cfg.get("query_url_env", ""), "").strip(),
            os.environ.get(cfg.get("token_env", ""), "").strip(),
        )
    if name == "custom_dynatrace":
        from .custom_dynatrace import CustomDynatraceReadAdapter

        return CustomDynatraceReadAdapter(
            os.environ.get(cfg.get("query_url_env", ""), "").strip(),
            os.environ.get(cfg.get("token_env", ""), "").strip(),
        )
    raise RuntimeError(
        f"unknown read adapter {name!r}; use app_be_psql / custom_psql / "
        "app_be_dynatrace / custom_dynatrace"
    )


__all__ = ["ReadAdapter", "get_read_adapter"]
