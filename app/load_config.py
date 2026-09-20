"""Loads runtime config from config.yaml.

Resolved relative to this file so the working directory doesn't matter. Every
key is required - no in-code fallbacks, so a missing key fails loudly at startup.
"""

from __future__ import annotations

from pathlib import Path

import yaml

_CONFIG_FILE = Path(__file__).resolve().parent / "config.yaml"
_config: dict = yaml.safe_load(_CONFIG_FILE.read_text(encoding="utf-8")) or {}


def _require(key: str):
    if key not in _config:
        raise RuntimeError(f"config.yaml is missing required key: {key!r}")
    return _config[key]


def _require_in(parent: dict, parent_name: str, key: str):
    if not isinstance(parent, dict) or key not in parent:
        raise RuntimeError(f"config.yaml is missing required key: {parent_name}.{key!r}")
    return parent[key]


SCHEMA_VERSION: str = _require("schema_version")
LIST_VIEW_LIMIT: int = _require("list_view_limit")
LIST_MAX_LIMIT: int = _require("list_max_limit")
TOP_SKILLS_LIMIT: int = _require("top_skills_limit")
QUERY_ENABLED: bool = _require("query_enabled")
QUERY_TIMEOUT_MS: int = _require("query_timeout_ms")
QUERY_MAX_ROWS: int = _require("query_max_rows")
WS_ENABLED: bool = _require("ws_enabled")
WS_BROADCAST_INTERVAL_MS: int = _require("ws_broadcast_interval_ms")

# Read sources (see modules/read/). Mirrors the write side's names minus bluebox, which
# has no query language. Each must be present with an `enabled` flag, and unlike the write
# side exactly one may be true - that one is what the dashboard reads. Per-source values
# (a DSN, a URL, a token, a key) come from the env vars named here, so nothing
# env-specific lives in config.yaml.
_READ_ADAPTERS_RAW = _require("read_adapters")
_READ_ADAPTER_NAMES = (
    "app_be_psql",
    "custom_psql",
    "app_be_dynatrace",
    "custom_dynatrace",
    "phoenix",
)
READ_ADAPTERS: dict[str, dict] = {}
for _name in _READ_ADAPTER_NAMES:
    _cfg = _require_in(_READ_ADAPTERS_RAW, "read_adapters", _name)
    if not isinstance(_cfg, dict) or "enabled" not in _cfg:
        raise RuntimeError(
            f"config.yaml read_adapters.{_name} must be a mapping with an 'enabled' key"
        )
    READ_ADAPTERS[_name] = dict(_cfg)

_read_enabled = [n for n in _READ_ADAPTER_NAMES if bool(READ_ADAPTERS[n]["enabled"])]
if len(_read_enabled) != 1:
    raise RuntimeError(
        f"read_adapters must have exactly one source with enabled: true, got {_read_enabled or 'none'}"
    )
READ_ADAPTER_PROVIDER: str = _read_enabled[0]
