"""Claude Code .jsonl to ATIF, and the size stub that keeps storage cheap."""

from __future__ import annotations

import json

from api.build_trajectory import claude_jsonl_to_atif, stub_if_oversized
from load_config import SCHEMA_VERSION

SESSION = "\n".join(
    json.dumps(line)
    for line in [
        {"type": "summary", "summary": "ignore me"},
        {
            "type": "user",
            "message": {"role": "user", "content": "hello"},
            "timestamp": "2026-05-31T10:00:00Z",
        },
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "model": "claude-opus-4-8",
                "content": [
                    {"type": "thinking", "thinking": "let me look"},
                    {"type": "text", "text": "running it"},
                    {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "ls"}},
                ],
                "usage": {"input_tokens": 12, "output_tokens": 5},
            },
            "timestamp": "2026-05-31T10:00:01Z",
        },
        {
            "type": "user",
            "message": {
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "a.txt"}],
            },
            "timestamp": "2026-05-31T10:00:02Z",
        },
        {
            "type": "assistant",
            "message": {"role": "assistant", "content": [{"type": "text", "text": "done"}]},
        },
    ]
)


def _steps(raw: str, agent: str = "claude-code") -> list[dict]:
    return claude_jsonl_to_atif(raw, session_id="s", agent=agent)["steps"]


def test_the_per_turn_model_id_wins_over_the_agent_label():
    trajectory = claude_jsonl_to_atif(
        SESSION, session_id="sess-1", agent="claude-code claude-sonnet-4-6"
    )
    assert trajectory["schema_version"] == SCHEMA_VERSION
    assert trajectory["session_id"] == "sess-1"
    # The label says sonnet, the session file says opus. The session file is the
    # record of what actually ran.
    assert trajectory["agent"] == {"name": "claude-code", "model_name": "claude-opus-4-8"}


def test_the_agent_label_supplies_the_model_when_the_session_file_has_none():
    raw = json.dumps({"type": "user", "message": {"role": "user", "content": "hi"}})
    trajectory = claude_jsonl_to_atif(raw, session_id="s", agent="claude-code claude-opus-4-8")
    assert trajectory["agent"] == {"name": "claude-code", "model_name": "claude-opus-4-8"}


def test_non_conversation_lines_are_dropped_and_step_ids_stay_sequential():
    steps = _steps(SESSION)
    assert [s["step_id"] for s in steps] == [1, 2, 3, 4]
    assert [s["source"] for s in steps] == ["user", "agent", "system", "agent"]


def test_a_user_line_keeps_its_text_as_the_message():
    assert _steps(SESSION)[0]["message"] == "hello"


def test_an_assistant_line_splits_into_message_reasoning_tool_calls_and_metrics():
    step = _steps(SESSION)[1]
    assert step["message"] == "running it"
    assert step["reasoning_content"] == "let me look"
    assert step["tool_calls"] == [
        {"tool_call_id": "t1", "name": "Bash", "arguments": {"command": "ls"}}
    ]
    assert step["metrics"] == {"prompt_tokens": 12, "completion_tokens": 5}


def test_a_tool_result_with_no_text_becomes_a_system_observation():
    step = _steps(SESSION)[2]
    assert step["source"] == "system"
    assert step["observation"] == "a.txt"


def test_final_metrics_total_the_steps_and_tokens():
    metrics = claude_jsonl_to_atif(SESSION, session_id="s", agent="x")["final_metrics"]
    assert metrics == {"total_prompt_tokens": 12, "total_completion_tokens": 5, "total_steps": 4}


def test_cached_context_counts_towards_prompt_tokens():
    # With prompt caching, input_tokens alone is a tiny slice of what the model
    # actually processed. Summing all three input kinds gives 7 + 100 + 20.
    raw = json.dumps(
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": "hi"}],
                "usage": {
                    "input_tokens": 7,
                    "output_tokens": 3,
                    "cache_read_input_tokens": 100,
                    "cache_creation_input_tokens": 20,
                },
            },
        }
    )
    assert _steps(raw)[0]["metrics"] == {"prompt_tokens": 127, "completion_tokens": 3}


def test_blank_and_unparsable_lines_are_ignored():
    raw = '\n  \nnot json\n{"type":"user","message":{"role":"user","content":"hi"}}\n'
    steps = _steps(raw)
    assert len(steps) == 1
    assert steps[0]["message"] == "hi"


def test_an_empty_session_file_yields_no_steps():
    trajectory = claude_jsonl_to_atif("", session_id="s", agent="x")
    assert trajectory["steps"] == []
    assert trajectory["final_metrics"]["total_steps"] == 0


# The three turns that ask for a rating (the instruction the hook hands the agent,
# the picker the agent draws, and the answer coming back) all land in the session
# file between the work and the consent. Rating the rating is not the point, so
# the conversion drops them.
PICKER = {
    "questions": [
        {
            "question": "Rate poem-creator, check all that apply or type a comment.",
            "header": "RateXp",
            "multiSelect": True,
            "options": [{"label": "Good", "description": "The result was helpful."}],
        }
    ]
}

SURVEY = "\n".join(
    json.dumps(line)
    for line in [
        {"type": "assistant", "message": {"role": "assistant", "content": "here is your poem"}},
        {
            "type": "user",
            "message": {
                "role": "user",
                "content": "Stop hook feedback:\nDraw this exact AskUserQuestion picker, "
                "without answers or extra fields.\n" + json.dumps(PICKER),
            },
        },
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "id": "t9", "name": "AskUserQuestion", "input": PICKER}
                ],
            },
        },
        {
            "type": "user",
            "message": {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "t9",
                        "content": 'Your questions have been answered: "Rate poem-creator, '
                        'check all that apply or type a comment."="Good".',
                    }
                ],
            },
        },
    ]
)


def test_the_rating_survey_is_not_part_of_the_trajectory_it_rates():
    steps = _steps(SURVEY)
    assert [s["source"] for s in steps] == ["agent"]
    assert steps[0]["message"] == "here is your poem"  # the work itself is kept
    blob = json.dumps(steps)
    assert "RateXp" not in blob
    assert "Draw this exact AskUserQuestion picker" not in blob


def test_a_skills_own_question_to_the_user_is_kept():
    # Only RateXp's survey goes. A skill asking the user something is real work.
    own = json.dumps(
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "t1",
                        "name": "AskUserQuestion",
                        "input": {
                            "questions": [
                                {"question": "Which mood?", "header": "Mood", "options": []}
                            ]
                        },
                    }
                ],
            },
        }
    )
    steps = _steps(own)
    assert len(steps) == 1
    assert steps[0]["tool_calls"][0]["name"] == "AskUserQuestion"


def test_a_trajectory_within_the_limit_is_returned_untouched():
    trajectory = claude_jsonl_to_atif(SESSION, session_id="s", agent="x")
    assert stub_if_oversized(trajectory, 1_000_000) is trajectory


def test_an_oversized_trajectory_keeps_only_its_totals():
    trajectory = claude_jsonl_to_atif(SESSION, session_id="s", agent="x")
    stub = stub_if_oversized(trajectory, 10)
    assert stub["steps"] == []  # the conversation is what made it too big
    assert stub["final_metrics"]["total_steps"] == 4  # the cheap facts survive
    assert stub["session_id"] == "s"
    assert stub["oversized"]["limit_bytes"] == 10
    assert stub["oversized"]["byte_size"] > 10
    # Nothing a user wrote is left, which is why the stub skips redaction.
    assert "hello" not in json.dumps(stub)
