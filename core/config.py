"""Loads runtime config from config.yaml.

A single place for tunables that should live outside code, resolved relative to
this file so the working directory doesn't matter (tests, uvicorn, Docker all
find it). Every key is required — there are no in-code fallbacks, so the yaml is
the single source of truth and a missing key fails loudly at startup.
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
MAX_BODY_BYTES: int = _require("max_body_bytes")
RATE_LIMIT_PER_MINUTE: int = _require("rate_limit_per_minute")
