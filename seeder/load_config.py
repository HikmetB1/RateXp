"""Loads runtime config from config.yaml.

Resolved relative to this file so the working directory doesn't matter. Every
key is required - no in-code fallbacks, so a missing key fails loudly at startup.

Model credentials are not config and never live in config.yaml: they sit in .env
beside this file (see .env.example). Loading them here means every entry point
has them, whether a run starts from function_app.py or api/run_continuously.py.
Real environment variables win, which is how the deployed function and compose
pass theirs.
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

_HERE = Path(__file__).resolve().parent
_CONFIG_FILE = _HERE / "config.yaml"
_config: dict = yaml.safe_load(_CONFIG_FILE.read_text(encoding="utf-8")) or {}

load_dotenv(_HERE / ".env")


def _require(key: str):
    if key not in _config:
        raise RuntimeError(f"config.yaml is missing required key: {key!r}")
    return _config[key]


SCHEMA_VERSION: str = _require("schema_version")

# MODEL and RATEXP_CORE_URL override config.yaml so a deployment can point the
# seeder at another model or another core without editing the file - Terraform
# sets both on the Function App, compose sets the core URL.
MODEL: str = os.environ.get("MODEL") or str(_require("model"))
CORE_URL: str = (os.environ.get("RATEXP_CORE_URL") or str(_require("core_url"))).rstrip("/")
EVAL_NAME: str = str(_require("eval_name"))

TEMPERATURE: float = float(_require("temperature"))
MAX_ROUNDS: int = int(_require("max_rounds"))
if MAX_ROUNDS < 1:
    raise RuntimeError(f"max_rounds must be >= 1, got {MAX_ROUNDS}")
INTERVAL_SECONDS: int = int(_require("interval_seconds"))

CRITICAL_RATIO: float = float(_require("critical_ratio"))
OVERSIZED_RATIO: float = float(_require("oversized_ratio"))
for _name, _ratio in (("critical_ratio", CRITICAL_RATIO), ("oversized_ratio", OVERSIZED_RATIO)):
    if not 0 <= _ratio <= 1:
        raise RuntimeError(f"{_name} must be between 0 and 1, got {_ratio}")

# The agent's instructions. {name} is the skill for this run, {max_rounds} its turn budget.
SYSTEM_PROMPT: str = str(_require("system_prompt"))
TASK_PROMPT: str = str(_require("task_prompt"))
CRITICAL_PROMPT: str = str(_require("critical_prompt"))
