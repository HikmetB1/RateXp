"""Label a rating, and again its shared conversation, with one value per label group.

``label_rating`` hands a cheap Azure OpenAI model what is known about a rating: its score,
skill and eval, its comment (PII-masked first) and, once the user shares it, a trimmed
digest of the already-masked conversation. A strict JSON schema holds the answer to one
value per group of config.yaml ``labeling.groups``, or NO_LABEL when the input does not
tell; a group that splits its values into ``when_good`` and ``when_bad`` offers a good
rating only the first and a bad rating only the second. Fail-open, unlike redaction: a
label only groups ratings, so a missing endpoint, a slow or failing model, a failed mask
or an off-list answer leaves the labels empty and the record is stored without them. The
model is reached with core's Managed Identity (or a developer's az login) - no key.
"""

from __future__ import annotations

import json
import logging
import urllib.request

from load_config import (
    LABEL_GROUPS,
    LABELING_API_VERSION,
    LABELING_DEPLOYMENT,
    LABELING_ENABLED,
    LABELING_ENDPOINT,
    LABELING_MAX_INPUT_CHARS,
    LABELING_TIMEOUT_SECONDS,
    NO_LABEL,
)
from modules.redaction.redact_trajectory import redact_text

logger = logging.getLogger(__name__)

_INSTRUCTIONS = (
    "You label a user's rating of an AI agent's work, so ratings can be grouped later. "
    "You get the rating (good, bad or none), what was rated, the user's comment and, when "
    "the user shared it, the conversation. Pick one value per field from its list, or "
    f'"{NO_LABEL}" when the input does not tell. With no comment, judge from the '
    "conversation and the rating. The fields:"
)
_SCORE_WORDS = {1: "good", 2: "bad"}
# Per comment, message and tool call, so one huge paste can't crowd out the rest.
_COMMENT_CHARS = 4000
_MESSAGE_CHARS = 2000
_ARGUMENT_CHARS = 500

# Built on first use, so core imports without azure-identity while labeling is off.
_token_provider = None


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


def describe_groups(score: int | None) -> str:
    """Each group with what it means and the values a rating with `score` may get."""
    lines: list[str] = []
    for name, group in LABEL_GROUPS.items():
        lines.append(f"- {name}: {group.means}")
        for value in group.values_for(score):
            description = group.values[value]
            lines.append(f"  - {value}: {description}" if description else f"  - {value}")
    return "\n".join(lines)


def _bearer_token() -> str:
    global _token_provider
    if _token_provider is None:
        from azure.identity import DefaultAzureCredential, get_bearer_token_provider

        # The provider caches the token and refreshes it before it expires.
        _token_provider = get_bearer_token_provider(
            DefaultAzureCredential(), "https://cognitiveservices.azure.com/.default"
        )
    return _token_provider()


def _ask_model(score: int | None, prompt: str) -> dict:
    """The model's answer as a dict, one key per group. Raises on any failure."""
    allowed = {name: group.values_for(score) for name, group in LABEL_GROUPS.items()}
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": list(allowed),
        "properties": {
            name: {"type": "string", "enum": [*values, NO_LABEL]}
            for name, values in allowed.items()
        },
    }
    body = {
        "messages": [
            {"role": "system", "content": f"{_INSTRUCTIONS}\n{describe_groups(score)}"},
            {"role": "user", "content": prompt},
        ],
        # Picking a few words needs no long thinking; minimal keeps it fast and cheap.
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
    answer = json.loads(completion["choices"][0]["message"]["content"])
    # The schema already holds the model to the lists; this catches it if it didn't.
    if any(answer.get(name) not in [*values, NO_LABEL] for name, values in allowed.items()):
        raise ValueError(f"answer is off the lists: {answer}")
    return answer


def label_rating(
    *,
    score: int | None,
    comment: str | None,
    skill_name: str | None,
    eval_name: str | None,
    atif: dict | None = None,
) -> dict[str, str]:
    """The value of each group the model could tell, as {group: value}; {} when labeling
    is off, has neither a comment nor a conversation to read, or fails. Costs one model
    call, plus masking the comment, of up to LABELING_TIMEOUT_SECONDS.

    `atif` is the already-masked conversation, when the user shared it.
    """
    comment = (comment or "").strip()
    digest = digest_trajectory(atif, LABELING_MAX_INPUT_CHARS) if atif else ""
    if not (LABELING_ENABLED and LABELING_ENDPOINT) or not (comment or digest):
        return {}
    try:
        lines = [
            f"Rating: {_SCORE_WORDS.get(score, 'none')}",
            f"Rated: {f'the skill {skill_name}' if skill_name else 'the whole session'}",
            f"Eval: {eval_name or 'none'}",
            f"Comment: {redact_text(comment[:_COMMENT_CHARS]) if comment else 'none'}",
        ]
        if digest:
            lines.append(f"Conversation:\n{digest}")
        answer = _ask_model(score, "\n".join(lines))
    except Exception:  # noqa: BLE001 - fail-open: the record is stored without labels
        logger.warning("labeling failed; storing the record without labels", exc_info=True)
        return {}
    return {name: answer[name] for name in LABEL_GROUPS if answer[name] != NO_LABEL}
