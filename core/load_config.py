"""Loads runtime config from config.yaml, and the evals from evals/.

Resolved relative to this file so the working directory doesn't matter. Every
key is required - no in-code fallbacks, so a missing key fails loudly at startup.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import NamedTuple

import yaml

_HERE = Path(__file__).resolve().parent
_CONFIG_FILE = _HERE / "config.yaml"
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
MAX_BODY_BYTES: int = _require("max_body_bytes")
MAX_TRANSCRIPT_BYTES: int = _require("max_transcript_bytes")
RATE_LIMIT_PER_MINUTE: int = _require("rate_limit_per_minute")
DEFAULT_SURVEY_EVERY: int = _require("default_survey_every")
if DEFAULT_SURVEY_EVERY < 1:
    raise RuntimeError(f"default_survey_every must be >= 1, got {DEFAULT_SURVEY_EVERY}")


class Eval(NamedTuple):
    """One survey: its question, and the label and description of each answer.

    The hooks read these fields in this order, right after the eval's name (see
    api/serve_http.py), so a field is added or moved only together with them.
    """

    question: str
    good_label: str
    good_description: str
    bad_label: str
    bad_description: str


# What the user types after /ratexp to pick an eval, so one word.
_EVAL_NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")


def _eval_text(source: str, field: str, value, limit: int) -> str:
    """One piece of an eval's wording: a single line of text, at most `limit` long."""
    if not isinstance(value, str) or not value.strip():
        # YAML reads a bare yes, no, true or false as a boolean, and a leading { as a mapping.
        raise RuntimeError(
            f"{source}: {field} must be text - quote a yes, no, true, false or {{..."
        )
    if len(value) > limit or value != value.strip() or re.search(r"[\x00-\x1f\x7f]", value):
        raise RuntimeError(f"{source}: {field} must be one line of at most {limit} characters")
    return value


def load_evals(folder: Path) -> dict[str, Eval]:
    """Every eval in `folder`, by name: its file's name, which users type after /ratexp."""
    evals: dict[str, Eval] = {}
    for path in sorted(folder.glob("*.yaml")):
        source = f"evals/{path.name}"
        if not _EVAL_NAME.fullmatch(path.stem):
            raise RuntimeError(f"{source}: an eval's name is lowercase letters, digits and -")
        survey = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(survey, dict):
            raise RuntimeError(f"{source}: must hold a question, good and bad")
        question = _eval_text(source, "question", survey.get("question"), 300)
        answers: list[str] = []
        for answer in ("good", "bad"):
            given = survey.get(answer)
            if not isinstance(given, dict):
                raise RuntimeError(f"{source}: {answer} must hold a label and a description")
            label = _eval_text(source, f"{answer}.label", given.get("label"), 40)
            # Claude Code hands back the ticked labels joined by ", ", quoting any
            # label that holds a comma - a label with either could not be read back.
            if "," in label or '"' in label:
                raise RuntimeError(f"{source}: {answer}.label may not hold a comma or a quote")
            description = _eval_text(source, f"{answer}.description", given.get("description"), 200)
            answers += [label, description]
        if answers[0] == answers[2]:
            raise RuntimeError(f"{source}: good and bad need different labels")
        evals[path.stem] = Eval(question, *answers)
    if not evals:
        raise RuntimeError(f"{folder} holds no eval - add one as <name>.yaml")
    return evals


# The surveys a rating can answer, baked into the hooks core serves.
EVALS: dict[str, Eval] = load_evals(_HERE / "evals")
# The one asked every Nth turn, and on a /ratexp that names none.
DEFAULT_SURVEY_EVAL: str = _require("default_survey_eval")
if DEFAULT_SURVEY_EVAL not in EVALS:
    raise RuntimeError(
        f"default_survey_eval {DEFAULT_SURVEY_EVAL!r} is not in evals/ - pick one of {list(EVALS)}"
    )

# PII redaction config (see modules/redaction/).
_REDACTION: dict = _require("redaction")
REDACTION_ENABLED: bool = bool(_require_in(_REDACTION, "redaction", "enabled"))
# Which adapter handles redaction: "presidio" (self-hosted) or "azure" (AI Language).
# RATEXP_REDACTION_PROVIDER overrides config.yaml so a deployment can flip provider
# without a rebuild (both adapters' deps ship in the image).
_REDACTION_PROVIDER_ENV = os.getenv("RATEXP_REDACTION_PROVIDER")
REDACTION_PROVIDER: str = (
    (
        _REDACTION_PROVIDER_ENV
        if _REDACTION_PROVIDER_ENV is not None
        else str(_require_in(_REDACTION, "redaction", "provider"))
    )
    .strip()
    .lower()
)
if REDACTION_PROVIDER not in ("presidio", "azure"):
    raise RuntimeError(
        f"redaction provider must be 'presidio' or 'azure', got {REDACTION_PROVIDER!r}"
    )
# Azure AI Language endpoint - required only when provider is "azure".
REDACTION_ENDPOINT: str = str(_REDACTION.get("azure_endpoint") or "")
if REDACTION_ENABLED and REDACTION_PROVIDER == "azure" and not REDACTION_ENDPOINT:
    raise RuntimeError("redaction.provider is 'azure' but redaction.azure_endpoint is empty")
_REDACTION_LANGUAGES = _require_in(_REDACTION, "redaction", "languages")
if not isinstance(_REDACTION_LANGUAGES, list) or not _REDACTION_LANGUAGES:
    raise RuntimeError("config.yaml redaction.languages must be a non-empty list")
# Accepted PII languages; the first is the fallback when detection misses.
REDACTION_LANGUAGES: list[str] = [str(x) for x in _REDACTION_LANGUAGES]
REDACTION_LANGUAGE: str = REDACTION_LANGUAGES[0]

# Write adapters (see modules/write/). Each named
# destination must be present with an `enabled` flag; a submission is written to
# every one whose flag is true.
_WRITE_ADAPTERS_RAW = _require("write_adapters")
_WRITE_ADAPTER_NAMES = (
    "app_be_psql",
    "custom_psql",
    "app_be_dynatrace",
    "custom_dynatrace",
    "bluebox",
    "phoenix",
)
WRITE_ADAPTERS: dict[str, dict] = {}
for _name in _WRITE_ADAPTER_NAMES:
    _cfg = _require_in(_WRITE_ADAPTERS_RAW, "write_adapters", _name)
    if not isinstance(_cfg, dict) or "enabled" not in _cfg:
        raise RuntimeError(
            f"config.yaml write_adapters.{_name} must be a mapping with an 'enabled' key"
        )
    WRITE_ADAPTERS[_name] = dict(_cfg)
