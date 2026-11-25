"""Labeling a rating: what the model is shown, what it may answer, and that every way it
can go wrong leaves the labels empty instead of failing the upload.

No model is reached: the HTTP call and the token are replaced in every test.
"""

from __future__ import annotations

import io
import json
import logging

import pytest
from load_config import LABEL_GROUPS, LABELING_TIMEOUT_SECONDS, NO_LABEL
from modules.labeling import label_ratings
from modules.labeling.label_ratings import digest_trajectory, label_rating

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
ANSWER = {
    "business_case": "Backend",
    "language": "Go",
    "task_type": "Bug fix",
    "feedback_theme": "Completion is slow",
}
BAD = {"score": 2, "comment": "Far too slow", "skill_name": "go-fixer", "eval_name": "speed"}


@pytest.fixture
def model(monkeypatch) -> dict:
    """Switch labeling on against a fake model; return what it was sent and will answer.

    Set ``answer`` to the dict the model replies with, or ``error`` to what the call raises.
    """
    sent: dict = {"answer": dict(ANSWER)}

    def fake_urlopen(request, timeout):
        sent["request"], sent["timeout"] = request, timeout
        if "error" in sent:
            raise sent["error"]
        content = json.dumps(sent["answer"])
        reply = {"choices": [{"message": {"content": content}}]}
        return io.BytesIO(json.dumps(reply).encode())

    monkeypatch.setattr(label_ratings, "LABELING_ENDPOINT", ENDPOINT)
    monkeypatch.setattr(label_ratings, "_bearer_token", lambda: "tok")
    monkeypatch.setattr(label_ratings.urllib.request, "urlopen", fake_urlopen)
    return sent


def _body(model) -> dict:
    return json.loads(model["request"].data)


def _enums(model) -> dict[str, list[str]]:
    schema = _body(model)["response_format"]["json_schema"]["schema"]
    return {group: prop["enum"] for group, prop in schema["properties"].items()}


def test_a_good_answer_becomes_the_labels(model):
    assert label_rating(**BAD, atif=ATIF) == ANSWER


def test_a_group_the_model_cannot_tell_is_left_out(model):
    model["answer"] = {**ANSWER, "language": NO_LABEL}
    labels = label_rating(**BAD)
    assert "language" not in labels
    assert labels["feedback_theme"] == "Completion is slow"


def test_the_model_is_asked_for_one_value_per_configured_group(model):
    label_rating(**BAD)
    request = model["request"]
    assert request.full_url.startswith(f"{ENDPOINT}openai/deployments/gpt-5-nano/chat/completions")
    assert "api-version=" in request.full_url
    assert request.get_header("Authorization") == "Bearer tok"
    schema = _body(model)["response_format"]["json_schema"]
    assert schema["strict"] is True
    assert schema["schema"]["required"] == list(LABEL_GROUPS)
    assert model["timeout"] == LABELING_TIMEOUT_SECONDS


def test_a_bad_rating_may_only_get_complaints_and_a_good_one_only_praise(model):
    theme = LABEL_GROUPS["feedback_theme"]
    label_rating(**BAD)
    assert _enums(model)["feedback_theme"] == [*theme.when_bad, NO_LABEL]
    assert "Completion is slow" in _body(model)["messages"][0]["content"]
    assert "Completion is quick" not in _body(model)["messages"][0]["content"]
    model["answer"] = {**ANSWER, "feedback_theme": "Completion is quick"}
    label_rating(**{**BAD, "score": 1, "comment": "Quick"})
    assert _enums(model)["feedback_theme"] == [*theme.when_good, NO_LABEL]


def test_an_unrated_comment_may_get_either_side(model):
    label_rating(**{**BAD, "score": None})
    assert _enums(model)["feedback_theme"] == [*LABEL_GROUPS["feedback_theme"].values, NO_LABEL]


def test_a_group_that_does_not_split_offers_every_value_whatever_the_score(model):
    label_rating(**BAD)
    assert _enums(model)["language"] == [*LABEL_GROUPS["language"].values, NO_LABEL]


def test_the_prompt_holds_the_rating_the_comment_and_the_conversation(model):
    label_rating(**BAD, atif=ATIF)
    system, user = (m["content"] for m in _body(model)["messages"])
    assert "- feedback_theme: " + LABEL_GROUPS["feedback_theme"].means in system
    assert "  - Completion is slow: It took too long or kept me waiting." in system
    assert user.splitlines()[:4] == [
        "Rating: bad",
        "Rated: the skill go-fixer",
        "Eval: speed",
        "Comment: Far too slow",
    ]
    assert user.endswith("Conversation:\n" + digest_trajectory(ATIF, 20000))


def test_a_session_rating_without_a_comment_is_labeled_from_its_conversation(model):
    label_rating(score=1, comment=None, skill_name=None, eval_name=None, atif=ATIF)
    user = _body(model)["messages"][1]["content"]
    assert "Rated: the whole session" in user
    assert "Comment: none" in user


def test_the_comment_is_masked_before_the_model_reads_it(model, monkeypatch):
    monkeypatch.setattr(label_ratings, "redact_text", lambda text: text.replace("Ann", "<PERSON>"))
    label_rating(**{**BAD, "comment": "Ann waited an hour"})
    assert "Comment: <PERSON> waited an hour" in _body(model)["messages"][1]["content"]


def test_a_failing_mask_sends_nothing_and_leaves_the_labels_empty(model, monkeypatch, caplog):
    def boom(text):
        raise RuntimeError("presidio down")

    monkeypatch.setattr(label_ratings, "redact_text", boom)
    with caplog.at_level(logging.WARNING):
        assert label_rating(**BAD) == {}
    assert "request" not in model
    assert "labeling failed" in caplog.text


def test_an_answer_off_the_lists_leaves_every_label_empty(model, caplog):
    # Completion is quick is praise, and a bad rating may only get a complaint.
    model["answer"] = {**ANSWER, "feedback_theme": "Completion is quick"}
    with caplog.at_level(logging.WARNING):
        assert label_rating(**BAD) == {}
    assert "labeling failed" in caplog.text


@pytest.mark.parametrize(
    "error", [TimeoutError("read timed out"), OSError("connection refused"), KeyError("choices")]
)
def test_a_failing_or_slow_model_leaves_every_label_empty(model, error, caplog):
    # Fail-open: the upload is stored either way, only without labels.
    model["error"] = error
    with caplog.at_level(logging.WARNING):
        assert label_rating(**BAD, atif=ATIF) == {}
    assert "labeling failed" in caplog.text


def test_without_an_endpoint_nothing_is_sent(model, monkeypatch):
    monkeypatch.setattr(label_ratings, "LABELING_ENDPOINT", "")
    assert label_rating(**BAD) == {}
    assert "request" not in model


def test_switched_off_nothing_is_sent(model, monkeypatch):
    monkeypatch.setattr(label_ratings, "LABELING_ENABLED", False)
    assert label_rating(**BAD) == {}
    assert "request" not in model


def test_no_comment_and_no_conversation_is_not_sent(model):
    assert label_rating(score=2, comment="  ", skill_name=None, eval_name=None) == {}
    assert label_rating(score=2, comment=None, skill_name=None, eval_name=None, atif={}) == {}
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
