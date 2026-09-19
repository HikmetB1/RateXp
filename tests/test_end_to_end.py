"""Full round-trips: what is posted to core shows up on the dashboard.

These are the tests that prove the whole app works together - core takes a
rating (and a consented trajectory) over plain HTTP and writes it, the dashboard
reads the same data back out. The last test goes one step further and drives the
*shipped* hook script itself, so the exact bytes a real skill puts on the wire
are the ones being checked.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import time
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
CANONICAL_HOOK = ROOT / "core" / "ratexp.sh"
PLACEHOLDER = "'__RATEXP_URL__'"

# The hook refuses to post anywhere but https or the loopback host.
LOOPBACK_HTTP = re.compile(r"^http://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?(/|$)")

# core keeps a trajectory whole only up to max_transcript_bytes (core/config.yaml,
# 256 KiB) and stores a meta-only stub for anything bigger. This padding is safely
# over that while staying under the 1 MiB per-part limit the form parser enforces.
OVERSIZE_PAD_BYTES = 600_000

# Driving the hook means really running it: a POSIX shell plus the tools it uses.
needs_shell = pytest.mark.skipif(
    os.name != "posix" or not (shutil.which("bash") and shutil.which("curl")),
    reason="running the shipped hook needs a POSIX system with bash and curl",
)


def _find(rows: list[dict], skill_name: str) -> dict | None:
    return next((r for r in rows if r.get("skill_name") == skill_name), None)


def _get(http, url: str, **params):
    """GET a dashboard endpoint and return its JSON."""
    r = http.get(url, params=params)
    assert r.status_code == 200
    return r.json()


def _poll(fetch, ready=bool):
    """Retry briefly to absorb write/read lag; returns the last value fetched."""
    found = None
    for _ in range(5):
        found = fetch()
        if ready(found):
            break
        time.sleep(0.5)
    return found


def test_feedback_round_trip(app_url, http, post_feedback):
    # A unique skill name so we can pick our row out of the dashboard list.
    skill = f"e2e-{uuid.uuid4().hex[:8]}"

    # 1. Core stores it.
    r = post_feedback(
        session_id=str(uuid.uuid4()),
        request_id=str(uuid.uuid4()),
        skill_name=skill,
        agent="claude-code",
        score=2,
        comment="end-to-end ok",
    )
    assert r.status_code == 201

    # 2. The dashboard reads it back.
    row = _poll(lambda: _find(_get(http, f"{app_url}/feedback", full="true"), skill))
    assert row is not None, f"{skill} never appeared on the dashboard"
    assert row["score"] == 2
    assert row["comment"] == "end-to-end ok"


def test_top_skills_counts_our_feedback(app_url, http, post_feedback):
    skill = f"e2e-{uuid.uuid4().hex[:8]}"

    # One good (1) and one bad (2) rating for the same skill.
    for score in (1, 2):
        r = post_feedback(
            session_id=str(uuid.uuid4()),
            request_id=str(uuid.uuid4()),
            skill_name=skill,
            agent="claude-code",
            score=score,
        )
        assert r.status_code == 201

    entry = _poll(
        lambda: next(
            (
                s
                for s in _get(http, f"{app_url}/stats/top-skills", limit=100)["skills"]
                if s.get("skill_name") == skill
            ),
            None,
        )
    )
    assert entry is not None, f"{skill} missing from top-skills"
    assert entry["total"] >= 2  # both ratings counted


def test_trajectory_round_trip(app_url, http, post_feedback, post_transcript):
    """A feedback row and its stored transcript must stay linked on the dashboard.

    The dashboard's /snapshot is what the UI shows; it must return the feedback row
    together with the matching transcript (the "Trajectory"). This guards the bug
    where snapshot fetched the newest transcripts unrelated to the shown feedback.
    """
    session_id = str(uuid.uuid4())
    request_id = str(uuid.uuid4())
    skill = f"e2e-{uuid.uuid4().hex[:8]}"
    shared = {
        "session_id": session_id,
        "request_id": request_id,
        "skill_name": skill,
        "agent": "claude-code",
    }

    # Submit the rating, then its consented transcript - same ids, as a real run does.
    assert post_feedback(**shared, score=1).status_code == 201
    atif = {
        "agent": {"name": "claude-code", "model_name": "test"},
        "session_id": session_id,
        "steps": [{"source": "user", "message": "do the thing", "step_id": 1}],
    }
    assert post_transcript(**shared, atif=atif).status_code == 201

    # The dashboard snapshot must carry our feedback AND its transcript, linked by id.
    def _linked():
        data = _get(http, f"{app_url}/snapshot")
        return (
            _find(data["feedback"], skill),
            next((t for t in data["transcripts"] if t.get("request_id") == request_id), None),
        )

    fb, tx = _poll(_linked, ready=all)
    assert fb is not None, "feedback row missing from snapshot"
    assert tx is not None, "trajectory missing - feedback and transcript not linked in snapshot"
    assert tx["session_id"] == session_id
    assert tx["atif"]["steps"][0]["message"] == "do the thing"


# --- the shipped hook, driven the way Claude Code drives it -------------------
# Everything above posts to core from Python. The test below instead runs the real
# ratexp.sh: it does its own answer parsing and its own curl calls, so this checks
# the wire itself - hook event in, row on the dashboard out.


@pytest.fixture
def skill_dir(tmp_path, core_url) -> Path:
    """A throwaway skill folder holding the canonical hook, aimed at the live core.

    The hook takes its skill name from the folder it sits in, so this unique folder
    name is also the name the rating lands under on the dashboard.
    """
    if not (core_url.startswith("https://") or LOOPBACK_HTTP.match(core_url)):
        pytest.skip(f"the hook only posts to https or loopback - core is at {core_url}")
    folder = tmp_path / f"e2e-hook-{uuid.uuid4().hex[:8]}"
    folder.mkdir()
    source = CANONICAL_HOOK.read_text(encoding="utf-8")
    assert PLACEHOLDER in source, f"{CANONICAL_HOOK} no longer carries {PLACEHOLDER}"
    (folder / "ratexp.sh").write_text(
        source.replace(PLACEHOLDER, shlex.quote(core_url)), encoding="utf-8"
    )
    return folder


def _session_jsonl(pad: str = "") -> str:
    """A minimal Claude Code session transcript, optionally padded to a size."""
    lines = [
        {
            "type": "user",
            "message": {"role": "user", "content": "write me a poem"},
            "timestamp": "2026-01-01T00:00:00Z",
        },
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "model": "claude-test",
                "content": [{"type": "text", "text": "roses are red" + pad}],
            },
            "timestamp": "2026-01-01T00:00:01Z",
        },
    ]
    return "".join(json.dumps(line) + "\n" for line in lines)


def _hook_env(state_dir: Path) -> dict:
    """Environment for a hook run: its own state, and a survey on every run."""
    env = dict(os.environ)
    env["XDG_STATE_HOME"] = str(state_dir)
    env["RATEXP_EVERY"] = "1"  # ask on this run
    env.pop("RATEXP_URL", None)  # use the URL baked into this copy
    return env


def _run_hook(script: Path, env: dict, payload: dict) -> str:
    """Feed one Claude Code hook event to the script on stdin; return its stdout."""
    done = subprocess.run(
        ["bash", str(script)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    return done.stdout


def _rate_with_hook(script: Path, env: dict, session_id: str, transcript: Path, answer: str) -> str:
    """Replay the three hook events Claude Code fires around the rating picker.

    Stop hands the model a picker to draw, PreToolUse checks the model drew that
    exact picker, and PostToolUse carries the user's answer - the one event that
    posts anything. Returns the hook's PostToolUse output (its delivery report).
    """
    # session_id, transcript_path and cwd ride on every hook event, so send them on
    # all three - the upload reads the file to send from the event that consents.
    common = {
        "session_id": session_id,
        "transcript_path": str(transcript),
        "cwd": str(script.parent),
    }
    stop = _run_hook(script, env, {"hook_event_name": "Stop", **common})
    blocked = json.loads(stop)
    assert blocked["decision"] == "block", stop
    # The reason is one line of instruction, then the picker the model must draw.
    picker = json.loads(blocked["reason"].split("\n", 1)[1])
    question = picker["questions"][0]["question"]
    tool_use_id = f"toolu_{uuid.uuid4().hex[:16]}"

    pre = _run_hook(
        script,
        env,
        {
            "hook_event_name": "PreToolUse",
            "tool_name": "AskUserQuestion",
            "tool_use_id": tool_use_id,
            "tool_input": picker,
            **common,
        },
    )
    assert "deny" not in pre, pre  # the picker came from the hook; it must be accepted

    return _run_hook(
        script,
        env,
        {
            "hook_event_name": "PostToolUse",
            "tool_name": "AskUserQuestion",
            "tool_use_id": tool_use_id,
            "tool_input": picker,
            "tool_response": {"answers": {question: answer}},
            **common,
        },
    )


@needs_shell
@pytest.mark.parametrize("oversized", [False, True], ids=["normal", "oversized"])
@pytest.mark.parametrize("share", [True, False], ids=["share", "no-share"])
def test_shipped_hook_round_trip(app_url, http, tmp_path, skill_dir, share, oversized):
    """The real hook script, run as Claude Code runs it, lands on the dashboard.

    The rating always goes; the transcript goes only when the user ticked consent.
    An oversized transcript still uploads, but core stores it as the meta-only stub.
    """
    session_id = str(uuid.uuid4())
    transcript = tmp_path / "session.jsonl"
    transcript.write_text(
        _session_jsonl("x" * OVERSIZE_PAD_BYTES if oversized else ""), encoding="utf-8"
    )
    answer = "Good, Yes, store trajectory" if share else "Good, No, do not store"

    report = _rate_with_hook(
        skill_dir / "ratexp.sh",
        _hook_env(tmp_path / "state"),
        session_id,
        transcript,
        answer,
    )
    # The hook reports only what it actually got a 201 for.
    message = json.loads(report)["systemMessage"]
    if share:
        assert "feedback and transcript accepted" in message, message
    else:
        assert "Transcript kept private" in message, message

    # 1. The rating is on the dashboard, under the skill folder's name.
    row = _poll(lambda: _find(_get(http, f"{app_url}/feedback", full="true"), skill_dir.name))
    assert row is not None, f"{skill_dir.name} never appeared on the dashboard"
    assert row["score"] == 1  # "Good"
    assert row["session_id"] == session_id

    # 2. The transcript is stored only when consent was given. The hook finished
    #    both requests before it returned, so what is stored now is all there is.
    def _stored():
        return next(
            (
                t
                for t in _get(http, f"{app_url}/transcript", full="true")
                if t.get("session_id") == session_id
            ),
            None,
        )

    if not share:
        assert _stored() is None, "transcript uploaded without consent"
        return
    tx = _poll(_stored)
    assert tx is not None, "consented transcript missing from the dashboard"
    assert tx["request_id"] == row["request_id"]  # rating and trajectory stay linked
    if oversized:
        # Too big to keep whole: a meta-only stub, no conversation text.
        assert "oversized" in tx["atif"]
        assert tx["atif"]["steps"] == []
    else:
        assert tx["atif"]["steps"], "stored trajectory has no steps"
