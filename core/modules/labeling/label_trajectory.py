"""Label a consented trajectory with its business case, main language and task type.

``label_atif`` hands a trimmed digest of the already-masked conversation to a cheap
Azure OpenAI model; a strict JSON schema holds its answer to one word from each list
in config.yaml ``labeling.labels``. Fail-open, unlike redaction: a label only groups
trajectories, so a missing endpoint, a slow or failing model, or an off-list answer
leaves every label None and the trajectory is stored without them. The model is
reached with core's Managed Identity (or a developer's az login) - no key.
"""

from __future__ import annotations

import json
import logging
import urllib.request
from typing import NamedTuple

from load_config import (
    LABEL_GROUPS,
    LABELING_API_VERSION,
    LABELING_DEPLOYMENT,
    LABELING_ENABLED,
    LABELING_ENDPOINT,
    LABELING_MAX_INPUT_CHARS,
    LABELING_TIMEOUT_SECONDS,
    LABELS,
)

logger = logging.getLogger(__name__)

_INSTRUCTIONS = (
    "You label a coding agent's session so sessions can be grouped later. From the "
    "conversation below, pick one word per field: business_case is the technical area "
    "of the work, language the main programming language written or edited (none when "
    "no code was involved), task_type the conventional commit type that best fits the "
    "work. Pick other when nothing fits."
)
# Per message and per tool call, so one huge paste can't crowd out the rest.
_MESSAGE_CHARS = 2000
_ARGUMENT_CHARS = 500

# Built on first use, so core imports without azure-identity while labeling is off.
_token_provider = None


class Labels(NamedTuple):
    """One word per group, or None when the trajectory was not labeled."""

    business_case: str | None = None
    language: str | None = None
    task_type: str | None = None


def digest_trajectory(atif: dict, max_chars: int) -> str:
    """Who said what and which tools they called (with their files), cut to max_chars.

    Tool output is left out: it is the bulk of a trajectory, and the messages and the
    calls' arguments already show the language and the kind of change.
    """
    lines: list[str] = []
    steps = atif.get("steps")
    for step in steps if isinstance(steps, list) else []:
        if not isinstance(step, dict):
            continue
        message = step.get("message")
        if isinstance(message, str) and message.strip():
            lines.append(f"{step.get('source')}: {message.strip()[:_MESSAGE_CHARS]}")
        calls = step.get("tool_calls")
        for call in calls if isinstance(calls, list) else []:
            if isinstance(call, dict):
                arguments = json.dumps(call.get("arguments"), ensure_ascii=False)
                lines.append(f"tool {call.get('name')}: {arguments[:_ARGUMENT_CHARS]}")
    return "\n".join(lines)[:max_chars]


def _bearer_token() -> str:
    global _token_provider
    if _token_provider is None:
        from azure.identity import DefaultAzureCredential, get_bearer_token_provider

        # The provider caches the token and refreshes it before it expires.
        _token_provider = get_bearer_token_provider(
            DefaultAzureCredential(), "https://cognitiveservices.azure.com/.default"
        )
    return _token_provider()


def _ask_model(digest: str) -> dict:
    """The model's answer as a dict, one key per group. Raises on any failure."""
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": list(LABEL_GROUPS),
        "properties": {group: {"type": "string", "enum": LABELS[group]} for group in LABEL_GROUPS},
    }
    body = {
        "messages": [
            {"role": "system", "content": _INSTRUCTIONS},
            {"role": "user", "content": digest},
        ],
        # Picking three words needs no long thinking; minimal keeps it fast and cheap.
        "reasoning_effort": "minimal",
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "labels", "strict": True, "schema": schema},
        },
    }
    request = urllib.request.Request(
        f"{LABELING_ENDPOINT.rstrip('/')}/openai/deployments/{LABELING_DEPLOYMENT}"
        f"/chat/completions?api-version={LABELING_API_VERSION}",
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {_bearer_token()}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=LABELING_TIMEOUT_SECONDS) as response:
        completion = json.loads(response.read())
    return json.loads(completion["choices"][0]["message"]["content"])


def label_atif(atif: dict) -> Labels:
    """The trajectory's labels; all None when labeling is off, has nothing to read, or fails."""
    if not (LABELING_ENABLED and LABELING_ENDPOINT):
        return Labels()
    digest = digest_trajectory(atif, LABELING_MAX_INPUT_CHARS)
    if not digest:
        return Labels()
    try:
        answer = _ask_model(digest)
        labels = Labels(**{group: answer[group] for group in LABEL_GROUPS})
        # The schema already holds the model to the lists; this catches it if it didn't.
        if any(word not in LABELS[group] for group, word in labels._asdict().items()):
            raise ValueError(f"answer is off the lists: {answer}")
    except Exception:  # noqa: BLE001 - fail-open: the trajectory is stored without labels
        logger.warning("labeling failed; storing the trajectory without labels", exc_info=True)
        return Labels()
    return labels
