"""Black-box tests for core/install.sh, the one-line installer.

Users run it straight from core (`curl -fsSL <core>/install.sh | bash -s -- install
claude`). It saves the agent's hook script beside the agent's settings file and adds
RateXp's hooks to that file, keeping everything else in it.

Like the hooks it installs, it has to run on a bare machine: Bash 3.2+, curl and a
few standard utilities. Every test runs `/bin/bash install.sh` in a subprocess whose
PATH holds ONLY symlinks to those utilities plus a fake `curl` that hands out a stub
hook script, under its own temporary HOME. Nothing touches the network or the real
~/.claude and ~/.cursor; a python/jq dependency would make every test fail.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.name != "posix" or not Path("/bin/bash").exists(),
    reason="the installer is a POSIX shell script and needs /bin/bash",
)

CORE = Path(__file__).resolve().parents[1]
INSTALL_SH = CORE / "install.sh"
REPO = CORE.parent
# The utilities the script's own preflight loop checks for; `curl` is the fake.
ALLOWED_UTILS = ("mkdir", "mv", "cp", "rm", "rmdir")
LOCAL_URL = "http://127.0.0.1:9999"
STUB_HOOK = f"#!/bin/bash\nDEFAULT_URL='{LOCAL_URL}'\n"

# What each agent installs by default: its folder, settings file, script and the
# command its hooks run there.
AGENTS = {
    "claude": (
        ".claude",
        "settings.json",
        "ratexp-claude.sh",
        'bash "$HOME/.claude/ratexp-claude.sh"',
    ),
    "cursor": (".cursor", "hooks.json", "ratexp-cursor.sh", "bash ./ratexp-cursor.sh"),
}


def claude_hooks(command):
    """RateXp's Claude Code hooks, as the install popup lists them."""
    hook = {"type": "command", "command": command}
    return {
        "SessionStart": [{"hooks": [hook]}],
        "UserPromptExpansion": [{"hooks": [hook]}],
        "Stop": [{"hooks": [hook]}],
        "PreToolUse": [{"matcher": "Skill|AskUserQuestion", "hooks": [hook]}],
        "PostToolUse": [{"matcher": "AskUserQuestion", "hooks": [{**hook, "timeout": 60}]}],
        "PostToolUseFailure": [{"matcher": "AskUserQuestion", "hooks": [hook]}],
    }


def ratexp_settings(agent, command=None):
    """The whole settings file a fresh install writes."""
    command = command or AGENTS[agent][3]
    if agent == "claude":
        return {"hooks": claude_hooks(command)}
    hook = {"command": command}
    return {"version": 1, "hooks": {"sessionStart": [hook], "stop": [hook]}}


@pytest.fixture
def machine(tmp_path):
    """A bare machine: its own HOME, and a PATH of only the allowed utilities."""
    home = tmp_path / "home"
    home.mkdir()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for util in ALLOWED_UTILS:
        os.symlink(shutil.which(util), bin_dir / util)
    calls = tmp_path / "curl-calls"
    served = tmp_path / "served"
    # Records its arguments and writes the stub hook to -o - or the real one, when a
    # test has put core's copy in served/ - or fails like curl -f when the test has
    # dropped a `curl-fails` file.
    (bin_dir / "curl").write_text(
        "#!/bin/bash\n"
        f"printf '%s\\n' \"$*\" >> '{calls}'\n"
        f"[[ -e '{tmp_path}/curl-fails' ]] && exit 22\n"
        "while (( $# )); do\n"
        "    [[ $1 == -o ]] && { out=$2; shift; }\n"
        "    [[ $1 == --url ]] && { url=$2; shift; }\n"
        "    shift\n"
        "done\n"
        f"src='{served}'/${{url##*/}}\n"
        'if [[ -f $src ]]; then printf \'%s\\n\' "$(< "$src")" > "$out"\n'
        f'else printf \'%s\' "{STUB_HOOK}" > "$out"; fi\n'
    )
    (bin_dir / "curl").chmod(0o755)

    class Machine:
        path = tmp_path

        def run(self, *args, cwd=None):
            env = {"HOME": str(home), "PATH": str(bin_dir), "RATEXP_URL": LOCAL_URL}
            return subprocess.run(
                ["/bin/bash", "-s", "--", *args],
                input=INSTALL_SH.read_text(encoding="utf-8"),
                capture_output=True,
                text=True,
                env=env,
                cwd=cwd or home,
                timeout=120,
            )

        def curl_calls(self):
            return calls.read_text().splitlines() if calls.exists() else []

        def agent_dir(self, agent):
            return home / AGENTS[agent][0]

        def settings(self, agent):
            return self.agent_dir(agent) / AGENTS[agent][1]

        def script(self, agent):
            return self.agent_dir(agent) / AGENTS[agent][2]

    Machine.home = home
    Machine.served = served
    return Machine()


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    # Indented, as Claude Code and Cursor write their own settings files.
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2))


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def ratexp_commands_in(settings):
    """Every hook command in a settings file that runs a RateXp script."""
    found = []
    for groups in settings.get("hooks", {}).values():
        for group in groups:
            for entry in group.get("hooks", [group]):
                if "ratexp-" in entry.get("command", ""):
                    found.append(entry["command"])
    return found


# --------------------------------------------------------------------------
# install
# --------------------------------------------------------------------------


@pytest.mark.parametrize("agent", AGENTS)
def test_a_fresh_install_saves_the_script_and_writes_only_ratexps_hooks(machine, agent):
    result = machine.run("install", agent)

    assert result.returncode == 0, result.stderr
    assert machine.script(agent).read_text() == STUB_HOOK
    assert read_json(machine.settings(agent)) == ratexp_settings(agent)
    assert [c for c in machine.curl_calls() if f"{LOCAL_URL}/{AGENTS[agent][2]}" in c]
    # Nothing was there to back up, and the download left nothing behind.
    assert sorted(p.name for p in machine.agent_dir(agent).iterdir()) == sorted(
        [AGENTS[agent][1], AGENTS[agent][2]]
    )


@pytest.mark.parametrize("agent", AGENTS)
def test_install_keeps_every_other_setting_and_hook(machine, agent):
    if agent == "claude":
        mine = {"type": "command", "command": "echo mine"}
        before = {
            "model": "opus",
            "permissions": {"allow": ["Bash(ls)"], "deny": []},
            "hooks": {
                "Stop": [{"hooks": [mine]}],
                "Notification": [{"matcher": "", "hooks": [mine]}],
            },
        }
    else:
        mine = {"command": "./mine.sh"}
        before = {"version": 1, "hooks": {"stop": [mine], "afterFileEdit": [mine]}}
    write_json(machine.settings(agent), before)

    assert machine.run("install", agent).returncode == 0
    after = read_json(machine.settings(agent))

    for key, value in before.items():
        if key != "hooks":
            assert after[key] == value
    expected = ratexp_settings(agent)["hooks"]
    for event, groups in before["hooks"].items():
        assert after["hooks"][event][: len(groups)] == groups
    for event, groups in expected.items():
        assert after["hooks"][event][-1] == groups[0]
    assert len(ratexp_commands_in(after)) == len(expected)


@pytest.mark.parametrize("agent", AGENTS)
def test_installing_twice_gives_the_same_file_and_keeps_the_first_backup(machine, agent):
    write_json(machine.settings(agent), {"keep": True})
    machine.run("install", agent)
    once = machine.settings(agent).read_text()

    result = machine.run("install", agent)

    assert result.returncode == 0
    assert machine.settings(agent).read_text() == once
    assert "already" in result.stdout
    backup = machine.settings(agent).with_name(AGENTS[agent][1] + ".ratexp-backup")
    assert read_json(backup) == {"keep": True}


@pytest.mark.parametrize("agent", AGENTS)
def test_hand_pasted_or_stale_ratexp_hooks_are_replaced_not_doubled(machine, agent):
    pasted = ratexp_settings(agent)
    # A copy saved somewhere else once: still RateXp's, so it goes too.
    stale = ratexp_settings(agent, f"bash /old/place/{AGENTS[agent][2]}")
    first_event = next(iter(pasted["hooks"]))
    pasted["hooks"][first_event] += stale["hooks"][first_event]
    write_json(machine.settings(agent), pasted)

    assert machine.run("install", agent).returncode == 0

    assert read_json(machine.settings(agent)) == ratexp_settings(agent)


@pytest.mark.parametrize("agent", AGENTS)
def test_the_backup_holds_the_file_exactly_as_it_was(machine, agent):
    original = '{\n    "theme":   "dark",\n    "n": 1.50e3\n}\n'
    machine.settings(agent).parent.mkdir()
    machine.settings(agent).write_text(original)

    machine.run("install", agent)

    backup = machine.settings(agent).with_name(AGENTS[agent][1] + ".ratexp-backup")
    assert backup.read_text() == original
    assert read_json(machine.settings(agent))["n"] == 1500


@pytest.mark.parametrize(
    "content, reason",
    [
        ('{"model": "opus",}', "not valid JSON"),
        ('{"a": 1, "a": 2}', "not valid JSON"),
        ("[1, 2]", "not a JSON object"),
        ('{"hooks": []}', '"hooks" is not an object'),
    ],
)
@pytest.mark.parametrize("agent", AGENTS)
def test_a_settings_file_it_cannot_read_is_left_untouched_and_the_section_printed(
    machine, agent, content, reason
):
    machine.settings(agent).parent.mkdir()
    machine.settings(agent).write_text(content)

    result = machine.run("install", agent)

    assert result.returncode == 1
    assert machine.settings(agent).read_text() == content
    assert not machine.script(agent).exists()
    assert sorted(p.name for p in machine.agent_dir(agent).iterdir()) == [AGENTS[agent][1]]
    assert reason in result.stderr
    # The section to paste by hand is the whole fresh-install file.
    section = result.stderr.split("\n\n", 1)[1]
    assert json.loads(section) == ratexp_settings(agent)


@pytest.mark.parametrize("agent", AGENTS)
def test_a_failed_download_changes_nothing(machine, agent):
    write_json(machine.settings(agent), {"keep": True})
    (machine.path / "curl-fails").touch()

    result = machine.run("install", agent)

    assert result.returncode == 1
    assert "could not download" in result.stderr
    assert read_json(machine.settings(agent)) == {"keep": True}
    assert sorted(p.name for p in machine.agent_dir(agent).iterdir()) == [AGENTS[agent][1]]


@pytest.mark.parametrize(
    "agent, project_dir, command",
    [
        ("claude", ".claude", 'bash "$CLAUDE_PROJECT_DIR/.claude/ratexp-claude.sh"'),
        ("cursor", ".cursor", "bash .cursor/ratexp-cursor.sh"),
    ],
)
def test_a_project_settings_file_gets_the_script_beside_it_and_a_portable_command(
    machine, agent, project_dir, command
):
    project = machine.path / "project"
    project.mkdir()
    relative = f"{project_dir}/{AGENTS[agent][1]}"

    result = machine.run("install", agent, "--settings", relative, cwd=project)

    assert result.returncode == 0, result.stderr
    assert (project / project_dir / AGENTS[agent][2]).read_text() == STUB_HOOK
    assert read_json(project / relative) == ratexp_settings(agent, command)
    assert not machine.agent_dir(agent).exists()


@pytest.mark.parametrize("agent", AGENTS)
def test_any_other_settings_file_names_the_script_by_its_full_path(machine, agent):
    target = machine.path / "dot files" / "agent.json"

    assert machine.run("install", agent, "--settings", str(target)).returncode == 0

    script = target.parent / AGENTS[agent][2]
    assert script.exists()
    assert read_json(target) == ratexp_settings(agent, f'bash "{script}"')


@pytest.mark.parametrize(
    "agent, project_dir, first_event, marker",
    [
        ("claude", ".claude", "SessionStart", "RateXp target: "),
        ("cursor", ".cursor", "sessionStart", "# RateXp survey"),
    ],
)
def test_a_project_install_runs_the_real_hook_from_the_project_and_uninstalls_cleanly(
    machine, client, agent, project_dir, first_event, marker
):
    # The real hook as core serves it, run the way the agent runs it: through the
    # command the installer wrote, from the project, with nothing installed globally.
    script = AGENTS[agent][2]
    machine.served.mkdir()
    (machine.served / script).write_text(client.get(f"/{script}").text)
    project = machine.path / "project"
    project.mkdir()
    relative = f"{project_dir}/{AGENTS[agent][1]}"
    assert machine.run("install", agent, "--settings", relative, cwd=project).returncode == 0
    first = read_json(project / relative)["hooks"][first_event][0]
    if agent == "claude":
        command = first["hooks"][0]["command"]
        event = {
            "session_id": "project-session",
            "transcript_path": str(project / "transcript.jsonl"),
            "cwd": str(project),
            "hook_event_name": first_event,
            "source": "startup",
        }
    else:
        command = first["command"]
        event = {"hook_event_name": first_event, "workspace_roots": [str(project)]}

    ran = subprocess.run(
        ["/bin/bash", "-c", command],
        input=json.dumps(event),
        capture_output=True,
        text=True,
        cwd=project,
        timeout=60,
        env={
            "HOME": str(machine.home),
            "PATH": "/usr/bin:/bin",
            "CLAUDE_PROJECT_DIR": str(project),
            "XDG_STATE_HOME": str(machine.path / "state"),
            "RATEXP_URL": LOCAL_URL,
        },
    )

    assert ran.returncode == 0, ran.stderr
    # On a session start the hook writes /ratexp beside itself: inside the project.
    written = project / project_dir / "commands" / "ratexp.md"
    assert marker in written.read_text()
    assert not machine.agent_dir(agent).exists()

    assert machine.run("uninstall", agent, "--settings", relative, cwd=project).returncode == 0
    assert not written.exists()
    assert not (project / project_dir / script).exists()
    assert ratexp_commands_in(read_json(project / relative)) == []


def test_a_path_a_hook_command_cannot_hold_is_refused(machine):
    target = machine.path / 'odd"$dir' / "settings.json"

    result = machine.run("install", "claude", "--settings", str(target))

    assert result.returncode == 1
    assert "characters" in result.stderr
    assert not target.parent.exists()
    assert not machine.curl_calls()


def test_a_symlinked_settings_file_stays_a_symlink(machine):
    real = machine.path / "dotfiles" / "settings.json"
    write_json(real, {"keep": True})
    machine.agent_dir("claude").mkdir()
    machine.settings("claude").symlink_to(real)

    assert machine.run("install", "claude").returncode == 0

    assert machine.settings("claude").is_symlink()
    assert read_json(real) == {"keep": True, **ratexp_settings("claude")}


def test_a_large_settings_file_full_of_escapes_survives(machine):
    # Thousands of permissions, every JSON escape, non-ASCII text and odd numbers:
    # the reader and writer round-trip all of it, in a few seconds.
    tricky = 'quote " slash \\ tab \t nl \n ctl \u0001 uni é ☃ 😀 </script>'
    before = {
        "permissions": {"allow": [f"Bash(echo {i} {tricky})" for i in range(3000)]},
        "env": {"A": "1", "B": tricky},
        "numbers": [0, -1, 1.5, 2e10, -3.25e-4, True, False, None],
        "nested": {"a": {"b": {"c": [[], {}, [{}]]}}},
    }
    write_json(machine.settings("claude"), before)

    result = machine.run("install", "claude")

    assert result.returncode == 0, result.stderr
    after = read_json(machine.settings("claude"))
    assert {k: v for k, v in after.items() if k != "hooks"} == before


# --------------------------------------------------------------------------
# uninstall
# --------------------------------------------------------------------------


@pytest.mark.parametrize("agent", AGENTS)
def test_uninstall_removes_only_ratexp(machine, agent):
    if agent == "claude":
        mine = {"type": "command", "command": "echo mine"}
        before = {"model": "opus", "hooks": {"Stop": [{"hooks": [mine]}], "Notification": []}}
        ours = ["ratexp.md", "ratexp/poem-creator.md"]
        ratexp_text = "---\ndescription: x\n---\n\nRateXp target: this session\n"
    else:
        before = {"version": 1, "hooks": {"stop": [{"command": "./mine.sh"}]}}
        ours = ["ratexp.md"]
        ratexp_text = "# RateXp survey\n\nRun it.\n"
    write_json(machine.settings(agent), before)
    machine.run("install", agent)
    commands = machine.agent_dir(agent) / "commands"
    for name in ours:
        (commands / name).parent.mkdir(parents=True, exist_ok=True)
        (commands / name).write_text(ratexp_text)
    (commands / "mine.md").write_text("# my own command\n")

    result = machine.run("uninstall", agent)

    assert result.returncode == 0, result.stderr
    assert read_json(machine.settings(agent)) == before
    assert not machine.script(agent).exists()
    assert sorted(p.name for p in commands.iterdir()) == ["mine.md"]


@pytest.mark.parametrize("agent", AGENTS)
def test_uninstall_after_a_fresh_install_drops_the_hooks_it_emptied(machine, agent):
    machine.run("install", agent)

    assert machine.run("uninstall", agent).returncode == 0

    assert read_json(machine.settings(agent)) == ({} if agent == "claude" else {"version": 1})


def test_uninstall_keeps_a_users_own_command_named_ratexp(machine):
    machine.run("install", "claude")
    own = machine.agent_dir("claude") / "commands" / "ratexp.md"
    own.parent.mkdir()
    own.write_text("my own /ratexp, nothing to do with RateXp\n")

    machine.run("uninstall", "claude")

    assert own.exists()


def test_uninstall_with_nothing_installed_changes_nothing(machine):
    result = machine.run("uninstall", "claude")

    assert result.returncode == 0
    assert not machine.agent_dir("claude").exists()


# --------------------------------------------------------------------------
# status and usage
# --------------------------------------------------------------------------


@pytest.mark.parametrize("agent", AGENTS)
def test_status_says_missing_before_and_installed_after(machine, agent):
    before = machine.run("status", agent)
    machine.run("install", agent)
    after = machine.run("status", agent)

    assert before.returncode == 1
    assert "missing" in before.stdout
    assert after.returncode == 0, after.stdout
    assert not re.search(r"\smissing$", after.stdout, re.M)
    assert str(machine.settings(agent)) in after.stdout
    assert LOCAL_URL in after.stdout


def test_status_notices_a_single_missing_hook(machine):
    machine.run("install", "claude")
    settings = read_json(machine.settings("claude"))
    del settings["hooks"]["Stop"]
    write_json(machine.settings("claude"), settings)

    result = machine.run("status", "claude")

    assert result.returncode == 1
    assert re.search(r"Stop\s+missing", result.stdout)


@pytest.mark.parametrize(
    "args",
    [
        [],
        ["install"],
        ["remove", "claude"],
        ["install", "codex"],
        ["install", "claude", "--settings"],
        ["install", "claude", "--other", "x"],
        ["install", "claude", "--settings", "x", "y"],
    ],
)
def test_wrong_words_print_the_usage_and_exit_2(machine, args):
    result = machine.run(*args)

    assert result.returncode == 2
    assert "Usage:" in result.stderr
    assert not machine.curl_calls()


# --------------------------------------------------------------------------
# Kept in step with the hooks and the install popup
# --------------------------------------------------------------------------


def shell_function(path, name):
    """A shell function's source, from its opening line to its closing brace."""
    lines = path.read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(f"{name}() {{"))
    end = start if lines[start].endswith("}") else lines.index("}", start)
    return lines[start : end + 1]


@pytest.mark.parametrize("name", ("hex4", "utf8", "string", "get", "quote", "good_url"))
def test_the_installer_reads_json_with_the_hooks_own_reader(name):
    assert shell_function(INSTALL_SH, name) == shell_function(CORE / "ratexp-claude.sh", name), (
        f"{name}() differs from ratexp-claude.sh; change every copy"
    )


def test_the_installed_claude_hooks_are_the_ones_the_popup_and_the_hook_know(machine):
    machine.run("install", "claude")
    installed = {
        event: groups[0].get("matcher", "")
        for event, groups in read_json(machine.settings("claude"))["hooks"].items()
    }
    popup_source = (REPO / "app" / "ratexp" / "FE" / "src" / "App.jsx").read_text(encoding="utf-8")
    popup_block = popup_source.split("const CLAUDE_SETTINGS = {", 1)[1].split("\n}\n", 1)[0]
    popup = {
        event: matcher or ""
        for event, matcher in re.findall(r"(\w+): \[\{ (?:matcher: '([^']*)', )?hooks", popup_block)
    }
    triage = "\n".join(shell_function(CORE / "ratexp-claude.sh", "triage"))

    assert installed == popup
    for event, matcher in installed.items():
        # A tool event is triaged by its tool's name, any other by its own.
        assert matcher or f'"{event}"' in triage
        for tool in filter(None, matcher.split("|")):
            assert f'"{tool}"' in triage
