"""Convert a Claude Code session transcript (.jsonl) into ATIF.

ATIF - the Agent Trajectory Interchange Format (Harbor) - is a JSON shape for a
whole agent conversation: an ordered list of `steps`, each from a `source`
("user", "agent", "system") carrying a `message`, optional `reasoning_content`,
`tool_calls`, and tool `observation`s.

Claude Code writes one JSON object per line. The shapes we care about:

  {"type":"user","message":{"role":"user","content":"hi"},"timestamp":"..."}
  {"type":"assistant","message":{"role":"assistant","model":"claude-...",
      "content":[{"type":"text","text":"..."},
                 {"type":"thinking","thinking":"..."},
                 {"type":"tool_use","id":"...","name":"Bash","input":{...}}],
      "usage":{"input_tokens":...,"output_tokens":...}},"timestamp":"..."}
  {"type":"user","message":{"role":"user","content":[
      {"type":"tool_result","tool_use_id":"...","content":"..."}]},"timestamp":"..."}

`content` is either a plain string or a list of typed blocks. Lines that are not
conversation messages (e.g. "summary" entries) are skipped. The converter is
permissive: unknown shapes degrade gracefully rather than raising.
"""

from __future__ import annotations

import json

from config import SCHEMA_VERSION


def stub_if_oversized(atif: dict, limit_bytes: int) -> dict:
    """Keep storage cheap: if the ATIF JSON is larger than `limit_bytes`, drop its
    bulky `steps` and return a light meta-only stub instead of the full trajectory.

    The stub keeps the small, useful facts - agent, model, and the token/step totals
    in `final_metrics` - and adds an `oversized` note carrying the original byte size
    and a short human message. It carries no conversation text, so it needs no PII
    redaction. Returns the original dict unchanged when it already fits.
    """
    size = len(json.dumps(atif).encode("utf-8"))
    if size <= limit_bytes:
        return atif
    return {
        "schema_version": atif.get("schema_version"),
        "session_id": atif.get("session_id"),
        "agent": atif.get("agent"),
        "steps": [],  # the trajectory itself is what made it too big - dropped
        "final_metrics": atif.get("final_metrics", {}),
        "oversized": {
            "byte_size": size,
            "limit_bytes": limit_bytes,
            "message": (
                f"Trajectory too large to store ({size // 1024} KB, over the "
                f"{limit_bytes // 1024} KB limit). The step-by-step conversation was "
                "dropped to keep things fast; token and step totals are kept."
            ),
        },
    }


def _text_from_content(content) -> str:
    """Flatten a message `content` (string or block list) to plain text."""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(str(block.get("text", "")))
    return "\n".join(p for p in parts if p)


def _reasoning_from_content(content) -> str:
    """Collect any `thinking` blocks into ATIF `reasoning_content`."""
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "thinking":
            parts.append(str(block.get("thinking", "")))
    return "\n".join(p for p in parts if p)


def _tool_calls_from_content(content) -> list[dict]:
    """Map Claude `tool_use` blocks to ATIF tool_calls."""
    if not isinstance(content, list):
        return []
    calls: list[dict] = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "tool_use":
            calls.append(
                {
                    "tool_call_id": block.get("id"),
                    "name": block.get("name"),
                    "arguments": block.get("input", {}),
                }
            )
    return calls


def _observation_from_content(content) -> str | None:
    """Extract `tool_result` payloads (carried on user-role lines) as text."""
    if not isinstance(content, list):
        return None
    parts: list[str] = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "tool_result":
            inner = block.get("content")
            parts.append(_text_from_content(inner) if isinstance(inner, list) else str(inner))
    return "\n".join(p for p in parts if p) or None


def _has_block(content, block_type: str) -> bool:
    return isinstance(content, list) and any(
        isinstance(b, dict) and b.get("type") == block_type for b in content
    )


def claude_jsonl_to_atif(raw: str, *, session_id: str | None, agent: str | None) -> dict:
    """Build an ATIF trajectory dict from raw Claude Code .jsonl text.

    `agent` is the RateXp runtime label, e.g. "claude-code claude-opus-4-8";
    its second token (if any) is used as a fallback model name. The per-turn
    model id recorded by Claude Code takes precedence when present.
    """
    harness, _, agent_model = (agent or "").partition(" ")
    model_name: str | None = agent_model or None

    steps: list[dict] = []
    total_prompt = 0
    total_completion = 0

    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(entry, dict):
            continue

        msg = entry.get("message")
        etype = entry.get("type")
        if etype not in ("user", "assistant") or not isinstance(msg, dict):
            continue  # skip summaries, meta, and anything non-conversational

        content = msg.get("content")
        timestamp = entry.get("timestamp")
        step: dict = {"step_id": len(steps) + 1}
        if timestamp:
            step["timestamp"] = timestamp

        if etype == "assistant":
            step["source"] = "agent"
            if msg.get("model"):
                model_name = msg["model"]
            text = _text_from_content(content)
            if text:
                step["message"] = text
            reasoning = _reasoning_from_content(content)
            if reasoning:
                step["reasoning_content"] = reasoning
            tool_calls = _tool_calls_from_content(content)
            if tool_calls:
                step["tool_calls"] = tool_calls
            usage = msg.get("usage") or {}
            prompt_tokens = usage.get("input_tokens")
            completion_tokens = usage.get("output_tokens")
            if prompt_tokens or completion_tokens:
                step["metrics"] = {
                    "prompt_tokens": prompt_tokens or 0,
                    "completion_tokens": completion_tokens or 0,
                }
                total_prompt += prompt_tokens or 0
                total_completion += completion_tokens or 0
            # An assistant turn with no text and no tool calls carries nothing.
            if "message" not in step and "tool_calls" not in step:
                continue
        else:  # user line - either a real user message or a tool result
            observation = _observation_from_content(content)
            if observation is not None and not _has_block(content, "text"):
                step["source"] = "system"
                step["observation"] = observation
            else:
                step["source"] = "user"
                step["message"] = _text_from_content(content)
                if observation is not None:
                    step["observation"] = observation

        steps.append(step)

    return {
        "schema_version": SCHEMA_VERSION,
        "session_id": session_id,
        "agent": {"name": harness or "unknown", "model_name": model_name},
        "steps": steps,
        "final_metrics": {
            "total_prompt_tokens": total_prompt,
            "total_completion_tokens": total_completion,
            "total_steps": len(steps),
        },
    }
