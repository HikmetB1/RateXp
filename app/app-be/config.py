"""Loads runtime config from config.yaml. Self-contained per service.

Resolved relative to this file so the working directory doesn't matter. Every
key is required — there are no in-code fallbacks, so the yaml is the single
source of truth and a missing key fails loudly at startup.
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


SCHEMA_VERSION: str = _require("schema_version")
LIST_VIEW_LIMIT: int = _require("list_view_limit")
LIST_MAX_LIMIT: int = _require("list_max_limit")
TOP_SKILLS_LIMIT: int = _require("top_skills_limit")
QUERY_ENABLED: bool = _require("query_enabled")
QUERY_TIMEOUT_MS: int = _require("query_timeout_ms")
QUERY_MAX_ROWS: int = _require("query_max_rows")
WS_ENABLED: bool = _require("ws_enabled")
WS_BROADCAST_INTERVAL_MS: int = _require("ws_broadcast_interval_ms")
