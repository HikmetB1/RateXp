"""Full round-trips: what is posted to core shows up on the dashboard.

These are the tests that prove the whole app works together - core takes a
rating (and a consented trajectory) over plain HTTP and writes it, the dashboard
reads the same data back out. The last tests go one step further and drive the
hook script as the RateXp plugin runs it, so the exact bytes a real install puts on
the wire are the ones being checked.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
# The Claude Code plugin, as its own repo holds it and Claude Code installs it.
CLAUDE_PLUGIN = ROOT / "plugins" / "claude-code"

# The hook refuses to post anywhere but https or the loopback host.
LOOPBACK_HTTP = re.compile(r"^http://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?(/|$)")

# core keeps a trajectory whole only up to max_transcript_bytes (core/config.yaml,
# 256 KiB) and stores a meta-only stub for anything bigger. This padding is safely
# over that while staying under the 1 MiB per-part limit the form parser enforces.
OVERSIZE_PAD_BYTES = 600_000

# The columns the Dashboard view draws each panel kind from.
DASHBOARD_KIND_COLUMNS = {
    "number": {"value"},
    "line": {"day", "good", "bad"},
    "bar": {"name", "total", "good", "bad", "percent_good"},
}

# Driving the hook means really running it: a POSIX shell plus the tools it uses.
needs_shell = pytest.mark.skipif(
    os.name != "posix" or not (shutil.which("bash") and shutil.which("curl")),
    reason="running the hook needs a POSIX system with bash and curl",
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
        eval_name="human-satisfaction",
        score=2,
        comment="end-to-end ok",
    )
    assert r.status_code == 201

    # 2. The dashboard reads it back, with the eval it answered.
    row = _poll(lambda: _find(_get(http, f"{app_url}/feedback", full="true"), skill))
    assert row is not None, f"{skill} never appeared on the dashboard"
    assert row["eval_name"] == "human-satisfaction"
    assert row["score"] == 2
    assert row["comment"] == "end-to-end ok"


def test_trajectory_round_trip(app_url, http, post_feedback, post_transcript):
    """A feedback row and its stored transcript must stay linked on the dashboard.

    The dashboard's /snapshot is what the UI shows; it must return the feedback row
    together with the matching transcript (the "Trajectory"), not whichever
    transcripts happen to be newest.
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


def test_dashboard_view_round_trip(app_url, http, post_feedback, post_transcript):
    """Every panel the Dashboard view lists runs on the stored data, unfiltered and filtered
    to a new skill, which counts its one rating; the export carries that rating with its
    conversation."""
    session_id = str(uuid.uuid4())
    request_id = str(uuid.uuid4())
    skill = f"e2e-{uuid.uuid4().hex[:8]}"
    shared = {
        "session_id": session_id,
        "request_id": request_id,
        "skill_name": skill,
        "agent": "claude-code",
    }
    assert post_feedback(**shared, eval_name="human-satisfaction", score=1).status_code == 201
    atif = {
        "agent": {"name": "claude-code", "model_name": "test"},
        "session_id": session_id,
        "steps": [{"source": "user", "message": "chart the thing", "step_id": 1}],
    }
    assert post_transcript(**shared, atif=atif).status_code == 201

    info = _get(http, f"{app_url}/dashboard")
    if not info["available"]:
        pytest.skip(info["reason"])

    def _panel(panel: dict, filters: dict) -> dict:
        r = http.post(f"{app_url}/dashboard/panel", json={"panel": panel["id"], "filters": filters})
        assert r.status_code == 200, (panel["id"], r.text)
        body = r.json()
        # A table panel names its own columns; the other kinds draw from fixed ones.
        needed = DASHBOARD_KIND_COLUMNS.get(panel["kind"], set())
        assert needed <= set(body["columns"]), (panel["id"], body["columns"])
        return body

    for panel in info["panels"]:
        _panel(panel, {})
        _panel(panel, {"skill": skill})

    total = next(p for p in info["panels"] if p["id"] == "total_ratings")
    counted = _poll(lambda: _panel(total, {"skill": skill})["rows"], ready=lambda r: r == [[1]])
    assert counted == [[1]], f"total_ratings filtered to {skill} reads {counted}"

    exported = _poll(
        lambda: _get(http, f"{app_url}/dashboard/export", skill=skill),
        ready=lambda rows: rows and rows[0]["conversation"],
    )
    assert [row["request_id"] for row in exported] == [request_id]
    assert exported[0]["conversation"]["steps"][0]["message"] == "chart the thing"


# --- the real hook, driven the way Claude Code drives it -----------------------
# Everything above posts to core from Python. The test below instead runs the real
# ratexp-claude.sh rating a skill, as the plugin's rating panel has it send: it makes
# its own curl calls, so this checks the wire itself - answers in, row on the
# dashboard out.


@pytest.fixture
def hook(tmp_path, core_url, http):
    """The Claude Code hook as the RateXp plugin runs it, aimed at the live core, after a
    session start: core has sent its surveys. Returns the script, the environment it
    runs in, and the eval core asks by default."""
    if not (core_url.startswith("https://") or LOOPBACK_HTTP.match(core_url)):
        pytest.skip(f"the hook only posts to https or loopback - core is at {core_url}")
    plugin = tmp_path / "plugin"
    shutil.copytree(CLAUDE_PLUGIN, plugin)
    script = plugin / "ratexp-claude.sh"
    env = {**os.environ, "XDG_STATE_HOME": str(tmp_path / "state"), "RATEXP_URL": core_url}
    started = _run_hook(
        script,
        env,
        {"hook_event_name": "SessionStart", "session_id": str(uuid.uuid4()), "cwd": str(plugin)},
    )
    assert started == "", "the plugin's version is the newest, so there is no update notice"
    settings = _get(http, f"{core_url}/hook-settings")
    default = next(e for e in settings["evals"] if e["name"] == settings["default_eval"])
    return script, env, default


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


def _rate_with_panel(
    script: Path,
    env: dict,
    session_id: str,
    transcript: Path,
    run: str,
    skill: str,
    eval_name: str,
    share: bool,
) -> str:
    """Replay what a real install does around a skill's run and its rating.

    /<skill> starts the run and its turns land in the transcript; then the rating
    panel's Send hands the answers to the script's `send` - the one call that posts
    anything. Returns the line the script prints for the user.
    """
    common = {
        "session_id": session_id,
        "transcript_path": str(transcript),
        "cwd": str(script.parent.parent),
    }
    transcript.write_text("", encoding="utf-8")
    _run_hook(
        script, env, {"hook_event_name": "UserPromptExpansion", "command_name": skill, **common}
    )
    transcript.write_text(run, encoding="utf-8")
    fields = [str(transcript), "yes" if share else "no", skill, eval_name, "good", ""]
    done = subprocess.run(
        ["bash", str(script), "send", session_id],
        input=b"".join(field.encode() + b"\0" for field in fields),
        capture_output=True,
        env=env,
        timeout=120,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    return done.stdout.decode()


@needs_shell
@pytest.mark.parametrize("oversized", [False, True], ids=["normal", "oversized"])
@pytest.mark.parametrize("share", [True, False], ids=["share", "no-share"])
def test_hook_round_trip(app_url, http, tmp_path, hook, share, oversized):
    """The real hook script, rating a skill as the rating panel has it, lands on the dashboard.

    The rating always goes; the transcript goes only when the user ticked consent.
    An oversized transcript still uploads, but core stores it as the meta-only stub.
    """
    script, env, default = hook
    session_id = str(uuid.uuid4())
    skill = f"e2e-skill-{uuid.uuid4().hex[:8]}"  # the name the rating lands under
    message = _rate_with_panel(
        script,
        env,
        session_id,
        tmp_path / "session.jsonl",
        _session_jsonl("x" * OVERSIZE_PAD_BYTES if oversized else ""),
        skill,
        default["name"],
        share,
    )
    # The hook reports only what it actually got a 201 for.
    if share:
        assert "feedback and transcript accepted" in message, message
    else:
        assert "Transcript kept private" in message, message

    # 1. The rating is on the dashboard, under the skill's name and the eval asked.
    row = _poll(lambda: _find(_get(http, f"{app_url}/feedback", full="true"), skill))
    assert row is not None, f"{skill} never appeared on the dashboard"
    assert row["score"] == 1  # the good answer
    assert row["eval_name"] == default["name"]
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
