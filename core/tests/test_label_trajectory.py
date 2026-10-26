"""Labeling a trajectory: what the model is shown, what it is asked, and that every way
it can go wrong leaves the labels empty instead of failing the upload.

No model is reached: the HTTP call and the token are replaced in every test.
"""

from __future__ import annotations

import io
import json
import logging

import pytest
from load_config import LABELING_TIMEOUT_SECONDS, LABELS
from modules.labeling import label_trajectory
from modules.labeling.label_trajectory import Labels, digest_trajectory, label_atif

ENDPOINT = "https://aoai.example/"
ATIF = {
    "steps": [
        {"step_id": 1, "source": "user", "message": "The handler panics on a nil body, fix it"},
        {
            "step_id": 2,
            "source": "agent",
            "message": "Guarding the nil body.",
            "tool_calls": [{"name": "Edit", "arguments": {"file_path": "server/handler.go"}}],
        },
        {"step_id": 3, "source": "system", "observation": "file edited"},
    ]
}


@pytest.fixture
def model(monkeypatch) -> dict:
    """Switch labeling on against a fake model; return what it was sent and will answer.

    Set ``answer`` to the dict the model replies with, or ``error`` to what the call raises.
    """
    sent: dict = {"answer": {"business_case": "backend", "language": "go", "task_type": "fix"}}

    def fake_urlopen(request, timeout):
        sent["request"], sent["timeout"] = request, timeout
        if "error" in sent:
            raise sent["error"]
        content = json.dumps(sent["answer"])
        reply = {"choices": [{"message": {"content": content}}]}
        return io.BytesIO(json.dumps(reply).encode())

    monkeypatch.setattr(label_trajectory, "LABELING_ENDPOINT", ENDPOINT)
    monkeypatch.setattr(label_trajectory, "_bearer_token", lambda: "tok")
    monkeypatch.setattr(label_trajectory.urllib.request, "urlopen", fake_urlopen)
    return sent


def test_a_good_answer_becomes_the_labels(model):
    assert label_atif(ATIF) == Labels(business_case="backend", language="go", task_type="fix")


def test_the_model_is_asked_for_one_word_from_each_configured_list(model):
    label_atif(ATIF)
    request = model["request"]
    assert request.full_url.startswith(f"{ENDPOINT}openai/deployments/gpt-5-nano/chat/completions")
    assert "api-version=" in request.full_url
    assert request.get_header("Authorization") == "Bearer tok"
    body = json.loads(request.data)
    schema = body["response_format"]["json_schema"]
    assert schema["strict"] is True
    assert schema["schema"]["required"] == ["business_case", "language", "task_type"]
    for group, words in LABELS.items():
        assert schema["schema"]["properties"][group]["enum"] == words
    assert body["messages"][1]["content"] == digest_trajectory(ATIF, 20000)
    assert model["timeout"] == LABELING_TIMEOUT_SECONDS


def test_an_answer_off_the_lists_leaves_every_label_empty(model, caplog):
    model["answer"] = {"business_case": "backend", "language": "cobol", "task_type": "fix"}
    with caplog.at_level(logging.WARNING):
        assert label_atif(ATIF) == Labels()
    assert "labeling failed" in caplog.text


@pytest.mark.parametrize(
    "error", [TimeoutError("read timed out"), OSError("connection refused"), KeyError("choices")]
)
def test_a_failing_or_slow_model_leaves_every_label_empty(model, error, caplog):
    # Fail-open: the upload is stored either way, only without labels.
    model["error"] = error
    with caplog.at_level(logging.WARNING):
        assert label_atif(ATIF) == Labels()
    assert "labeling failed" in caplog.text


def test_without_an_endpoint_nothing_is_sent(model, monkeypatch):
    monkeypatch.setattr(label_trajectory, "LABELING_ENDPOINT", "")
    assert label_atif(ATIF) == Labels()
    assert "request" not in model


def test_switched_off_nothing_is_sent(model, monkeypatch):
    monkeypatch.setattr(label_trajectory, "LABELING_ENABLED", False)
    assert label_atif(ATIF) == Labels()
    assert "request" not in model


def test_a_trajectory_with_nothing_to_read_is_not_sent(model):
    assert label_atif({"steps": []}) == Labels()
    assert "request" not in model


def test_the_digest_holds_who_said_what_and_which_files_were_touched_but_no_tool_output():
    digest = digest_trajectory(ATIF, 20000)
    assert digest.splitlines() == [
        "user: The handler panics on a nil body, fix it",
        "agent: Guarding the nil body.",
        'tool Edit: {"file_path": "server/handler.go"}',
    ]


def test_the_digest_cuts_each_message_and_the_whole_to_size():
    steps = [{"source": "user", "message": "x" * 5000} for _ in range(20)]
    lines = digest_trajectory({"steps": steps}, 20000).splitlines()
    assert len(lines[0]) == len("user: ") + 2000
    assert len("\n".join(lines)) == 20000


def test_a_digest_of_an_odd_trajectory_is_empty_rather_than_an_error():
    # A client posts the ATIF, so any key may be missing or of the wrong type.
    odd = {"steps": ["not a step", {"source": "agent", "message": 7, "tool_calls": "Bash"}]}
    assert digest_trajectory(odd, 20000) == ""
    assert digest_trajectory({"steps": None}, 20000) == ""
