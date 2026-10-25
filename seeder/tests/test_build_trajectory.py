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
        "total_cached_tokens": 0,
        "total_steps": 2,
    }


def test_cache_hits_are_kept_per_step_and_totalled(run, monkeypatch):
    monkeypatch.setattr(build_trajectory, "OVERSIZED_RATIO", 0)
    cached = {"input_tokens": 100, "output_tokens": 5, "input_token_details": {"cache_read": 60}}
    uncached = {"input_tokens": 20, "output_tokens": 2, "input_token_details": {"cache_read": 0}}
    atif = messages_to_atif(
        run, [message("ai", "a", usage=cached), message("ai", "b", usage=uncached)]
    )
    assert atif["steps"][0]["metrics"]["cached_tokens"] == 60
    # Like core's Claude path, a step with no cache hit carries no cached_tokens.
    assert "cached_tokens" not in atif["steps"][1]["metrics"]
    assert atif["final_metrics"]["total_prompt_tokens"] == 120
    assert atif["final_metrics"]["total_cached_tokens"] == 60


def test_cached_total_is_unknown_when_no_usage_was_recorded(run, monkeypatch):
    monkeypatch.setattr(build_trajectory, "OVERSIZED_RATIO", 0)
    atif = messages_to_atif(run, [message("ai", "done")])
    assert atif["final_metrics"]["total_cached_tokens"] is None


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
