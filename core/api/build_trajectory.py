"""Convert a coding agent's session transcript (.jsonl) into ATIF.

`jsonl_to_atif` picks the reader that matches the agent that produced the file.
Each agent writes its own shape, so there is one reader per agent and no shared
middle layer - the formats have too little in common to be worth one.

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
      "usage":{"input_tokens":...,"output_tokens":...,
               "cache_read_input_tokens":...,"cache_creation_input_tokens":...}},
      "timestamp":"..."}
  {"type":"user","message":{"role":"user","content":[
      {"type":"tool_result","tool_use_id":"...","content":"..."}]},"timestamp":"..."}

`content` is either a plain string or a list of typed blocks. Lines that are not
conversation messages (e.g. "summary" entries) are skipped. The converter is
permissive: unknown shapes degrade gracefully rather than raising.

Cursor writes one JSON object per line as well, but carries far less: the role
sits on the line itself instead of in a `type` field, user turns are wrapped in
`<user_query>` and prefixed with an inline `<timestamp>`, tool calls are usually
logged without their results, and there are no token counts anywhere in the file.
Its token totals are therefore zero because Cursor never recorded them - not
because nothing was spent.
"""

from __future__ import annotations

import json
import re

from load_config import SCHEMA_VERSION


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


SURVEY_MARK = "check all that apply or type a comment."
# Cursor's survey starts from a /ratexp command the user sent, so it reads as an
# ordinary user message. The /ratexp command ratexp-cursor.sh writes, and its stop
# hook's followup, open with this phrase; keep them in step.
CURSOR_SURVEY_MARK = "RateXp survey"
# The rest of the survey is worded by ratexp-cursor.sh as well: the consent question
# `ask` has the agent put to the user, and the result `report` prints. Keep in step.
CURSOR_SURVEY_MARKS = (
    CURSOR_SURVEY_MARK,
    "including messages and tool results, to",
    "RateXp: feedback",
)
# The agent calling ratexp-cursor.sh to ask and report is the survey at work.
_RATEXP_SCRIPT = "ratexp-cursor.sh"
# Cursor wraps user turns and stamps them inline rather than in a JSON field.
_CURSOR_TIMESTAMP = re.compile(r"<timestamp>([^<]*)</timestamp>")
_CURSOR_TAGS = re.compile(r"</?(?:user_query|timestamp)>")


# The /ratexp request as Claude Code logs it: the command's name, its expanded
# body, and the one line the agent is told to answer with.
CLAUDE_REQUEST_MARKS = ("<command-name>/ratexp", "RateXp target:", "Opening the RateXp survey.")


def _is_survey_turn(content) -> bool:
    """Exclude RateXp's request and questionnaire from the trajectory being rated."""
    text = content if isinstance(content, str) else json.dumps(content)
    return SURVEY_MARK in text or any(mark in text for mark in CLAUDE_REQUEST_MARKS)


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

        etype = entry.get("type")
        if etype == "system":
            # Claude Code's own notes inside the conversation, such as the summary
            # it writes when the user steps away. Its other record types are session
            # state rather than conversation - `mode`, `permission-mode`, `ai-title`,
            # `last-prompt`, `queue-operation`, `attachment` (internal tool-registry
            # deltas) - and `file-history-snapshot` carries whole file contents, so
            # including it would put untouched source into every upload.
            text = _text_from_content(entry.get("content"))
            if not text or _is_survey_turn(text):
                continue
            step = {"step_id": len(steps) + 1, "source": "system", "message": text}
            if entry.get("timestamp"):
                step["timestamp"] = entry["timestamp"]
            steps.append(step)
            continue

        msg = entry.get("message")
        if etype not in ("user", "assistant") or not isinstance(msg, dict):
            continue  # skip summaries, meta, and anything non-conversational

        content = msg.get("content")
        if _is_survey_turn(content):
            continue  # asking for the rating is not part of the run being rated

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
            # Claude reports cached context separately from fresh input. Sum all
            # input kinds so prompt_tokens reflects the tokens actually processed,
            # not just the uncached slice (which, with prompt caching, is tiny).
            prompt_tokens = (
                (usage.get("input_tokens") or 0)
                + (usage.get("cache_read_input_tokens") or 0)
                + (usage.get("cache_creation_input_tokens") or 0)
            )
            completion_tokens = usage.get("output_tokens") or 0
            if prompt_tokens or completion_tokens:
                step["metrics"] = {
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                }
                total_prompt += prompt_tokens
                total_completion += completion_tokens
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


def cursor_jsonl_to_atif(raw: str, *, session_id: str | None, agent: str | None) -> dict:
    """Build an ATIF trajectory dict from raw Cursor agent-transcript .jsonl text.

    Every step keeps what Cursor recorded for it: the text, any reasoning, the
    tool calls with their arguments, and a tool result wherever one was logged.
    Cursor records no token usage, so the totals stay zero.
    """
    harness, _, agent_model = (agent or "").partition(" ")
    model_name: str | None = agent_model or None
    steps: list[dict] = []

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

        # The role and the body each sit either on the line or one level down:
        # Cursor has shipped both shapes, and old transcripts stay on disk.
        msg = entry.get("message")
        msg = msg if isinstance(msg, dict) else {}
        role = entry.get("role") or msg.get("role")
        content = entry.get("content") if "content" in entry else msg.get("content")
        if role not in ("user", "assistant", "system"):
            continue
        if msg.get("model"):
            model_name = msg["model"]

        text = _text_from_content(content)
        stamp = _CURSOR_TIMESTAMP.search(text)
        text = _CURSOR_TAGS.sub("", text)
        if stamp:
            text = text.replace(stamp.group(1), "", 1)
        text = text.strip()
        # The survey is not part of the run being rated: the request that starts it,
        # the questions the agent asks - with AskQuestion or in plain text - and the
        # result it relays. Only an answer the user types freely stays in.
        if any(mark in json.dumps(content) for mark in CURSOR_SURVEY_MARKS):
            continue
        tool_calls = _tool_calls_from_content(content)
        # The agent running the RateXp script is the survey too, not the work.
        if any(_RATEXP_SCRIPT in json.dumps(call.get("arguments")) for call in tool_calls):
            continue
        reasoning = _reasoning_from_content(content)
        observation = _observation_from_content(content)
        if not (text or tool_calls or reasoning or observation):
            continue

        step: dict = {"step_id": len(steps) + 1}
        timestamp = stamp.group(1).strip() if stamp else entry.get("timestamp")
        if timestamp:
            step["timestamp"] = timestamp
        step["source"] = {"user": "user", "assistant": "agent"}.get(role, "system")
        if observation is not None and not text:
            step["source"] = "system"  # a tool result, not the user speaking
        if text:
            step["message"] = text
        if reasoning:
            step["reasoning_content"] = reasoning
        if tool_calls:
            step["tool_calls"] = tool_calls
        if observation is not None:
            step["observation"] = observation
        steps.append(step)

    return {
        "schema_version": SCHEMA_VERSION,
        "session_id": session_id,
        "agent": {"name": harness or "unknown", "model_name": model_name},
        "steps": steps,
        # Cursor writes no usage anywhere in the file, so these are zero rather
        # than unknown. Do not read them as a session that cost nothing.
        "final_metrics": {
            "total_prompt_tokens": 0,
            "total_completion_tokens": 0,
            "total_steps": len(steps),
        },
    }


def jsonl_to_atif(raw: str, *, session_id: str | None, agent: str | None) -> dict:
    """Convert a transcript using the reader for whichever agent wrote it."""
    harness, _, _ = (agent or "").partition(" ")
    if harness == "cursor":
        return cursor_jsonl_to_atif(raw, session_id=session_id, agent=agent)
    return claude_jsonl_to_atif(raw, session_id=session_id, agent=agent)
