"""POST /feedback: what a rating may look like on the wire, and what it may not.

`client`, `captured_writes` and `no_destination_accepts` come from conftest.py.
"""

from __future__ import annotations

import pytest

# The hook posts every field with `curl --form-string`, so multipart is the shape
# that actually arrives in production. JSON is what the seeder sends.
FORM = {
    "skill_name": "demo",
    "agent": "claude-code",
    "eval_name": "human-satisfaction",
    "session_id": "sess-1",
    "request_id": "req-1",
    "score": "1",
    "comment": "great",
}

JSON_CT = {"content-type": "application/json"}


def _multipart(**overrides) -> dict:
    """FORM plus overrides as httpx multipart fields. An override of None drops it."""
    fields = {**FORM, **overrides}
    return {name: (None, value) for name, value in fields.items() if value is not None}


def test_a_form_post_stores_the_rating(client, captured_writes):
    response = client.post("/feedback", files=_multipart())
    assert response.status_code == 201
    assert response.json() == {"status": "stored"}
    record = captured_writes[-1]
    assert record.skill_name == "demo"
    assert record.agent == "claude-code"
    assert record.eval_name == "human-satisfaction"
    assert record.score == 1  # "1" on the wire, an int in the record
    assert record.comment == "great"
    assert record.request_id == "req-1"


def test_a_rating_for_a_whole_session_carries_no_skill(client, captured_writes):
    # Nothing but the session hook posts this shape: the run being rated is the
    # session itself, so there is no skill to name.
    response = client.post("/feedback", files=_multipart(skill_name=None))
    assert response.status_code == 201
    assert captured_writes[-1].skill_name is None
    assert captured_writes[-1].agent == "claude-code"


def test_a_rating_that_names_no_eval_still_stores(client, captured_writes):
    # A hook downloaded before evals existed sends none; its rating still counts.
    response = client.post("/feedback", files=_multipart(eval_name=None))
    assert response.status_code == 201
    assert captured_writes[-1].eval_name is None


def test_a_json_post_stores_the_rating(client, captured_writes):
    response = client.post("/feedback", json={**FORM, "score": 1})
    assert response.status_code == 201
    assert captured_writes[-1].score == 1
    assert captured_writes[-1].comment == "great"


def test_an_explicitly_null_score_and_comment_are_accepted(client, captured_writes):
    response = client.post(
        "/feedback",
        json={"skill_name": "demo", "agent": "claude-code", "score": None, "comment": None},
    )
    assert response.status_code == 201
    assert captured_writes[-1].score is None


def test_a_dismissed_picker_sends_neither_field_and_still_stores(client, captured_writes):
    # Someone closed the picker without rating. The run is still worth counting.
    response = client.post("/feedback", files=_multipart(score=None, comment=None))
    assert response.status_code == 201
    assert captured_writes[-1].score is None
    assert captured_writes[-1].comment is None


@pytest.mark.parametrize("score", ["0", "3", "maybe", "-1", "1.0"])
def test_a_score_outside_one_and_two_is_refused(client, captured_writes, score):
    assert client.post("/feedback", files=_multipart(score=score)).status_code == 422
    assert captured_writes == []


@pytest.mark.parametrize(
    ("score", "why"),
    [
        ("٢", "Arabic-Indic two"),
        ("²", "superscript two"),
        ("1" * 100_000, "a number no int() should be asked to build"),
    ],
)
def test_a_score_that_is_not_plain_ascii_digits_is_refused(client, captured_writes, score, why):
    # These all pass str.isdigit(). int() either refuses them outright or would
    # record a rating nobody gave.
    assert client.post("/feedback", files=_multipart(score=score)).status_code == 422, why
    assert captured_writes == []


@pytest.mark.parametrize(
    ("body", "headers"),
    [
        (b"not json at all", {"content-type": "text/plain"}),
        (b"[" * 50_000, JSON_CT),  # nesting deep enough to hit the recursion limit
        (b"\xff\xfe", JSON_CT),  # not UTF-8
    ],
)
def test_an_unreadable_body_is_refused_rather_than_crashing(client, captured_writes, body, headers):
    # A public endpoint gets posted every shape there is. None of them is a 500.
    assert client.post("/feedback", content=body, headers=headers).status_code == 422
    assert captured_writes == []


@pytest.mark.parametrize("body", [b"[1, 2]", b'"hi"', b"42", b"null"])
def test_a_json_body_that_is_not_an_object_is_refused(client, captured_writes, body):
    # A list, string, number or null root carries no fields to build a rating from.
    assert client.post("/feedback", content=body, headers=JSON_CT).status_code == 422
    assert captured_writes == []


def test_a_file_part_is_not_read_as_a_text_field(client, captured_writes):
    # `curl -F 'comment=@/etc/hostname'` sends a file where text belongs. The part
    # is dropped, so the rating stores as if no comment had been given, rather
    # than quietly storing the contents of whatever file was named.
    response = client.post(
        "/feedback", files={**_multipart(comment=None), "comment": ("host", b"secret")}
    )
    assert response.status_code == 201
    assert captured_writes[-1].comment is None


def test_a_rating_no_destination_accepted_answers_503(client, no_destination_accepts):
    # Never tell a caller "stored" when nothing was.
    assert client.post("/feedback", files=_multipart()).status_code == 503
