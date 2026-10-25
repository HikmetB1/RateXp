"""Build the dashboard's read source - the one with ``enabled: true`` in config.yaml
``read_adapters`` (mirrors the write side's 2×2, but single-select: exactly one on).

The five sources read back from the matching write destination: ``app_be_psql`` /
``custom_psql`` (PostgreSQL, SQL filter box), ``app_be_dynatrace`` /
``custom_dynatrace`` (Dynatrace over DQL), and ``phoenix`` (an Arize Phoenix
project, key:value filters).

Each adapter is imported only once chosen, so an unused source's dependencies never
have to load.
"""

from __future__ import annotations

import os

import load_config
from modules.read.adapters.read_adapter_interface import ReadAdapter


def open_read_source() -> ReadAdapter:
    """Open the one enabled read source. Caller owns it and must ``close()`` it."""
    # Read off the module at call time rather than binding at import, so a test can
    # point this at a different source.
    name = load_config.READ_ADAPTER_PROVIDER
    cfg = load_config.READ_ADAPTERS.get(name) or {}
    if name == "app_be_psql":
        from modules.read.adapters.read_from_app_be_psql import AppBePostgresReadAdapter

        return AppBePostgresReadAdapter()
    if name == "custom_psql":
        from modules.read.adapters.read_from_custom_psql import CustomPostgresReadAdapter

        return CustomPostgresReadAdapter(cfg["dsn_env"])
    if name == "app_be_dynatrace":
        from modules.read.adapters.read_from_app_be_dynatrace import AppBeDynatraceReadAdapter

        return AppBeDynatraceReadAdapter(
            os.environ.get(cfg.get("query_url_env", ""), "").strip(),
            os.environ.get(cfg.get("token_env", ""), "").strip(),
        )
    if name == "custom_dynatrace":
        from modules.read.adapters.read_from_custom_dynatrace import CustomDynatraceReadAdapter

        return CustomDynatraceReadAdapter(
            os.environ.get(cfg.get("query_url_env", ""), "").strip(),
            os.environ.get(cfg.get("token_env", ""), "").strip(),
        )
    if name == "phoenix":
        from modules.read.adapters.read_from_phoenix import PhoenixReadAdapter

        return PhoenixReadAdapter(
            os.environ.get(cfg.get("endpoint_env", ""), "").strip(),
            os.environ.get(cfg.get("api_key_env", ""), "").strip(),
            os.environ.get(cfg.get("project_env", ""), "").strip(),
        )
    raise RuntimeError(
        f"unknown read adapter {name!r}; use app_be_psql / custom_psql / "
        "app_be_dynatrace / custom_dynatrace / phoenix"
    )
