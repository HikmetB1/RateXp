"""POST /transcript + ingest_transcript - convert, size-limit, redact, store.

Also covers GET /ratexp.sh, the hook script core hands out with its own URL baked in.
"""

from __future__ import annotations

import json
import os

import ingest
import pytest
from atif import claude_jsonl_to_atif
from models import Transcript

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

AGENT = "claude-code claude-opus-4-8"

# The hook posts the ids with `curl --form-string` and streams the raw .jsonl
# into the `transcript` field - all one multipart body.
FORM = {
    "skill_name": "goodbye",
    "agent": AGENT,
    "session_id": "sess-1",
    "request_id": "req-1",
}


def _multipart(**overrides) -> dict:
    """FORM + the raw transcript as httpx multipart fields."""
    fields = {**FORM, "transcript": RAW_JSONL, **overrides}
    return {name: (None, value) for name, value in fields.items()}


def _record(**overrides) -> Transcript:
    """A Transcript like the one the server builds from that form body."""
    base = {
        **FORM,
        "atif": claude_jsonl_to_atif(RAW_JSONL, session_id="sess-1", agent=AGENT),
    }
    base.update(overrides)
    return Transcript(**base)


# --- POST /transcript ---------------------------------------------------------


def test_http_transcript_form_happy(client):
    c, captured = client
    r = c.post("/transcript", files=_multipart())
    assert r.status_code == 201
    assert r.json() == {"status": "stored"}
    rec = captured[-1]
    assert rec.skill_name == "goodbye"
    assert rec.request_id == "req-1"
    assert rec.schema_version == "ATIF-v1.7"
    assert rec.atif["session_id"] == "sess-1"
    assert [s["source"] for s in rec.atif["steps"]] == ["user", "agent"]


def test_http_transcript_form_accepts_a_multi_megabyte_upload(client):
    """A consented transcript is one multipart field, and the hook allows 4 MiB.

    Starlette caps a single part at 1 MiB by default, which would reject most real
    sessions with a 400 long before max_body_bytes applied - so the cap is raised
    to our own body limit (see server._read_body).
    """
    c, captured = client
    line = json.dumps({"type": "user", "message": {"role": "user", "content": "x" * 200}})
    big = "\n".join([line] * (2 * 1024 * 1024 // len(line)))  # ~2 MiB, over the default
    assert len(big) > 1024 * 1024
    r = c.post("/transcript", files=_multipart(transcript=big))
    assert r.status_code == 201  # a 400 here means the part was refused unread
    # It arrived intact; being past max_transcript_bytes it stores as the stub.
    assert captured[-1].atif["oversized"]["byte_size"] > 1024 * 1024


def test_http_transcript_json_atif_body(client):
    c, captured = client
    r = c.post(
        "/transcript",
        json={
            "session_id": "s9",
            "skill_name": "cheerful",
            "agent": "claude-code",
            "atif": {"schema_version": "ATIF-v1.7", "steps": []},
            "request_id": "r9",
        },
    )
    assert r.status_code == 201
    assert captured[-1].atif == {"schema_version": "ATIF-v1.7", "steps": []}


def test_http_transcript_empty_rejected(client):
    c, captured = client
    assert c.post("/transcript", files=_multipart(transcript="   ")).status_code == 422
    assert captured == []


def test_http_transcript_json_root_must_be_an_object(client):
    # A bare list has no fields to read, and saying so is a 422 like any other
    # unusable body.
    c, captured = client
    r = c.post("/transcript", content=b"[1, 2]", headers={"content-type": "application/json"})
    assert r.status_code == 422
    assert captured == []


def test_http_transcript_file_part_is_not_a_text_field(client):
    # The hook streams the .jsonl as a text field (curl --form 'transcript=<-'). A
    # part uploaded as a file is dropped, leaving nothing to convert.
    c, captured = client
    r = c.post("/transcript", files={**_multipart(), "transcript": ("s.jsonl", RAW_JSONL.encode())})
    assert r.status_code == 422
    assert captured == []


# --- ingest_transcript --------------------------------------------------------


def test_transcript_created_at_autofilled(store_stub):
    ingest.ingest_transcript(_record())
    assert store_stub[-1].created_at.endswith("Z")


def test_transcript_small_stored_in_full(store_stub):
    ingest.ingest_transcript(_record())
    atif = store_stub[-1].atif
    assert "oversized" not in atif  # under the limit -> full trajectory kept
    assert [s["source"] for s in atif["steps"]] == ["user", "agent"]


def test_transcript_oversized_stored_as_stub(store_stub, monkeypatch):
    # Shrink the limit so a normal transcript counts as oversized.
    monkeypatch.setattr(ingest, "MAX_TRANSCRIPT_BYTES", 10)
    # Redaction must be skipped for the meta-only stub - blow up if it's reached.
    monkeypatch.setattr(
        ingest, "redact_atif", lambda atif: (_ for _ in ()).throw(AssertionError("redacted"))
    )
    ingest.ingest_transcript(_record())
    atif = store_stub[-1].atif
    assert atif["steps"] == []  # bulky trajectory dropped
    assert atif["oversized"]["limit_bytes"] == 10
    assert atif["oversized"]["byte_size"] > 10
    assert "final_metrics" in atif  # token/step totals kept


def test_transcript_redaction_applied_before_store(store_stub, monkeypatch):
    monkeypatch.setattr(ingest, "redact_atif", lambda atif: {**atif, "redacted": True})
    ingest.ingest_transcript(_record())
    assert store_stub[-1].atif.get("redacted") is True


def test_transcript_redaction_failure_propagates(store_stub, monkeypatch):
    def boom(_atif):
        raise RuntimeError("azure down")

    monkeypatch.setattr(ingest, "redact_atif", boom)
    with pytest.raises(RuntimeError):
        ingest.ingest_transcript(_record())
    assert store_stub == []  # nothing stored when masking fails


# --- GET /ratexp.sh -----------------------------------------------------------


def _public_url() -> str:
    """The base URL core bakes into the script it serves (RATEXP_PUBLIC_URL)."""
    import server

    configured = getattr(server, "PUBLIC_URL", None) or os.environ.get(
        "RATEXP_PUBLIC_URL", "http://localhost:8000"
    )
    return configured.rstrip("/")


def test_ratexp_sh_is_served(client):
    c, _ = client
    r = c.get("/ratexp.sh")
    assert r.status_code == 200
    assert "__RATEXP_URL__" not in r.text  # placeholder swapped for a real URL
    assert _public_url() in r.text


def test_ratexp_sh_carries_the_configured_survey_frequency(client):
    """How often to ask is a deployment setting, stamped into the script served.

    A skill therefore works as soon as it is copied, with no environment variable
    to set; the user's own RATEXP_EVERY still wins at run time.
    """
    from config import DEFAULT_SURVEY_EVERY

    c, _ = client
    text = c.get("/ratexp.sh").text
    assert "__RATEXP_EVERY__" not in text
    assert f"DEFAULT_EVERY={DEFAULT_SURVEY_EVERY}" in text
