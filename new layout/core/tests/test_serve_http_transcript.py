"""POST /transcript: a consented trajectory, as raw .jsonl or as ready-made ATIF.

`client`, `captured_writes` and `no_destination_accepts` come from conftest.py.
"""

from __future__ import annotations

import json

import pytest
from api import ingest_records

RAW_JSONL = "\n".join(
    json.dumps(line)
    for line in [
        {"type": "user", "message": {"role": "user", "content": "hi"}},
        {
            "type": "assistant",
            "message": {"role": "assistant", "content": [{"type": "text", "text": "hello"}]},
        },
    ]
)

# The hook posts the ids with `curl --form-string` and streams the raw .jsonl
# into the `transcript` field, all in one multipart body.
FORM = {
    "skill_name": "goodbye",
    "agent": "claude-code claude-opus-4-8",
    "session_id": "sess-1",
    "request_id": "req-1",
}


def _multipart(**overrides) -> dict:
    fields = {**FORM, "transcript": RAW_JSONL, **overrides}
    return {name: (None, value) for name, value in fields.items()}


def test_a_form_post_converts_the_session_file_and_stores_it(client, captured_writes):
    response = client.post("/transcript", files=_multipart())
    assert response.status_code == 201
    assert response.json() == {"status": "stored"}
    record = captured_writes[-1]
    assert record.skill_name == "goodbye"
    assert record.request_id == "req-1"
    assert record.atif["session_id"] == "sess-1"
    assert [s["source"] for s in record.atif["steps"]] == ["user", "agent"]


def test_a_multi_megabyte_upload_is_read_rather_than_refused_unread(client, captured_writes):
    """A trajectory is one multipart field, and the hook will send up to 4 MiB.

    Starlette caps a single part at 1 MiB by default and answers 400 long before
    max_body_bytes is consulted, which would reject most real sessions. The cap
    has to be raised to our own body limit when the form is read.
    """
    line = json.dumps({"type": "user", "message": {"role": "user", "content": "x" * 200}})
    big = "\n".join([line] * (2 * 1024 * 1024 // len(line)))
    assert len(big) > 1024 * 1024  # past Starlette's default, so the cap is in play

    response = client.post("/transcript", files=_multipart(transcript=big))
    assert response.status_code == 201  # a 400 here means the part was refused unread
    # It arrived whole. Being past max_transcript_bytes, it stores as the stub.
    assert captured_writes[-1].atif["oversized"]["byte_size"] > 1024 * 1024


def test_a_json_post_may_carry_a_ready_made_trajectory(client, captured_writes):
    # The seeder builds ATIF itself rather than replaying a Claude Code session.
    response = client.post(
        "/transcript",
        json={
            "session_id": "s9",
            "skill_name": "cheerful",
            "agent": "claude-code",
            "atif": {"schema_version": "ATIF-v1.7", "steps": []},
            "request_id": "r9",
        },
    )
    assert response.status_code == 201
    assert captured_writes[-1].atif == {"schema_version": "ATIF-v1.7", "steps": []}


def test_a_blank_transcript_field_is_refused(client, captured_writes):
    assert client.post("/transcript", files=_multipart(transcript="   ")).status_code == 422
    assert captured_writes == []


def test_a_json_body_that_is_not_an_object_is_refused(client, captured_writes):
    response = client.post(
        "/transcript", content=b"[1, 2]", headers={"content-type": "application/json"}
    )
    assert response.status_code == 422
    assert captured_writes == []


def test_a_file_part_is_not_read_as_a_text_field(client, captured_writes):
    # The hook streams the .jsonl as text (`curl --form 'transcript=<-'`). A part
    # uploaded as a file is dropped, leaving nothing to convert.
    response = client.post(
        "/transcript", files={**_multipart(), "transcript": ("s.jsonl", RAW_JSONL.encode())}
    )
    assert response.status_code == 422
    assert captured_writes == []


def test_a_redaction_failure_answers_502_not_503(client, captured_writes, monkeypatch):
    """The two failures mean different things to whoever is reading the logs.

    503 says every destination refused the record. 502 says the record never got
    that far, because masking it failed and fail-closed means dropping it. The
    rating was already stored by its own request either way.
    """

    def boom(_atif):
        raise RuntimeError("language service down")

    monkeypatch.setattr(ingest_records, "redact_atif", boom)
    assert client.post("/transcript", files=_multipart()).status_code == 502
    assert captured_writes == []


def test_a_trajectory_no_destination_accepted_answers_503(client, no_destination_accepts):
    assert client.post("/transcript", files=_multipart()).status_code == 503


@pytest.mark.parametrize("missing", ["skill_name", "agent"])
def test_the_fields_that_identify_the_run_are_required(client, captured_writes, missing):
    fields = {name: value for name, value in _multipart().items() if name != missing}
    assert client.post("/transcript", files=fields).status_code == 422
    assert captured_writes == []
