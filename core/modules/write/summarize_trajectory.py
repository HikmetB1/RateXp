"""The few numbers a dashboard wants from a trajectory, without opening its steps.

A stored ATIF carries the whole conversation. A dashboard tile wants how long it
ran, how many tools it called, what it cost and which model answered - and a
destination can chart an attribute, not a JSON body. The Dynatrace writer
(adapters/write_to_dynatrace.py) puts the result on the transcript record as ``ratexp.steps``,
``ratexp.tool_calls``, ``ratexp.prompt_tokens``, ``ratexp.cached_tokens``,
``ratexp.completion_tokens`` and ``ratexp.model``, dropping the None ones.
"""

from __future__ import annotations

import math

# Beyond this a count is no real run, and JSON readers stop holding integers exactly.
_LARGEST_COUNT = 2**53


def _number(value) -> int | float | None:
    """`value` when it is a count a destination can store, else None.

    The exact type, because a bool passes isinstance(value, int) but is never a count.
    The range, because JSON readers stop holding an integer exactly from 2**53, and NaN
    or infinity is no count - and a client posts the ATIF, so it may hold any of them.
    """
    if type(value) not in (int, float) or not math.isfinite(value):
        return None
    # `or 0`: -0.0 passes the range, and a count has no sign to keep.
    return (value or 0) if 0 <= value < _LARGEST_COUNT else None


def summarize_trajectory(atif: dict, agent: str) -> dict:
    """Steps, tool calls, token totals and model of one ATIF; None where unknown.

    A client-posted trajectory may lack any key or give it any type, so nothing
    here is assumed to be there or to be what ATIF says, and nothing raises. Prompt
    and completion totals both falsy means the agent recorded no usage (Cursor does
    not), not a free run, so every token count is None - the app shows "not
    recorded". ``cached_tokens`` counts the prompt tokens read from the prompt
    cache, which ``prompt_tokens`` already includes.
    """
    steps = atif.get("steps")
    final_metrics = atif.get("final_metrics")
    final_metrics = final_metrics if isinstance(final_metrics, dict) else {}
    if isinstance(steps, list) and steps:
        step_count = len(steps)
        tool_calls = sum(
            len(step["tool_calls"])
            for step in steps
            if isinstance(step, dict) and isinstance(step.get("tool_calls"), list)
        )
    else:
        # An oversized stub keeps its totals but has no steps left to count calls in.
        total_steps = final_metrics.get("total_steps")
        step_count = _number(total_steps) if type(total_steps) is int else None
        tool_calls = None
    prompt_tokens = _number(final_metrics.get("total_prompt_tokens")) or 0
    completion_tokens = _number(final_metrics.get("total_completion_tokens")) or 0
    cached_tokens = _number(final_metrics.get("total_cached_tokens"))
    if not prompt_tokens and not completion_tokens:
        prompt_tokens = completion_tokens = cached_tokens = None
    agent_info = atif.get("agent")
    model = agent_info.get("model_name") if isinstance(agent_info, dict) else None
    model = model if isinstance(model, str) else None
    # The hooks post the model as the agent label's second word, e.g. "cursor gpt-5".
    words = (agent or "").split()
    return {
        "steps": step_count,
        "tool_calls": tool_calls,
        "prompt_tokens": prompt_tokens,
        "cached_tokens": cached_tokens,
        "completion_tokens": completion_tokens,
        "model": model or (words[1] if len(words) > 1 else None),
    }
