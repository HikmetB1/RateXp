"""Loads runtime config from config.yaml. Self-contained per service.

Resolved relative to this file so the working directory doesn't matter. Every
key is required - no in-code fallbacks, so a missing key fails loudly at startup.
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml

_CONFIG_FILE = Path(__file__).resolve().parent / "config.yaml"
_config: dict = yaml.safe_load(_CONFIG_FILE.read_text(encoding="utf-8")) or {}


def _require(key: str):
    if key not in _config:
        raise RuntimeError(f"config.yaml is missing required key: {key!r}")
    return _config[key]


SCHEMA_VERSION: str = _require("schema_version")
LIST_VIEW_LIMIT: int = _require("list_view_limit")
LIST_MAX_LIMIT: int = _require("list_max_limit")
TOP_SKILLS_LIMIT: int = _require("top_skills_limit")
QUERY_ENABLED: bool = _require("query_enabled")
QUERY_TIMEOUT_MS: int = _require("query_timeout_ms")
QUERY_MAX_ROWS: int = _require("query_max_rows")
WS_ENABLED: bool = _require("ws_enabled")
WS_BROADCAST_INTERVAL_MS: int = _require("ws_broadcast_interval_ms")

# Dashboard read source (see read_adapters/) - the one source with enabled: true.
# Mirrors the write side's 4 names; single-select. RATEXP_READ_ADAPTER overrides which.
# Per-source values (DSN / query URL / token) are read at build time from the env vars
# named in config (dsn_env / query_url_env / token_env) - nothing env-specific here.
_READ_ADAPTERS_RAW = _require("read_adapters")
_READ_NAMES = ("app_be_psql", "custom_psql", "app_be_dynatrace", "custom_dynatrace")
_read_override = (os.getenv("RATEXP_READ_ADAPTER") or "").strip().lower()
_read_enabled = [n for n in _READ_NAMES if bool((_READ_ADAPTERS_RAW.get(n) or {}).get("enabled"))]
if not _read_override and len(_read_enabled) != 1:
    raise RuntimeError(
        f"read_adapters must have exactly one source with enabled: true, got {_read_enabled or 'none'}"
    )
READ_ADAPTER_PROVIDER: str = _read_override or _read_enabled[0]
READ_ADAPTERS: dict[str, dict] = {n: dict(_READ_ADAPTERS_RAW.get(n) or {}) for n in _READ_NAMES}
