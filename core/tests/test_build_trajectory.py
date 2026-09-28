"""A coding agent's .jsonl to ATIF, and the size stub that keeps storage cheap."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from api.build_trajectory import (
    CLAUDE_REQUEST_MARKS,
    CURSOR_SURVEY_MARKS,
    claude_jsonl_to_atif,
    cursor_jsonl_to_atif,
    jsonl_to_atif,
    stub_if_oversized,
)
from load_config import SCHEMA_VERSION

# Cursor's shape: the role sits on the line, user turns are wrapped and carry an
# inline timestamp, and no line holds a tool result or a token count.
CURSOR_SESSION = "\n".join(
    json.dumps(line)
    for line in [
        {
            "role": "user",
            "content": "<timestamp>2026-09-21T10:00:00Z</timestamp><user_query>fix the test</user_query>",
        },
        {"role": "assistant", "message": {"model": "claude-4.5-sonnet", "content": "Fixed it."}},
        {"role": "system", "content": "context compacted"},
        {"not": "a message"},
    ]
)

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


def test_the_agents_own_notes_are_part_of_the_trajectory():
    """Claude Code writes notes of its own - an away summary, say - as `system`
    lines. They are part of what happened and belong in the trajectory."""
    raw = json.dumps(
        {"type": "system", "subtype": "away_summary", "content": "picked up where we left off"}
    )
    (step,) = _steps(raw)
    assert step["source"] == "system"
    assert step["message"] == "picked up where we left off"


def test_session_state_lines_are_not_conversation_and_stay_out():
    """These carry UI state, not what happened - and a file-history-snapshot
    carries whole file contents, which must never ride along in an upload."""
    raw = "\n".join(
        json.dumps(line)
        for line in [
            {"type": "mode", "mode": "acceptEdits"},
            {"type": "ai-title", "aiTitle": "Refactor the uploader"},
            {"type": "last-prompt", "lastPrompt": "do the thing"},
            {"type": "attachment", "attachment": {"type": "deferred_tools_delta"}},
            {"type": "file-history-snapshot", "snapshot": {"secret.py": "API_KEY = 'hunter2'"}},
            {"type": "system", "subtype": "turn_duration", "content": None},
        ]
    )
    assert _steps(raw) == []
    assert "hunter2" not in json.dumps(claude_jsonl_to_atif(raw, session_id="s", agent="x"))


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


# --------------------------------------------------------------------------
# Cursor
# --------------------------------------------------------------------------


def test_a_cursor_session_becomes_the_conversation():
    steps = cursor_jsonl_to_atif(CURSOR_SESSION, session_id="s", agent="cursor")["steps"]
    assert [(s["source"], s["message"]) for s in steps] == [
        ("user", "fix the test"),  # the wrapper and stamp are stripped off
        ("agent", "Fixed it."),
        ("system", "context compacted"),
    ]
    assert steps[0]["timestamp"] == "2026-09-21T10:00:00Z"


def test_a_cursor_model_name_is_kept_when_the_line_carries_one():
    trajectory = cursor_jsonl_to_atif(CURSOR_SESSION, session_id="s", agent="cursor")
    assert trajectory["agent"] == {"name": "cursor", "model_name": "claude-4.5-sonnet"}
    assert trajectory["schema_version"] == SCHEMA_VERSION


def test_a_cursor_model_name_comes_from_the_agent_label_when_no_line_carries_one():
    """What the hook posts: the model its stop event named, after the harness."""
    raw = json.dumps({"role": "user", "message": {"content": [{"type": "text", "text": "hi"}]}})
    trajectory = cursor_jsonl_to_atif(raw, session_id="s", agent="cursor gpt-5.1-codex")
    assert trajectory["agent"] == {"name": "cursor", "model_name": "gpt-5.1-codex"}


def test_cursor_token_totals_are_zero_because_cursor_records_none():
    """Not a free session - Cursor simply never writes usage to the transcript."""
    metrics = cursor_jsonl_to_atif(CURSOR_SESSION, session_id="s", agent="cursor")["final_metrics"]
    assert metrics == {
        "total_prompt_tokens": 0,
        "total_completion_tokens": 0,
        "total_steps": 3,
    }


@pytest.mark.parametrize(
    "ask",
    [
        "# RateXp survey\n\nIf the user wrote a skill name after /ratexp, ...",  # /ratexp
        "RateXp survey for this whole chat: run `bash ... ask` ...",  # the stop hook's followup
    ],
)
def test_the_survey_itself_is_not_part_of_the_run_it_rates(ask):
    raw = json.dumps({"role": "user", "content": ask})
    assert cursor_jsonl_to_atif(raw, session_id="s", agent="cursor")["steps"] == []


@pytest.mark.parametrize(
    ("source", "marks"),
    [
        # Cursor's whole survey is worded here: the /ratexp command it writes, which
        # Cursor logs as the user's message, and its questions and its result.
        ("ratexp-cursor.sh", CURSOR_SURVEY_MARKS),
        # Claude Code writes the command's name itself; the body, and the one line it
        # has the agent say, come from the /ratexp commands the hook writes.
        (
            "ratexp-claude.sh",
            [m for m in CLAUDE_REQUEST_MARKS if "<command-name>" not in m],
        ),
    ],
)
def test_the_real_survey_carries_the_marks_that_drop_it(source, marks):
    """Worded any other way, the survey would land in every rated trajectory."""
    text = (Path(__file__).resolve().parents[1] / source).read_text(encoding="utf-8")
    assert all(mark in text for mark in marks)


def test_an_earlier_survey_is_left_out_of_a_later_upload():
    """A chat is surveyed every few turns, so a whole-chat upload carries the earlier
    surveys: the questions the agent asked - with AskQuestion or in plain text - and
    the result it relayed. None of that is the work being rated."""
    consent = "Upload this whole chat, including messages and tool results, to https://c.test?"
    ask = {
        "type": "tool_use",
        "name": "AskQuestion",
        "input": {"title": "RateXp", "prompt": consent},
    }
    raw = "\n".join(
        json.dumps({"role": role, "message": {"content": content}})
        for role, content in [
            ("user", "<user_query>fix the test</user_query>"),
            ("assistant", "Fixed it."),
            ("assistant", [ask]),
            ("assistant", f"Rate this session: good or bad? {consent} share or private?"),
            ("assistant", "RateXp: feedback accepted by https://c.test. Transcript kept private."),
            ("user", "<user_query>now the docs</user_query>"),
        ]
    )
    steps = cursor_jsonl_to_atif(raw, session_id="s", agent="cursor")["steps"]
    assert [step.get("message") for step in steps] == ["fix the test", "Fixed it.", "now the docs"]


def test_the_agent_field_picks_the_reader():
    """One `agent` string decides the format; nothing sniffs the bytes."""
    assert jsonl_to_atif(CURSOR_SESSION, session_id="s", agent="cursor")["steps"]
    # Claude's reader needs a `type`, so Cursor's lines leave it with nothing.
    assert jsonl_to_atif(CURSOR_SESSION, session_id="s", agent="claude-code")["steps"] == []
    assert jsonl_to_atif(SESSION, session_id="s", agent="claude-code")["steps"]


def test_a_cursor_trajectory_keeps_tool_calls_reasoning_and_results():
    """Everything Cursor recorded is kept, not only what was said."""
    raw = "\n".join(
        json.dumps(line)
        for line in [
            {
                "role": "user",
                "message": {
                    "content": [{"type": "text", "text": "<user_query>list files</user_query>"}]
                },
            },
            {
                "role": "assistant",
                "message": {
                    "content": [
                        {"type": "thinking", "thinking": "I should run ls."},
                        {"type": "text", "text": "Listing them."},
                        {
                            "type": "tool_use",
                            "id": "t1",
                            "name": "Shell",
                            "input": {"command": "ls"},
                        },
                    ]
                },
            },
            {
                "role": "user",
                "message": {"content": [{"type": "tool_result", "content": "a.txt b.txt"}]},
            },
            {
                "role": "assistant",
                "message": {
                    "content": [{"type": "tool_use", "name": "Read", "input": {"path": "a.txt"}}]
                },
            },
        ]
    )
    steps = cursor_jsonl_to_atif(raw, session_id="s", agent="cursor")["steps"]
    assert steps[1]["reasoning_content"] == "I should run ls."
    assert steps[1]["tool_calls"] == [
        {"tool_call_id": "t1", "name": "Shell", "arguments": {"command": "ls"}}
    ]
    assert steps[2] == {"step_id": 3, "source": "system", "observation": "a.txt b.txt"}
    assert steps[3]["tool_calls"][0]["name"] == "Read", "a call with no text is still a step"


def test_the_agent_running_the_ratexp_script_is_not_part_of_the_run():
    raw = json.dumps(
        {
            "role": "assistant",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "name": "Shell",
                        "input": {
                            "command": 'bash "/x/.cursor/ratexp-cursor.sh" report good share'
                        },
                    }
                ]
            },
        }
    )
    assert cursor_jsonl_to_atif(raw, session_id="s", agent="cursor")["steps"] == []


@pytest.mark.parametrize(
    "content",
    [
        "<command-name>/ratexp</command-name>",
        "<command-name>/ratexp:poem-creator</command-name>",
        "RateXp target: poem-creator\n\nSay only: ...",
        [{"type": "text", "text": "Opening the RateXp survey."}],
    ],
)
def test_the_claude_ratexp_request_is_not_part_of_the_run(content):
    role = "assistant" if isinstance(content, list) else "user"
    raw = json.dumps({"type": role, "message": {"role": role, "content": content}})
    assert claude_jsonl_to_atif(raw, session_id="s", agent="claude-code")["steps"] == []
