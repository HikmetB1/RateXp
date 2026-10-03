"""Have the agent really do a task, in a throwaway workspace, and rate it.

Two kinds of run share one loop: a skill run gets the skill's own text through
``load_skill`` and rates the skill; a session run gets a plain coding task and
rates the session as a whole. Both work through list/read/write tools over a
temporary directory, so a run leaves behind the kind of trajectory a real coding
session would. Each has to finish with a ``Rating``: that structured verdict is
what core stores as feedback. A run that spends its whole turn budget, or stops
without one, is asked once more to rate, so every run ends with a verdict.

Every model call re-sends the whole conversation, so old file reads and writes are
what burn tokens and trip Azure's per-minute rate limit. Past a size threshold all
but the latest few are blanked in the copy sent to the model; the conversation the
run returns, and core stores, keeps them in full.

The workspace is deleted when the run ends, pass or fail. Every path the model
gives is treated as relative to it and anything escaping it is refused, so a
confused agent cannot touch the rest of the filesystem.
"""

from __future__ import annotations

import copy
import logging
import random
import shutil
import tempfile
from pathlib import Path

from api.record_schemas import Rating
from langchain.agents import create_agent
from langchain.agents.middleware import (
    ClearToolUsesEdit,
    ContextEditingMiddleware,
    ModelCallLimitMiddleware,
)
from langchain.tools import tool
from langchain_core.messages import HumanMessage
from langchain_core.messages.utils import count_tokens_approximately
from load_config import (
    CRITICAL_PROMPT,
    CRITICAL_RATIO,
    MAX_ROUNDS,
    SESSION_SYSTEM_PROMPT,
    SESSION_TASK_PROMPT,
    SYSTEM_PROMPT,
    TASK_PROMPT,
)
from modules.agent.open_chat_model import open_chat_model

logger = logging.getLogger(__name__)

_MAX_READ_CHARS = 4000
# Above ~6k tokens of conversation, blank every file read and write but the latest
# four. load_skill is never blanked: its result is the skill the agent is following.
_TRIM_OLD_TOOL_USES = ClearToolUsesEdit(
    trigger=6000, keep=4, clear_tool_inputs=True, exclude_tools=("load_skill",)
)
_RATE_NOW = (
    "Your turn budget is used up. Stop working now and give your assessment: an honest "
    "score (1 = good, 2 = bad) and a short, specific comment."
)


def run_skill_task(skill: dict) -> tuple[Rating | None, list]:
    """Use one skill on a small task and rate the skill. See ``_run_to_rating``."""
    prompt_fields = {"name": skill["name"], "max_rounds": MAX_ROUNDS}
    return _run_to_rating(
        SYSTEM_PROMPT.format(**prompt_fields),
        TASK_PROMPT.format(**prompt_fields),
        skill,
    )


def run_session_task(task: str) -> tuple[Rating | None, list]:
    """Do one plain coding task, no skill, and rate the session. See ``_run_to_rating``."""
    prompt_fields = {"task": task, "max_rounds": MAX_ROUNDS}
    return _run_to_rating(
        SESSION_SYSTEM_PROMPT.format(**prompt_fields),
        SESSION_TASK_PROMPT.format(**prompt_fields),
        None,
    )


def _run_to_rating(system_prompt: str, task: str, skill: dict | None) -> tuple[Rating | None, list]:
    """Run the agent to a verdict in a fresh workspace.

    Returns ``(rating, messages)``; ``rating`` is None only when even the forced
    final call failed, and ``messages`` is the full LangChain conversation either way
    (see modules/submit/build_trajectory.py, which turns it into ATIF).
    """
    workspace = Path(tempfile.mkdtemp(prefix="ratexp-seed-"))
    model = open_chat_model()
    agent = create_agent(
        model=model,
        tools=_workspace_tools(workspace, skill),
        system_prompt=system_prompt,
        response_format=Rating,
        middleware=[
            ContextEditingMiddleware(edits=[_TRIM_OLD_TOOL_USES]),
            # Out of turns ends the loop cleanly, so the forced rating below still runs.
            ModelCallLimitMiddleware(run_limit=MAX_ROUNDS, exit_behavior="end"),
        ],
    )
    # On a `critical_ratio` share of runs the agent reviews as a tough customer, so
    # bad ratings keep flowing instead of an unbroken stream of praise.
    if random.random() < CRITICAL_RATIO:
        task += "\n\n" + CRITICAL_PROMPT
    try:
        # The call limit above is what ends a long run. Each round is several graph
        # steps (middleware, model, tools), so this cap is only a backstop well past it.
        state = agent.invoke(
            {"messages": [{"role": "user", "content": task}]},
            {"recursion_limit": 6 * MAX_ROUNDS + 10},
        )
    finally:
        shutil.rmtree(workspace, ignore_errors=True)
    rating, messages = state.get("structured_response"), state["messages"]
    if rating is None:
        return _force_rating(model, messages)
    return rating, messages


def _force_rating(model, messages: list) -> tuple[Rating | None, list]:
    """Ask once more, outside the agent loop, for the rating it never gave.

    The ask and the answer are appended so the stored transcript shows how the run
    ended. A failure here is logged, not raised: the transcript is still worth sending.
    """
    ask = HumanMessage(_RATE_NOW)
    trimmed = copy.deepcopy([*messages, ask])
    _TRIM_OLD_TOOL_USES.apply(trimmed, count_tokens=count_tokens_approximately)
    try:
        answer = model.with_structured_output(Rating, include_raw=True).invoke(trimmed)
    except Exception as exc:  # noqa: BLE001 - a 429 here must not lose the transcript
        logger.warning("forced final rating failed: %s", exc)
        return None, messages
    return answer["parsed"], [*messages, ask, answer["raw"]]


def _workspace_tools(workspace: Path, skill: dict | None) -> list:
    """The tools one run gets, closed over its own workspace: three file tools, plus
    ``load_skill`` when the run has a skill."""

    def _resolve(path: str) -> Path | None:
        # Any path is relative to the workspace (so a leading "/" is harmless); only a
        # real ".." escape is refused, and as None so the tool can warn rather than crash.
        target = (workspace / path.lstrip("/")).resolve()
        return target if target.is_relative_to(workspace) else None

    @tool
    def load_skill() -> str:
        """Load this skill's full instructions (its SKILL.md)."""
        return skill["prompt"]

    @tool
    def list_files(path: str = ".") -> str:
        """List the files in your scratch workspace."""
        base = _resolve(path)
        if base is None:
            return "Path must stay inside the workspace; use a relative path."
        names = [
            p.relative_to(workspace).as_posix() + ("/" if p.is_dir() else "")
            for p in sorted(base.rglob("*"))
        ]
        return "\n".join(names) or "(empty)"

    @tool
    def read_file(path: str) -> str:
        """Read a file from your scratch workspace."""
        target = _resolve(path)
        if target is None:
            return "Path must stay inside the workspace; use a relative path."
        return target.read_text()[:_MAX_READ_CHARS] if target.is_file() else f"No such file: {path}"

    @tool
    def write_file(path: str, content: str) -> str:
        """Create or overwrite a file in your scratch workspace."""
        target = _resolve(path)
        if target is None:
            return "Path must stay inside the workspace; use a relative path."
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
        return f"wrote {path} ({len(content)} bytes)"

    file_tools = [list_files, read_file, write_file]
    return [load_skill, *file_tools] if skill else file_tools
