"""claude_jsonl_to_atif - Claude Code .jsonl -> ATIF trajectory."""

from __future__ import annotations

import json

from atif import SCHEMA_VERSION, claude_jsonl_to_atif

SAMPLE = "\n".join(
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


def test_schema_and_agent():
    atif = claude_jsonl_to_atif(SAMPLE, session_id="sess-1", agent="claude-code claude-opus-4-8")
    assert atif["schema_version"] == SCHEMA_VERSION
    assert atif["session_id"] == "sess-1"
    # Per-turn model id from the .jsonl wins over the agent label.
    assert atif["agent"] == {"name": "claude-code", "model_name": "claude-opus-4-8"}


def test_summary_lines_skipped_and_steps_sequential():
    atif = claude_jsonl_to_atif(SAMPLE, session_id="s", agent="claude-code")
    steps = atif["steps"]
    assert [s["step_id"] for s in steps] == [1, 2, 3, 4]
    assert [s["source"] for s in steps] == ["user", "agent", "system", "agent"]


def test_user_message_text():
    steps = claude_jsonl_to_atif(SAMPLE, session_id="s", agent="x")["steps"]
    assert steps[0]["message"] == "hello"


def test_assistant_text_reasoning_and_tool_calls():
    steps = claude_jsonl_to_atif(SAMPLE, session_id="s", agent="x")["steps"]
    agent_step = steps[1]
    assert agent_step["message"] == "running it"
    assert agent_step["reasoning_content"] == "let me look"
    assert agent_step["tool_calls"] == [
        {"tool_call_id": "t1", "name": "Bash", "arguments": {"command": "ls"}}
    ]
    assert agent_step["metrics"] == {"prompt_tokens": 12, "completion_tokens": 5}


def test_tool_result_becomes_system_observation():
    steps = claude_jsonl_to_atif(SAMPLE, session_id="s", agent="x")["steps"]
    assert steps[2]["source"] == "system"
    assert steps[2]["observation"] == "a.txt"


def test_final_metrics():
    atif = claude_jsonl_to_atif(SAMPLE, session_id="s", agent="x")
    assert atif["final_metrics"]["total_steps"] == 4
    assert atif["final_metrics"]["total_prompt_tokens"] == 12
    assert atif["final_metrics"]["total_completion_tokens"] == 5


def test_cache_tokens_counted_as_prompt():
    # Cached context is reported in its own fields; prompt_tokens should sum them
    # with fresh input (7 + 100 + 20 = 127), not just count input_tokens.
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
    atif = claude_jsonl_to_atif(raw, session_id="s", agent="x")
    assert atif["steps"][0]["metrics"] == {"prompt_tokens": 127, "completion_tokens": 3}
    assert atif["final_metrics"]["total_prompt_tokens"] == 127
    assert atif["final_metrics"]["total_completion_tokens"] == 3


def test_blank_and_malformed_lines_ignored():
    raw = '\n  \nnot json\n{"type":"user","message":{"role":"user","content":"hi"}}\n'
    steps = claude_jsonl_to_atif(raw, session_id="s", agent="x")["steps"]
    assert len(steps) == 1
    assert steps[0]["message"] == "hi"


def test_empty_input():
    atif = claude_jsonl_to_atif("", session_id="s", agent="x")
    assert atif["steps"] == []
    assert atif["final_metrics"]["total_steps"] == 0
