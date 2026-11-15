"""Opt-in check of the production RateXp with the real Claude Code and Cursor CLIs.

Never runs by default. Turn it on after deploying a change to core/ratexp-*.sh or
core/install.sh:

    RATEXP_PROD_AGENTS=1 uv run --no-project --with-requirements tests/requirements.txt \\
        pytest tests/test_agents_production.py -v

RATEXP_AGENTS_ENVIRONMENT=dev runs the same checks on dev (ratexp-dev-core and
ratexp-dev-app), before the tested images are copied to prod; "production" below then
means dev.

Each test installs RateXp into a scratch project with the one-line installer from the
production core, runs the agent there with `-p`, answers the survey the way a click
would - good, and store the conversation - finds the rating and its trajectory on the
production dashboard, and uninstalls. Your own ~/.claude and ~/.cursor are never changed.

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


# Each agent's settings file inside the scratch project: the install under test.
PROJECT_SETTINGS = {"claude": ".claude/settings.json", "cursor": ".cursor/hooks.json"}


def installer(project, action, agent) -> subprocess.CompletedProcess:
    """The one-line installer, exactly as the README gives it, aimed at the project."""
    words = f"{action} {agent} --settings {PROJECT_SETTINGS[agent]}"
    # pipefail: a failed download hands bash an empty script, which still exits 0.
    line = f"curl -fsSL {CORE_URL}/install.sh | bash -s -- {words}"
    return run(["bash", "-o", "pipefail", "-c", line], project)


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


def ratexp_files_left(folder: Path) -> list[str]:
    """Anything of RateXp's still in an agent folder after uninstall."""
    left = [p.name for p in folder.glob("ratexp-*.sh")]
    left += [str(p.relative_to(folder)) for p in folder.glob("commands/ratexp*")]
    settings = next(folder.glob("*.json")).read_text()
    return left + (["hooks"] if "ratexp-" in settings else [])


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


def test_claude_code_install_survey_rating_and_uninstall(project, agent_cli):
    claude = agent_cli("claude")
    folder = project / "project"
    state = project / "state"
    env = {"XDG_STATE_HOME": str(state)}
    # Only the project's settings, so a global RateXp install stays out of it.
    session = [claude, "-p", "--setting-sources", "project", "--model", CLAUDE_MODEL]

    assert installer(folder, "install", "claude").returncode == 0
    status = installer(folder, "status", "claude")
    assert status.returncode == 0, status.stdout

    # The hooks run: a session start writes /ratexp into the project. Claude Code reads
    # it at the next start, so the session is resumed to rate it - core leaves the
    # survey out of a trajectory, so a session holding only /ratexp would rate nothing.
    session_id = str(uuid.uuid4())
    first = run(
        [*session, "--session-id", session_id, "Reply with just OK."],
        folder,
        env,
        timeout=AGENT_TIMEOUT,
    )
    assert first.returncode == 0, first.stderr
    assert "RateXp target:" in (folder / ".claude/commands/ratexp.md").read_text()

    # /ratexp makes the hook ask. The picker tool is off: with nobody to answer, a
    # failed picker would spend the survey before the scripted click.
    second = run(
        # The prompt goes first: --disallowedTools takes every word after it as a tool.
        [*session, "/ratexp", "--resume", session_id, "--disallowedTools", "AskUserQuestion"],
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
    assert f"to {CORE_URL}" in json.dumps(picker), "the survey names another core"

    # The click: the two events Claude Code sends when True and Yes, store trajectory
    # are ticked.
    comment = ratexp_comment("claude")
    question = picker["questions"][0]["question"]
    hook = json.loads((folder / ".claude/settings.json").read_text())["hooks"]["PostToolUse"]
    hook_env = {**env, "CLAUDE_PROJECT_DIR": str(folder)}
    event = {
        "session_id": session_id,
        "transcript_path": transcript,
        "cwd": str(folder),
        "tool_name": "AskUserQuestion",
        "tool_use_id": "toolu_ratexp_live_test",
        "tool_input": picker,
    }
    answer = {
        "questions": picker["questions"],
        "answers": {question: "True, Yes, store trajectory"},
        "annotations": {question: {"notes": comment}},
    }
    for payload in (
        {**event, "hook_event_name": "PreToolUse"},
        {**event, "hook_event_name": "PostToolUse", "tool_response": answer},
    ):
        sent = run(
            ["bash", "-c", hook[0]["hooks"][0]["command"]], folder, hook_env, json.dumps(payload)
        )
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

    assert installer(folder, "uninstall", "claude").returncode == 0
    assert ratexp_files_left(folder / ".claude") == []


def test_cursor_install_survey_rating_and_uninstall(project, agent_cli):
    cursor = agent_cli("cursor-agent")
    folder = project / "project"
    state = project / "state"
    env = {"XDG_STATE_HOME": str(state)}
    script = folder / ".cursor/ratexp-cursor.sh"

    assert installer(folder, "install", "cursor").returncode == 0
    status = installer(folder, "status", "cursor")
    assert status.returncode == 0, status.stdout

    chat = [cursor, "-p", "--force"]

    # The hooks run: a new chat's session start writes /ratexp into the project.
    first = run(
        [*chat, "--output-format", "json", "Reply with just OK."],
        folder,
        env,
        timeout=AGENT_TIMEOUT,
    )
    assert first.returncode == 0, first.stderr
    assert "# RateXp survey" in (folder / ".cursor/commands/ratexp.md").read_text()
    # The same chat again for /ratexp: core leaves the survey out of a trajectory, so a
    # chat holding only /ratexp would rate nothing.
    chat += ["--output-format", "text", "--resume", json.loads(first.stdout)["session_id"]]

    # Cursor also reads ~/.cursor, and a global /ratexp wins over the project's - so
    # with RateXp installed globally the agent is given the project command's own
    # instruction instead, naming this project's script.
    global_command = Path.home() / ".cursor/commands/ratexp.md"
    if global_command.exists() and "RateXp" in global_command.read_text():
        request = f"Run `bash \"{script}\" ask '/ratexp'` and print what it prints, word for word."
    else:
        request = "/ratexp"
    second = run([*chat, request], folder, env, timeout=AGENT_TIMEOUT)
    assert second.returncode == 0, second.stderr
    pending = [
        p
        for p in glob.glob(f"{state}/ratexp/*/runs/*/pending")
        if CORE_URL.encode() in Path(p).read_bytes()
    ]
    assert pending, "the agent's /ratexp left no survey for this project's core"

    # The click: what the agent runs with the user's answer.
    comment = ratexp_comment("cursor")
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

    assert installer(folder, "uninstall", "cursor").returncode == 0
    assert ratexp_files_left(folder / ".cursor") == []
