"""The numbers a dashboard charts about a trajectory, and what "unknown" looks like."""

from __future__ import annotations

import pytest
from modules.write.summarize_trajectory import summarize_trajectory

TRAJECTORY = {
    "agent": {"name": "claude-code", "model_name": "claude-opus-4-8"},
    "steps": [
        {"step_id": 1, "source": "user", "message": "hi"},
        {"step_id": 2, "source": "agent", "tool_calls": [{"name": "Bash"}, {"name": "Read"}]},
        {"step_id": 3, "source": "system", "observation": "a.txt"},
        {"step_id": 4, "source": "agent", "tool_calls": [{"name": "Edit"}]},
    ],
    "final_metrics": {
        "total_prompt_tokens": 120,
        "total_completion_tokens": 30,
        "total_cached_tokens": 90,
        "total_steps": 4,
    },
}


def test_a_full_trajectory_is_counted_from_its_steps():
    assert summarize_trajectory(TRAJECTORY, "claude-code") == {
        "steps": 4,
        "tool_calls": 3,
        "prompt_tokens": 120,
        "cached_tokens": 90,
        "completion_tokens": 30,
        "model": "claude-opus-4-8",
    }


def test_an_oversized_stub_keeps_its_step_total_but_cannot_count_tool_calls():
    # The stub drops the steps (see api/build_trajectory.py), so the calls inside
    # them are unknown - not zero.
    stub = {**TRAJECTORY, "steps": [], "oversized": {"byte_size": 999}}
    summary = summarize_trajectory(stub, "claude-code")
    assert summary["steps"] == 4
    assert summary["tool_calls"] is None
    assert summary["prompt_tokens"] == 120
    assert summary["cached_tokens"] == 90


def test_a_bare_trajectory_is_all_unknown():
    # A client may post ATIF of its own making, down to an empty object.
    assert summarize_trajectory({}, "claude-code") == {
        "steps": None,
        "tool_calls": None,
        "prompt_tokens": None,
        "cached_tokens": None,
        "completion_tokens": None,
        "model": None,
    }


def test_zero_tokens_on_both_sides_means_not_recorded():
    # Cursor writes no usage at all; a zero would read as a run that cost nothing,
    # and with nothing recorded there is no cache hit to count either.
    for metrics in (
        {"total_prompt_tokens": 0, "total_completion_tokens": 0, "total_cached_tokens": 0},
        {},
    ):
        summary = summarize_trajectory({"final_metrics": metrics}, "cursor")
        assert (
            summary["prompt_tokens"],
            summary["cached_tokens"],
            summary["completion_tokens"],
        ) == (None, None, None)


def test_recorded_usage_without_a_cache_hit_counts_zero_cached():
    summary = summarize_trajectory(
        {"final_metrics": {"total_prompt_tokens": 5, "total_cached_tokens": 0}}, "x"
    )
    assert summary["cached_tokens"] == 0


def test_a_trajectory_that_does_not_say_what_was_cached_leaves_it_unknown():
    # A client may post its own ATIF with prompt and completion totals only.
    summary = summarize_trajectory({"final_metrics": {"total_prompt_tokens": 5}}, "x")
    assert summary["cached_tokens"] is None


def test_tokens_recorded_on_one_side_only_keep_the_other_at_zero():
    summary = summarize_trajectory({"final_metrics": {"total_completion_tokens": 7}}, "x")
    assert (summary["prompt_tokens"], summary["completion_tokens"]) == (0, 7)


def test_the_model_falls_back_to_the_agent_labels_second_word():
    # The hooks post the model after the harness, e.g. "cursor gpt-5", and a label
    # with no second word names none.
    assert summarize_trajectory({"steps": [{"step_id": 1}]}, "cursor default")["model"] == "default"
    assert summarize_trajectory({"agent": {"model_name": None}}, "claude-code")["model"] is None
    assert (
        summarize_trajectory({"agent": {"model_name": "gpt-4o"}}, "cursor x")["model"] == "gpt-4o"
    )


def test_odd_shapes_are_tolerated_rather_than_raised_on():
    atif = {
        "agent": "not a dict",
        "steps": ["not a step", {"step_id": 2, "tool_calls": None}],
        "final_metrics": "not metrics",
    }
    assert summarize_trajectory(atif, "")["steps"] == 2
    assert summarize_trajectory(atif, "")["tool_calls"] == 0
    assert summarize_trajectory(atif, "")["model"] is None


def test_oddly_typed_tool_calls_and_model_are_tolerated_rather_than_raised_on():
    # A client posts its own ATIF, so a field may hold any JSON type: only a list
    # of tool calls is counted, and only a string names a model.
    atif = {
        "agent": {"model_name": ["not", "a", "name"]},
        "steps": [
            {"step_id": 1, "tool_calls": 3},
            {"step_id": 2, "tool_calls": "Bash"},
            {"step_id": 3, "tool_calls": {"name": "Bash"}},
            {"step_id": 4, "tool_calls": [{"name": "Read"}]},
        ],
    }
    summary = summarize_trajectory(atif, "cursor gpt-5")
    assert (summary["steps"], summary["tool_calls"], summary["model"]) == (4, 1, "gpt-5")


@pytest.mark.parametrize(
    "junk",
    [
        "100",
        True,
        False,
        None,
        [100],
        {"n": {"m": 100}},
        # Numbers, but no count: NaN or infinity, a negative, or past 2**53, where
        # JSON readers stop holding an integer exactly.
        10**30,
        2**63,
        2**53,
        -5,
        float("nan"),
        float("inf"),
        float("-inf"),
    ],
)
def test_a_junk_token_total_reads_zero_beside_a_recorded_side_and_the_cache_is_unknown(junk):
    # A bool is an int to Python, but True is not one token. The completion side is
    # recorded, so the junk prompt side reads 0 as a missing one would; the cache
    # has no recorded side to lean on.
    metrics = {
        "total_prompt_tokens": junk,
        "total_completion_tokens": 7,
        "total_cached_tokens": junk,
    }
    summary = summarize_trajectory({"final_metrics": metrics}, "x")
    assert (
        summary["prompt_tokens"],
        summary["cached_tokens"],
        summary["completion_tokens"],
    ) == (0, None, 7)


@pytest.mark.parametrize(
    ("total", "kept"),
    [
        (48_213_906, 48_213_906),  # a long Claude Code session's prompt total
        (2**53 - 1, 2**53 - 1),
        (-0.0, 0),
    ],
)
def test_a_token_total_that_is_a_usable_count_is_kept(total, kept):
    metrics = {
        "total_prompt_tokens": total,
        "total_completion_tokens": 7,
        "total_cached_tokens": total,
    }
    summary = summarize_trajectory({"final_metrics": metrics}, "x")
    # repr, because -0.0 == 0 and only the printed sign tells them apart.
    assert repr(summary["prompt_tokens"]) == repr(summary["cached_tokens"]) == repr(kept)


def test_prompt_and_completion_totals_that_are_not_numbers_mean_not_recorded():
    metrics = {
        "total_prompt_tokens": True,
        "total_completion_tokens": "7",
        "total_cached_tokens": 3,
    }
    summary = summarize_trajectory({"final_metrics": metrics}, "x")
    assert (
        summary["prompt_tokens"],
        summary["cached_tokens"],
        summary["completion_tokens"],
    ) == (None, None, None)


def test_float_token_totals_are_kept():
    metrics = {
        "total_prompt_tokens": 12.0,
        "total_completion_tokens": 5.5,
        "total_cached_tokens": 9.0,
    }
    summary = summarize_trajectory({"final_metrics": metrics}, "x")
    assert (
        summary["prompt_tokens"],
        summary["cached_tokens"],
        summary["completion_tokens"],
    ) == (12.0, 9.0, 5.5)


@pytest.mark.parametrize("junk", ["4", 4.0, True, None, [4], 10**30, 2**53, -4])
def test_a_step_total_that_is_not_a_usable_int_is_unknown(junk):
    summary = summarize_trajectory(
        {"steps": "not a list", "final_metrics": {"total_steps": junk}}, "x"
    )
    assert (summary["steps"], summary["tool_calls"]) == (None, None)


@pytest.mark.parametrize("total", [4, 2**53 - 1])
def test_steps_that_are_not_a_list_fall_back_to_the_step_total(total):
    atif = {
        "steps": {"1": {"tool_calls": [{"name": "Bash"}]}},
        "final_metrics": {"total_steps": total},
    }
    summary = summarize_trajectory(atif, "x")
    assert (summary["steps"], summary["tool_calls"]) == (total, None)
