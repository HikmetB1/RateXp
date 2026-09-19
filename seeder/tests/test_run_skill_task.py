"""One skill run: the scratch workspace the agent gets, and what a run returns.

No model is ever reached - `create_agent` is replaced with a stand-in that returns
a fixed final state.
"""

from __future__ import annotations

import pytest
from api.record_schemas import Rating
from modules.agent import run_skill_task as task_module
from modules.agent.run_skill_task import run_skill_task

_SKILL = {"name": "demo", "prompt": "the skill body"}


def _tools(workspace):
    """The four workspace tools, by name."""
    return {t.name: t for t in task_module._workspace_tools(workspace, _SKILL)}


def test_load_skill_hands_over_the_skill_body(tmp_path):
    assert _tools(tmp_path)["load_skill"].invoke({}) == "the skill body"


def test_write_then_read_round_trips_inside_the_workspace(tmp_path):
    tools = _tools(tmp_path)
    assert tools["write_file"].invoke({"path": "notes/plan.md", "content": "hello"}) == (
        "wrote notes/plan.md (5 bytes)"
    )
    assert tools["read_file"].invoke({"path": "notes/plan.md"}) == "hello"
    assert tools["list_files"].invoke({"path": "."}) == "notes/\nnotes/plan.md"


def test_an_absolute_path_is_treated_as_relative_to_the_workspace(tmp_path):
    tools = _tools(tmp_path)
    tools["write_file"].invoke({"path": "/etc/passwd", "content": "nope"})
    assert (tmp_path / "etc/passwd").read_text() == "nope"


def test_paths_escaping_the_workspace_are_refused(tmp_path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (tmp_path / "secret.txt").write_text("do not read me")
    tools = _tools(workspace)

    for name, args in (
        ("read_file", {"path": "../secret.txt"}),
        ("list_files", {"path": ".."}),
        ("write_file", {"path": "../escaped.txt", "content": "x"}),
    ):
        assert "must stay inside the workspace" in tools[name].invoke(args)
    assert not (tmp_path / "escaped.txt").exists()


def test_missing_files_are_reported_not_raised(tmp_path):
    assert _tools(tmp_path)["read_file"].invoke({"path": "gone.md"}) == "No such file: gone.md"
    assert _tools(tmp_path)["list_files"].invoke({"path": "."}) == "(empty)"


class _Agent:
    """Stand-in for a compiled langchain agent: records the call, returns a fixed state."""

    def __init__(self, state):
        self._state = state
        self.tasks: list[str] = []

    def invoke(self, inputs, config=None):
        self.tasks.append(inputs["messages"][0]["content"])
        if isinstance(self._state, Exception):
            raise self._state
        return self._state


def _stub_agent(monkeypatch, state) -> _Agent:
    agent = _Agent(state)
    monkeypatch.setattr(task_module, "open_chat_model", lambda: None)
    monkeypatch.setattr(task_module, "create_agent", lambda **kwargs: agent)
    monkeypatch.setattr(task_module, "CRITICAL_RATIO", 0)
    return agent


def test_a_run_returns_the_rating_and_the_conversation(monkeypatch):
    rating = Rating(score=1, comment="clear")
    _stub_agent(monkeypatch, {"messages": ["m"], "structured_response": rating})
    assert run_skill_task(_SKILL) == (rating, ["m"])


def test_a_run_the_agent_never_rated_still_returns_its_conversation(monkeypatch):
    _stub_agent(monkeypatch, {"messages": ["m"], "structured_response": None})
    assert run_skill_task(_SKILL) == (None, ["m"])


def test_the_tough_reviewer_stance_is_appended_only_when_it_applies(monkeypatch):
    agent = _stub_agent(monkeypatch, {"messages": [], "structured_response": None})
    monkeypatch.setattr(task_module, "CRITICAL_PROMPT", "BE TOUGH")

    run_skill_task(_SKILL)
    assert "BE TOUGH" not in agent.tasks[0]

    monkeypatch.setattr(task_module, "CRITICAL_RATIO", 1)  # always tough
    run_skill_task(_SKILL)
    assert agent.tasks[1].endswith("BE TOUGH")


def test_the_workspace_is_deleted_even_when_the_run_blows_up(monkeypatch, tmp_path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    monkeypatch.setattr(task_module.tempfile, "mkdtemp", lambda prefix=None: str(workspace))
    _stub_agent(monkeypatch, RuntimeError("model is down"))

    with pytest.raises(RuntimeError, match="model is down"):
        run_skill_task(_SKILL)
    assert not workspace.exists()
