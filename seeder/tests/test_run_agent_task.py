"""One agent run, skill or session: the scratch workspace it gets, and what it returns.

No model is ever reached - `create_agent` is replaced with a stand-in that returns
a fixed final state, or the real agent loop runs against a scripted fake model.
"""

from __future__ import annotations

import itertools

import pytest
from api.record_schemas import Rating
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.messages.utils import count_tokens_approximately
from langchain_core.runnables import RunnableLambda
from modules.agent import run_agent_task as task_module
from modules.agent.run_agent_task import run_session_task, run_skill_task

_SKILL = {"name": "demo", "prompt": "the skill body"}


def _tools(workspace):
    """A skill run's four workspace tools, by name."""
    return {t.name: t for t in task_module._workspace_tools(workspace, _SKILL)}


def test_load_skill_hands_over_the_skill_body(tmp_path):
    assert _tools(tmp_path)["load_skill"].invoke({}) == "the skill body"


def test_a_session_run_gets_the_file_tools_but_no_skill(tmp_path):
    names = {t.name for t in task_module._workspace_tools(tmp_path, None)}
    assert names == {"list_files", "read_file", "write_file"}


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
        self.kwargs: dict = {}

    def invoke(self, inputs, config=None):
        self.tasks.append(inputs["messages"][0]["content"])
        if isinstance(self._state, Exception):
            raise self._state
        return self._state


def _stub_agent(monkeypatch, state) -> _Agent:
    agent = _Agent(state)
    monkeypatch.setattr(task_module, "open_chat_model", lambda: None)

    def create_agent(**kwargs):
        agent.kwargs = kwargs
        return agent

    monkeypatch.setattr(task_module, "create_agent", create_agent)
    monkeypatch.setattr(task_module, "CRITICAL_RATIO", 0)
    return agent


def test_a_run_returns_the_rating_and_the_conversation(monkeypatch):
    rating = Rating(score=1, comment="clear")
    _stub_agent(monkeypatch, {"messages": ["m"], "structured_response": rating})
    assert run_skill_task(_SKILL, "the speed") == (rating, ["m"])


def test_a_session_run_hands_the_task_over_without_load_skill(monkeypatch):
    rating = Rating(score=2, comment="slow")
    agent = _stub_agent(monkeypatch, {"messages": ["m"], "structured_response": rating})
    assert run_session_task("write a debounce helper", "the speed") == (rating, ["m"])
    assert "write a debounce helper" in agent.tasks[0]
    assert "load_skill" not in {t.name for t in agent.kwargs["tools"]}


def test_both_kinds_of_run_hand_the_comment_focus_over(monkeypatch):
    rating = Rating(score=1, comment="fast")
    agent = _stub_agent(monkeypatch, {"messages": [], "structured_response": rating})

    run_skill_task(_SKILL, "the tools")
    run_session_task("write a debounce helper", "the scope")
    assert "the tools" in agent.tasks[0]
    assert "the scope" in agent.tasks[1]


def test_a_run_that_ends_unrated_is_asked_once_more(monkeypatch):
    _stub_agent(monkeypatch, {"messages": [AIMessage("done")], "structured_response": None})
    model = _NeverStops()
    monkeypatch.setattr(task_module, "open_chat_model", lambda: model)

    rating, messages = run_skill_task(_SKILL, "the speed")
    assert rating == Rating(score=2, comment="ran out of turns")
    # The ask and the answer are kept, so the transcript shows how the run ended.
    assert [m.type for m in messages] == ["ai", "human", "ai"]


def test_a_failed_forced_rating_still_returns_the_conversation(monkeypatch):
    _stub_agent(monkeypatch, {"messages": [AIMessage("done")], "structured_response": None})
    model = _NeverStops(rating_error=RuntimeError("429"))
    monkeypatch.setattr(task_module, "open_chat_model", lambda: model)

    rating, messages = run_skill_task(_SKILL, "the speed")
    assert rating is None
    assert [m.content for m in messages] == ["done"]


class _NeverStops(GenericFakeChatModel):
    """A model that lists files forever and only rates when asked outside the loop."""

    rating_error: Exception | None = None

    def __init__(self, **kwargs):
        calls = (
            AIMessage("", tool_calls=[{"id": f"c{i}", "name": "list_files", "args": {}}])
            for i in itertools.count()
        )
        super().__init__(messages=calls, **kwargs)

    def bind_tools(self, tools, **kwargs):
        return self

    def with_structured_output(self, schema, include_raw=False, **kwargs):
        def answer(messages):
            if self.rating_error:
                raise self.rating_error
            return {
                "raw": AIMessage('{"score": 2}'),
                "parsed": Rating(score=2, comment="ran out of turns"),
                "parsing_error": None,
            }

        return RunnableLambda(answer)


def test_a_run_out_of_turns_ends_cleanly_and_is_still_rated(monkeypatch):
    # The real agent loop, no stand-in: only the model is fake.
    monkeypatch.setattr(task_module, "open_chat_model", lambda: _NeverStops())
    monkeypatch.setattr(task_module, "MAX_ROUNDS", 3)
    monkeypatch.setattr(task_module, "CRITICAL_RATIO", 0)

    rating, messages = run_skill_task(_SKILL, "the speed")
    assert rating == Rating(score=2, comment="ran out of turns")
    assert sum(1 for m in messages if m.type == "tool") == 3  # one tool result per turn
    assert messages[-2].content == task_module._RATE_NOW


def test_old_tool_uses_are_blanked_but_the_skill_is_kept():
    messages = [AIMessage("", tool_calls=[{"id": "s", "name": "load_skill", "args": {}}])]
    messages.append(ToolMessage("the skill " * 3000, tool_call_id="s", name="load_skill"))
    for i in range(6):
        messages.append(
            AIMessage(
                "",
                tool_calls=[{"id": f"w{i}", "name": "write_file", "args": {"content": "x" * 4000}}],
            )
        )
        messages.append(ToolMessage("wrote", tool_call_id=f"w{i}", name="write_file"))

    task_module._TRIM_OLD_TOOL_USES.apply(messages, count_tokens=count_tokens_approximately)
    results = [m for m in messages if m.type == "tool"]
    assert results[0].content.startswith("the skill")
    assert [r.content for r in results[1:]] == ["[cleared]"] * 2 + ["wrote"] * 4


def test_the_tough_reviewer_stance_is_appended_only_when_it_applies(monkeypatch):
    agent = _stub_agent(monkeypatch, {"messages": [], "structured_response": None})
    monkeypatch.setattr(task_module, "CRITICAL_PROMPT", "BE TOUGH")

    run_skill_task(_SKILL, "the speed")
    assert "BE TOUGH" not in agent.tasks[0]

    monkeypatch.setattr(task_module, "CRITICAL_RATIO", 1)  # always tough
    run_skill_task(_SKILL, "the speed")
    assert agent.tasks[1].endswith("BE TOUGH")


def test_the_workspace_is_deleted_even_when_the_run_blows_up(monkeypatch, tmp_path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    monkeypatch.setattr(task_module.tempfile, "mkdtemp", lambda prefix=None: str(workspace))
    _stub_agent(monkeypatch, RuntimeError("model is down"))

    with pytest.raises(RuntimeError, match="model is down"):
        run_skill_task(_SKILL, "the speed")
    assert not workspace.exists()
