"""Opt-in check of the production RateXp with the real Claude Code and Cursor CLIs.

Never runs by default. Turn it on after deploying a change to the plugins' files
(plugins/claude-code/, plugins/cursor/):

    RATEXP_PROD_AGENTS=1 uv run --no-project --with-requirements tests/requirements.txt \\
        pytest tests/test_agents_production.py -v

RATEXP_AGENTS_ENVIRONMENT=dev runs the same checks on dev (ratexp-dev-core and
ratexp-dev-app), before the tested images are copied to prod; "production" below then
means dev.

Each test loads the RateXp plugin into the agent for the session (`--plugin-dir`), as an
install loads it, runs the agent in a scratch project with `-p`, types /ratexp:rate,
answers the survey the way a click would - good, and store the conversation - and finds
the rating and its trajectory on the production dashboard. Your own ~/.claude is never
changed. The plugin's Cursor hook adds a stop hook that does nothing to
~/.cursor/hooks.json when that file has none; the Cursor test puts the file back as it
was.

Needs a logged-in `claude` and `cursor-agent`, and a few cents of model use. Every run
leaves its ratings and their short, masked test conversations in production - on the
dashboard and in every destination the production core writes to - each rating marked
with the comment "ratexp-live-test <time>".

Only the click is scripted: nobody is there to tick the picker, so the test hands the
hook the answer a click produces. Everything after it - the post, core, the dashboard -
is the real path.
"""

from __future__ import annotations

import glob
import json
import os
import shutil
import subprocess
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("RATEXP_PROD_AGENTS") != "1",
    reason="set RATEXP_PROD_AGENTS=1 to run the real Claude Code and Cursor CLIs on production"
    " (or on dev, with RATEXP_AGENTS_ENVIRONMENT=dev)",
)

# The name base that infra/main.tf gives each environment's web apps.
NAME_BASES = {"prod": "ratexp", "dev": "ratexp-dev"}
ENVIRONMENT = os.environ.get("RATEXP_AGENTS_ENVIRONMENT", "prod")
if ENVIRONMENT not in NAME_BASES:
    raise pytest.UsageError(f"RATEXP_AGENTS_ENVIRONMENT must be one of {', '.join(NAME_BASES)}")
CORE_URL = f"https://{NAME_BASES[ENVIRONMENT]}-core.azurewebsites.net"
APP_URL = f"https://{NAME_BASES[ENVIRONMENT]}-app.azurewebsites.net"
# The agents' turns, kept short and cheap; ten minutes covers a slow model.
AGENT_TIMEOUT = 600
CLAUDE_MODEL = os.environ.get("RATEXP_LIVE_CLAUDE_MODEL", "haiku")


def ratexp_comment(agent: str) -> str:
    """The comment that marks a test rating, wherever it ends up."""
    return f"ratexp-live-test {datetime.now(UTC):%Y-%m-%dT%H:%M:%SZ} {agent}"


def run(args, cwd, env=None, stdin=None, timeout=120) -> subprocess.CompletedProcess:
    return subprocess.run(
        args,
        cwd=cwd,
        env={**os.environ, **(env or {})},
        input=stdin,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def dashboard_rows(path) -> list[dict]:
    """The production dashboard's newest rows at `path`, or none while it is unreachable.

    The shared production plan drops the odd request under load; a wait that hits one
    keeps waiting rather than failing the whole run on it.
    """
    try:
        return httpx.get(f"{APP_URL}{path}", params={"full": "true"}, timeout=30).json()
    except (httpx.HTTPError, ValueError):
        return []


def rating_on_dashboard(comment) -> dict:
    """The production dashboard's row for a test rating, waiting for it to arrive."""
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        found = [r for r in dashboard_rows("/feedback") if r.get("comment") == comment]
        if found:
            return found[0]
        time.sleep(2)
    pytest.fail(f"no rating with comment {comment!r} reached the dashboard")


def trajectory_on_dashboard(row) -> dict:
    """The production dashboard's stored conversation for a rating, waiting for it.

    A cold core can take longer to mask a conversation than the hook waits for its
    answer, so the dashboard - not the hook's message - says whether it was stored.
    """
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        found = [
            t for t in dashboard_rows("/transcript") if t.get("request_id") == row["request_id"]
        ]
        if found:
            return found[0]
        time.sleep(3)
    pytest.fail(f"no trajectory for request {row['request_id']} reached the dashboard")


@pytest.fixture
def project(tmp_path):
    """A scratch project, and a state folder of its own for the hooks."""
    (tmp_path / "project").mkdir()
    (tmp_path / "state").mkdir()
    return tmp_path


@pytest.fixture
def agent_cli():
    """Fail loudly when an agent CLI is missing: the run was asked for on purpose."""

    def _need(name):
        assert shutil.which(name), f"{name} is not on PATH"
        return name

    return _need


def plugin_env(state: Path) -> dict:
    """The hooks' own state folder, and production's core: the plugin talks to the
    hosted core unless RATEXP_URL names another."""
    env = {"XDG_STATE_HOME": str(state)}
    if ENVIRONMENT != "prod":
        env["RATEXP_URL"] = CORE_URL
    return env


def plugin_copy(folder: Path, agent: str) -> Path:
    """An agent's plugin as its marketplace install gets it: the files git tracks in
    plugins/<agent>/, which the release step sends to that agent's plugin repo."""
    root = Path(__file__).resolve().parent.parent / "plugins" / agent
    listed = run(["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"], root)
    for name in filter(None, listed.stdout.split("\0")):
        if (root / name).is_file():
            (folder / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(root / name, folder / name)
    return folder


def test_claude_code_plugin_survey_and_rating(project, agent_cli):
    """The RateXp plugin, loaded for the session as an install loads it, on production."""
    claude = agent_cli("claude")
    folder = project / "project"
    state = project / "state"
    plugin = plugin_copy(project / "plugin", "claude-code")
    env = plugin_env(state)
    # Only the project's settings, so a RateXp you installed yourself stays out of it.
    session = [claude, "-p", "--model", CLAUDE_MODEL, "--setting-sources", "project"]
    session += ["--plugin-dir", str(plugin)]

    # A first turn, as core leaves the survey out of a trajectory: a session holding
    # only /ratexp:rate would rate nothing. Its session start asks core for the surveys.
    session_id = str(uuid.uuid4())
    first = run(
        [*session, "--session-id", session_id, "Reply with just OK."],
        folder,
        env,
        timeout=AGENT_TIMEOUT,
    )
    assert first.returncode == 0, first.stderr
    assert list((state / "ratexp").glob("settings-*")), "the plugin did not keep core's surveys"

    # /ratexp:rate makes the hook ask. The picker tool is off: with nobody to answer, a
    # failed picker would spend the survey before the scripted click.
    second = run(
        # The prompt goes first: --disallowedTools takes every word after it as a tool.
        [*session, "/ratexp:rate", "--resume", session_id, "--disallowedTools", "AskUserQuestion"],
        folder,
        env,
        timeout=AGENT_TIMEOUT,
    )
    assert second.returncode == 0, second.stderr
    pending = [
        p for p in glob.glob(f"{state}/ratexp/*-{session_id}/runs/*/pending") if os.path.getsize(p)
    ]
    assert pending, "the Stop hook asked for no survey"
    fields = Path(pending[0]).read_bytes().split(b"\0")
    picker, transcript = json.loads(fields[2]), fields[3].decode()
    assert f"to {CORE_URL}" in json.dumps(picker), "the plugin sends to another core"

    # The click, through the plugin's own PostToolUse hook.
    comment = ratexp_comment("claude plugin")
    question = picker["questions"][0]
    good = question["options"][0]["label"]
    manifest = json.loads((plugin / ".claude-plugin/plugin.json").read_text())
    command = manifest["hooks"]["PostToolUse"][0]["hooks"][0]["command"]
    hook_env = {**env, "CLAUDE_PROJECT_DIR": str(folder), "CLAUDE_PLUGIN_ROOT": str(plugin)}
    event = {
        "session_id": session_id,
        "transcript_path": transcript,
        "cwd": str(folder),
        "tool_name": "AskUserQuestion",
        "tool_use_id": "toolu_ratexp_live_plugin",
        "tool_input": picker,
    }
    answer = {
        "questions": picker["questions"],
        "answers": {question["question"]: f"{good}, Yes, store trajectory"},
        "annotations": {question["question"]: {"notes": comment}},
    }
    for payload in (
        {**event, "hook_event_name": "PreToolUse"},
        {**event, "hook_event_name": "PostToolUse", "tool_response": answer},
    ):
        sent = run(["bash", "-c", command], folder, hook_env, json.dumps(payload))
    assert f"accepted by {CORE_URL}" in sent.stdout, sent.stdout

    row = rating_on_dashboard(comment)
    assert row["agent"] == "claude-code"
    assert row["score"] == 1
    assert row["session_id"] == session_id
    assert not row.get("skill_name")
    # Claude Code names the model in its transcript, so the stored trajectory shows it.
    trajectory = trajectory_on_dashboard(row)["atif"]
    assert trajectory["steps"], "the stored trajectory has no steps"
    assert trajectory["agent"].get("model_name"), "the trajectory names no model"


@pytest.fixture
def cursor_hooks_file():
    """~/.cursor/hooks.json and its backup put back as they were after the test."""
    files = [Path.home() / ".cursor" / name for name in ("hooks.json", "hooks.json.ratexp-backup")]
    kept = {f: f.read_bytes() if f.exists() else None for f in files}
    yield
    for f, data in kept.items():
        if data is None:
            f.unlink(missing_ok=True)
        else:
            f.write_bytes(data)


def test_cursor_plugin_survey_and_rating(project, agent_cli, cursor_hooks_file):
    """The RateXp plugin, loaded for the chat as an install loads it, on production."""
    cursor = agent_cli("cursor-agent")
    folder = project / "project"
    state = project / "state"
    plugin = plugin_copy(project / "plugin", "cursor")
    script = plugin / "ratexp-cursor.sh"
    env = plugin_env(state)
    chat = [cursor, "-p", "--force", "--plugin-dir", str(plugin)]

    # A first turn, as core leaves the survey out of a trajectory: a chat holding only
    # /ratexp:rate would rate nothing.
    first = run(
        [*chat, "--output-format", "json", "Reply with just OK."],
        folder,
        env,
        timeout=AGENT_TIMEOUT,
    )
    assert first.returncode == 0, first.stderr
    chat += ["--output-format", "text", "--resume", json.loads(first.stdout)["session_id"]]

    # Cursor attaches the plugin's ratexp skill, which has the agent run `ask`.
    second = run([*chat, "/ratexp:rate"], folder, env, timeout=AGENT_TIMEOUT)
    assert second.returncode == 0, second.stderr
    pending = [
        p
        for p in glob.glob(f"{state}/ratexp/*/runs/*/pending")
        if CORE_URL.encode() in Path(p).read_bytes()
    ]
    assert pending, "the agent's /ratexp:rate left no survey for this core"

    # The click: what the agent runs with the user's answer.
    comment = ratexp_comment("cursor plugin")
    sent = run(["bash", str(script), "report", "good", "share", comment], folder, env)
    assert f"accepted by {CORE_URL}" in sent.stdout, sent.stdout + sent.stderr

    row = rating_on_dashboard(comment)
    assert row["agent"].startswith("cursor")
    assert row["score"] == 1
    assert not row.get("skill_name")
    assert trajectory_on_dashboard(row)["atif"]["steps"], "the stored trajectory has no steps"
    # No model to check: the hook learns it from Cursor's stop hook, which
    # `cursor-agent -p` never fires, and Cursor's transcript does not name it - so a
    # CLI row reads just "cursor". Cursor's editor fires it and the model shows.
