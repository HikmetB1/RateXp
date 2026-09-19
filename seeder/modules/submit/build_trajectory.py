"""Convert a LangChain conversation into ATIF - the same trajectory shape core
stores for a real Claude Code session (see core/api/build_trajectory.py).

Message types map across as human/ai/tool -> user/agent/system. A turn that says
nothing and calls nothing is dropped. Per-turn token usage is kept on agent steps
and totalled into ``final_metrics``.

On an ``oversized_ratio`` share of runs the body is padded past core's
``max_transcript_bytes`` on purpose, so the "too large -> store a meta-only stub"
path gets exercised end to end. The totals still describe the real run; only the
last step is synthetic bulk.
"""

from __future__ import annotations

import random
import uuid
from typing import TYPE_CHECKING

from load_config import OVERSIZED_RATIO, SCHEMA_VERSION
from modules.agent.open_chat_model import FRAMEWORK, model_name

if TYPE_CHECKING:
    from api.record_schemas import SeededRun

_SOURCE = {"human": "user", "ai": "agent", "tool": "system"}
_MAX_OBSERVATION_CHARS = 1000
# Enough filler to push any ATIF body past core's max_transcript_bytes (256 KiB).
_OVERSIZED_PAD_BYTES = 300_000


def messages_to_atif(run: SeededRun, messages: list) -> dict:
    """Build one complete ATIF trajectory dict. Touches nothing outside this process."""
    steps = _steps(messages)
    total_steps = len(steps)
    prompt_tokens = sum(s["metrics"]["prompt_tokens"] for s in steps if "metrics" in s)
    completion_tokens = sum(s["metrics"]["completion_tokens"] for s in steps if "metrics" in s)
    if random.random() < OVERSIZED_RATIO:
        steps.append(
            {
                "step_id": len(steps) + 1,
                "source": "system",
                "observation": "synthetic oversized-trajectory padding\n"
                + "x" * _OVERSIZED_PAD_BYTES,
            }
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "session_id": run.session_id,
        "agent": {"name": FRAMEWORK, "model_name": model_name()},
        "steps": steps,
        "final_metrics": {
            "total_prompt_tokens": prompt_tokens,
            "total_completion_tokens": completion_tokens,
            "total_steps": total_steps,
        },
    }


def _steps(messages: list) -> list[dict]:
    """LangChain messages -> ATIF steps, numbered from 1 in conversation order."""
    steps: list[dict] = []
    for msg in messages:
        source = _SOURCE.get(getattr(msg, "type", None))
        if not source:
            continue
        step = {"step_id": len(steps) + 1, "source": source}
        text = _text(msg.content)
        if source == "system":
            step["observation"] = text[:_MAX_OBSERVATION_CHARS]
        elif text:
            step["message"] = text
        calls = [
            {
                "tool_call_id": c.get("id") or str(uuid.uuid4()),
                "name": c.get("name"),
                "arguments": c.get("args", {}),
            }
            for c in getattr(msg, "tool_calls", None) or []
        ]
        if calls:
            step["tool_calls"] = calls
        if len(step) == 2:
            continue  # nothing but step_id and source: no message, observation or calls
        usage = getattr(msg, "usage_metadata", None) or {}
        if source == "agent" and (usage.get("input_tokens") or usage.get("output_tokens")):
            step["metrics"] = {
                "prompt_tokens": usage.get("input_tokens") or 0,
                "completion_tokens": usage.get("output_tokens") or 0,
            }
        steps.append(step)
    return steps


def _text(content) -> str:
    """One message's text, whether it arrived as a string or a list of content blocks."""
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content if isinstance(b, dict))
    return str(content or "")
