"""LangChain messages -> ATIF: the step mapping, the totals, and the oversized padding."""

from __future__ import annotations

import json

from conftest import message
from modules.submit import build_trajectory
from modules.submit.build_trajectory import messages_to_atif


def test_text_joins_text_blocks_and_ignores_non_dicts():
    assert build_trajectory._text("hi") == "hi"
    assert build_trajectory._text(None) == ""
    assert build_trajectory._text([{"text": "a"}, "skip", {"text": "b"}]) == "a\nb"


def test_steps_map_sources_calls_and_metrics():
    steps = build_trajectory._steps(
        [
            message("human", "hello"),
            message(
                "ai",
                "on it",
                tool_calls=[{"id": "t1", "name": "load_skill", "args": {}}],
                usage={"input_tokens": 10, "output_tokens": 4},
            ),
            message("tool", "tool output"),
            message("ai", ""),  # empty agent turn, no calls -> dropped
        ]
    )
    assert [s["source"] for s in steps] == ["user", "agent", "system"]
    assert steps[0]["message"] == "hello"
    assert steps[1]["tool_calls"][0]["name"] == "load_skill"
    assert steps[1]["metrics"] == {"prompt_tokens": 10, "completion_tokens": 4}
    assert steps[2]["observation"] == "tool output"


def test_atif_carries_the_run_identity_and_totals(run, monkeypatch):
    monkeypatch.setattr(build_trajectory, "OVERSIZED_RATIO", 0)
    atif = messages_to_atif(
        run,
        [
            message("human", "hello"),
            message("ai", "done", usage={"input_tokens": 7, "output_tokens": 3}),
        ],
    )
    assert atif["session_id"] == "s"
    assert atif["agent"]["name"] == "langchain"
    assert atif["final_metrics"] == {
        "total_prompt_tokens": 7,
        "total_completion_tokens": 3,
        "total_steps": 2,
    }


def test_no_padding_when_oversized_is_off(run, monkeypatch):
    monkeypatch.setattr(build_trajectory, "OVERSIZED_RATIO", 0)
    assert messages_to_atif(run, [])["steps"] == []


def test_padding_pushes_the_body_past_cores_size_limit(run, monkeypatch):
    monkeypatch.setattr(build_trajectory, "OVERSIZED_RATIO", 1)  # always oversized
    atif = messages_to_atif(run, [])
    # Over core's max_transcript_bytes (256 KiB), so core stores a meta-only stub.
    assert len(json.dumps(atif).encode()) > 262144
    # The kept totals describe the real run, not the synthetic padding.
    assert atif["final_metrics"]["total_steps"] == 0
