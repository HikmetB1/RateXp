"""Have the agent really use one skill, in a throwaway workspace, and rate it.

The agent gets the skill's own text through ``load_skill`` plus list/read/write
tools over a temporary directory, so a run leaves behind the kind of trajectory a
real coding session would. It has to finish with a ``Rating``: that structured
verdict is what core stores as feedback.

The workspace is deleted when the run ends, pass or fail. Every path the model
gives is treated as relative to it and anything escaping it is refused, so a
confused agent cannot touch the rest of the filesystem.
"""

from __future__ import annotations

import random
import shutil
import tempfile
from pathlib import Path

from api.record_schemas import Rating
from langchain.agents import create_agent
from langchain.tools import tool
from load_config import CRITICAL_PROMPT, CRITICAL_RATIO, MAX_ROUNDS, SYSTEM_PROMPT, TASK_PROMPT
from modules.agent.open_chat_model import open_chat_model

_MAX_READ_CHARS = 4000


def run_skill_task(skill: dict) -> tuple[Rating | None, list]:
    """Run one skill to a verdict.

    Returns ``(rating, messages)``; ``rating`` is None when the agent ended its turn
    without one, and ``messages`` is the full LangChain conversation either way (see
    modules/submit/build_trajectory.py, which turns it into ATIF).
    """
    workspace = Path(tempfile.mkdtemp(prefix="ratexp-skill-"))
    prompt_fields = {"name": skill["name"], "max_rounds": MAX_ROUNDS}
    agent = create_agent(
        model=open_chat_model(),
        tools=_workspace_tools(workspace, skill),
        system_prompt=SYSTEM_PROMPT.format(**prompt_fields),
        response_format=Rating,
    )
    task = TASK_PROMPT.format(**prompt_fields)
    # On a `critical_ratio` share of runs the agent reviews as a tough customer, so
    # bad ratings keep flowing instead of an unbroken stream of praise.
    if random.random() < CRITICAL_RATIO:
        task += "\n\n" + CRITICAL_PROMPT
    try:
        # langgraph counts ~2 steps per round (think + act); cap the loop accordingly.
        state = agent.invoke(
            {"messages": [{"role": "user", "content": task}]},
            {"recursion_limit": 2 * MAX_ROUNDS + 1},
        )
    finally:
        shutil.rmtree(workspace, ignore_errors=True)
    return state.get("structured_response"), state["messages"]


def _workspace_tools(workspace: Path, skill: dict) -> list:
    """The four tools one run gets, closed over its own workspace and skill."""

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

    return [load_skill, list_files, read_file, write_file]
