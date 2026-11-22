"""Black-box tests for what core/ratexp-claude.sh and core/ratexp-cursor.sh do as the
RateXp plugin's hooks, and for the plugin's manifests and skills.

The hooks send to the hosted core unless RATEXP_URL says otherwise, ask core at
/hook-settings for the turns, the default eval and the evals, keep that answer for
when core is out of reach, and show how to update when core names a newer plugin
version. The Cursor hook also makes sure ~/.cursor/hooks.json has a stop hook.

The sandbox, fake curl and event helpers come from test_hook.py,
test_hook_session.py and test_hook_cursor.py.
"""

from __future__ import annotations

import json
import re

import pytest
from test_hook import CORE, EVALS, LOCAL_URL, PLUGIN_VERSION, settings_answer
from test_hook_cursor import CursorHook
from test_hook_session import SessionHook

HOSTED_URL = "https://ratexp-core.azurewebsites.net"
# An eval that only core's answer holds, so a survey that asks it came from there.
ONLY_IN_SETTINGS = "plugin-only"
SETTINGS_EVALS = {
    **EVALS,
    ONLY_IN_SETTINGS: ("Did {subject} help?", "Helped", "It helped.", "Useless", "It did not."),
}
UPDATE_LINE = "claude plugin update ratexp@ratexp"
CANNOT_ASK = {
    "systemMessage": f"RateXp: the surveys could not be loaded from {LOCAL_URL}, so no survey can be asked."
}


def core_answer(**fields):
    """What core's /hook-settings returns in these tests."""
    return settings_answer(evals=SETTINGS_EVALS, **fields)


class PluginHook(SessionHook):
    """The Claude Code hook before core has sent anything: each test starts the session."""

    def __init__(self, tmp_path):
        super().__init__(tmp_path)
        self.settings_kept().unlink()
        self.answer_settings(core_answer())

    def env(self, **overrides):
        values = {"RATEXP_EVERY": None}
        values.update(overrides)
        return super().env(**values)

    def session_start(self, env=None):
        out, _, _ = self.run_hook(self.event("SessionStart", source="startup"), env)
        return out

    def ask_quietly(self, env=None):
        """The user typing /ratexp:rate, and the turn after it. Returns what Stop printed."""
        self.ratexp_command(env)
        self.append(type="assistant", text="WORK")
        out, _, _ = self.run_hook(self.event("Stop", stop_hook_active=False), env)
        return json.loads(out) if out else None

    def settings_calls(self):
        return [c for c in self.calls() if c["endpoint"] == "hook-settings"]


@pytest.fixture
def p(tmp_path):
    return PluginHook(tmp_path)


# --------------------------------------------------------------------------
# Settings from core
# --------------------------------------------------------------------------


def test_session_start_asks_core_for_the_settings(p):
    assert p.session_start() == ""
    assert [c["url"] for c in p.settings_calls()] == [f"{LOCAL_URL}/hook-settings"]


def test_without_ratexp_url_the_plugin_talks_to_the_hosted_core(p):
    p.session_start(env={"RATEXP_URL": None})
    assert [c["url"] for c in p.settings_calls()] == [f"{HOSTED_URL}/hook-settings"]
    picker = p.ask(env={"RATEXP_URL": None})
    assert HOSTED_URL in json.dumps(picker), "consent names the hosted core"


def test_the_survey_asks_an_eval_that_only_core_sent(p):
    p.session_start()
    picker = p.ask(eval_name=ONLY_IN_SETTINGS)
    question = picker["questions"][0]
    assert question["question"].startswith("Did this Claude Code session help?")
    assert [o["label"] for o in question["options"]][:2] == ["Helped", "Useless"]


def test_a_ratexp_without_an_eval_asks_the_default_eval_core_sent(p):
    p.answer_settings(core_answer(default_eval=ONLY_IN_SETTINGS))
    p.session_start()
    picker = p.ask()
    assert picker["questions"][0]["options"][0]["label"] == "Helped"
    p.pre(picker)
    p.run_hook(p.answer(picker, "Helped, No, do not store"))
    assert p.calls()[-1]["fields"]["eval_name"] == ONLY_IN_SETTINGS


def test_the_session_is_asked_about_every_nth_turn_as_core_says(p):
    p.answer_settings(core_answer(every=2))
    p.session_start()
    assert [p.turn(f"TURN-{i}") is not None for i in range(4)] == [False, True, False, True]


def test_ratexp_every_still_wins_over_core(p):
    p.answer_settings(core_answer(every=2))
    p.session_start()
    env = {"RATEXP_EVERY": "3"}
    assert [p.turn(f"TURN-{i}", env=env) is not None for i in range(3)] == [False, False, True]


def test_the_kept_settings_serve_when_core_is_out_of_reach(p):
    p.session_start()
    p.answer_settings(None)
    assert p.session_start() == ""
    assert p.ask(eval_name=ONLY_IN_SETTINGS) is not None


def test_a_turn_asks_core_again_when_session_start_could_not(p):
    p.answer_settings(None)
    p.session_start()
    p.answer_settings(core_answer())
    assert p.ask(eval_name=ONLY_IN_SETTINGS) is not None
    assert len(p.settings_calls()) == 2


def test_a_ratexp_that_cannot_be_asked_says_so_once(p):
    p.answer_settings(None)
    p.session_start()
    assert p.ask_quietly() == CANNOT_ASK
    assert p.turn() is None
    out, _, _ = p.run_hook(p.event("Stop", stop_hook_active=False))
    assert out == "", "the /ratexp:rate was reported once, then dropped"


def test_a_core_that_stays_out_of_reach_is_asked_once_more_per_session(p):
    """Every ask can wait for the connection to time out, so a down core must not
    slow every turn: session start asks, the first turn's end asks again, no more."""
    p.answer_settings(None)
    p.session_start()
    assert [p.turn(f"TURN-{i}") for i in range(3)] == [None, None, None]
    assert p.endpoints() == ["hook-settings", "hook-settings"]


def test_cursor_running_the_claude_code_plugin_is_ignored(p):
    """Cursor runs Claude Code's plugins too; RateXp's own Cursor plugin rates there."""
    env = {"CURSOR_VERSION": "3.25.6"}
    assert p.session_start(env=env) == ""
    p.ratexp_command(env)
    assert p.turn(env=env) is None
    assert p.calls() == []


@pytest.mark.parametrize(
    "answer",
    [
        "not json",
        json.dumps({**core_answer(), "every": 0}),
        json.dumps({**core_answer(), "plugin_version": "latest"}),
        json.dumps({**core_answer(), "evals": [{"name": "half"}]}),
        json.dumps({k: v for k, v in core_answer().items() if k != "default_eval"}),
    ],
)
def test_a_settings_answer_that_is_not_valid_is_not_kept(p, answer):
    p.answer_settings(answer)
    p.session_start()
    assert p.ask_quietly() == CANNOT_ASK


def test_a_settings_answer_that_is_not_200_is_not_kept(p):
    p.session_start(env={"RATEXP_CURL_SETTINGS_STATUS": "503"})
    p.answer_settings(None)
    assert p.ask_quietly() == CANNOT_ASK


# --------------------------------------------------------------------------
# A newer plugin version
# --------------------------------------------------------------------------


def test_a_newer_plugin_version_shows_how_to_update(p):
    p.answer_settings(core_answer(version="1.10.0"))
    message = json.loads(p.session_start())["systemMessage"]
    assert message.startswith(f"RateXp 1.10.0 is out, and you have {PLUGIN_VERSION}.")
    assert UPDATE_LINE in message


@pytest.mark.parametrize("version", [PLUGIN_VERSION, "1.3.9", "0.9"])
def test_the_same_or_an_older_version_shows_nothing(p, version):
    p.answer_settings(core_answer(version=version))
    assert p.session_start() == ""


def test_the_survey_count_carries_over_a_plugin_update(p):
    """Each version sits in its own folder; the turns counted before an update
    still count after it."""
    p.answer_settings(core_answer(every=2))
    p.session_start()
    assert p.turn("BEFORE") is None
    p.install_version("1.5.0")
    assert p.turn("AFTER") is not None


# --------------------------------------------------------------------------
# The Cursor hook as the plugin runs it
# --------------------------------------------------------------------------


class CursorPluginHook(CursorHook):
    """The Cursor hook before core has sent anything."""

    def __init__(self, tmp_path):
        super().__init__(tmp_path)
        self.settings_kept().unlink()
        self.answer_settings(core_answer())

    def env(self, **overrides):
        values = {"RATEXP_EVERY": None}
        values.update(overrides)
        return super().env(**values)

    def settings_calls(self):
        return [c for c in self.calls(settings=True) if c["endpoint"] == "hook-settings"]


@pytest.fixture
def cp(tmp_path):
    return CursorPluginHook(tmp_path)


def test_cursor_session_start_asks_core_for_the_settings(cp):
    assert json.loads(cp.session_start()) == {}
    assert [c["url"] for c in cp.settings_calls()] == [f"{LOCAL_URL}/hook-settings"]
    assert cp.settings_kept().is_file(), "the answer is kept"
    assert not (cp.home / ".cursor" / "commands").exists(), "the plugin's skill is the command"


def test_cursor_without_ratexp_url_the_plugin_talks_to_the_hosted_core(cp):
    cp.use()
    cp.request()
    out, rc = cp.ask("/ratexp:rate", env={"RATEXP_URL": None})
    assert rc == 0
    assert [c["url"] for c in cp.settings_calls()] == [f"{HOSTED_URL}/hook-settings"]
    assert f"to {HOSTED_URL}?" in out, "consent names the hosted core"


def test_cursor_ask_offers_an_eval_that_only_core_sent(cp):
    cp.use()
    cp.request(f"/ratexp:rate {ONLY_IN_SETTINGS}")
    out, rc = cp.ask(f"/ratexp:rate {ONLY_IN_SETTINGS}")
    assert rc == 0
    assert '"Did this session help?"' in out
    assert "Helped (It helped.)" in out


def test_cursor_ask_uses_the_kept_settings_when_core_is_out_of_reach(cp):
    cp.session_start()
    cp.answer_settings(None)
    cp.use()
    cp.request()
    out, rc = cp.ask("/ratexp:rate")
    assert rc == 0
    assert "RateXp survey for this whole chat" in out


def test_cursor_ask_says_so_when_no_survey_can_be_loaded(cp):
    cp.answer_settings(None)
    cp.use()
    cp.request()
    out, rc = cp.ask("/ratexp:rate")
    assert rc == 1
    assert f"the surveys could not be loaded from {LOCAL_URL}" in out


def test_cursor_ask_tells_the_user_first_about_a_newer_plugin(cp):
    cp.answer_settings(core_answer(version="2.0.0"))
    cp.use()
    cp.request()
    out, rc = cp.ask("/ratexp:rate")
    assert rc == 0
    assert out.startswith(
        f"First tell the user: RateXp 2.0.0 is out, and they have {PLUGIN_VERSION}."
    )


def test_cursor_ask_says_nothing_about_the_same_version(cp):
    cp.use()
    cp.request()
    out, _ = cp.ask("/ratexp:rate")
    assert "is out" not in out


def test_cursor_asks_every_nth_turn_as_core_says(cp):
    cp.answer_settings(core_answer(every=2))
    cp.session_start()
    asked = [cp.end_turn(f"gen-{i}").strip() != "{}" for i in range(4)]
    assert asked == [False, True, False, True]


def test_cursor_turns_ask_a_core_out_of_reach_once_per_chat(cp):
    cp.answer_settings(None)
    assert [cp.end_turn(f"gen-{i}").strip() for i in range(3)] == ["{}", "{}", "{}"]
    assert len(cp.settings_calls()) == 1


# Cursor runs a plugin's stop hook only when a hooks file has a stop hook too, so the
# plugin adds one that does nothing to ~/.cursor/hooks.json.
STOP_HOOK = {"command": "true # RateXp: lets Cursor run the stop hook of the RateXp plugin"}


def hooks_file(hook):
    return hook.home / ".cursor" / "hooks.json"


def test_cursor_session_start_writes_a_hooks_file_with_a_stop_hook(cp):
    cp.session_start()
    assert json.loads(hooks_file(cp).read_text(encoding="utf-8")) == {
        "version": 1,
        "hooks": {"stop": [STOP_HOOK]},
    }


def test_cursor_adds_the_stop_hook_and_keeps_the_rest_of_the_hooks_file(cp):
    own = {
        "hooks": {
            "sessionStart": [{"command": "bash '/opt/herdr.sh' session", "timeout": 10}],
            "afterFileEdit": [{"command": 'fmt "$1"'}],
        },
        "version": 1,
        "note": "ünïcode, a \\ and a tab\t",
    }
    text = json.dumps(own, indent=4)
    hooks_file(cp).write_text(text, encoding="utf-8")
    cp.session_start()
    own["hooks"]["stop"] = [STOP_HOOK]
    assert json.loads(hooks_file(cp).read_text(encoding="utf-8")) == own
    assert (cp.home / ".cursor" / "hooks.json.ratexp-backup").read_text(encoding="utf-8") == text


@pytest.mark.parametrize(
    ("own", "expected"),
    [
        ({"version": 1}, {"version": 1, "hooks": {"stop": [STOP_HOOK]}}),
        ({"version": 1, "hooks": {}}, {"version": 1, "hooks": {"stop": [STOP_HOOK]}}),
        ({"hooks": {"stop": []}}, {"hooks": {"stop": [STOP_HOOK]}}),
    ],
)
def test_cursor_adds_the_stop_hook_where_the_hooks_file_lacks_one(cp, own, expected):
    hooks_file(cp).write_text(json.dumps(own), encoding="utf-8")
    cp.session_start()
    assert json.loads(hooks_file(cp).read_text(encoding="utf-8")) == expected


def test_cursor_adds_the_stop_hook_only_once(cp):
    cp.session_start()
    cp.session_start()
    assert json.loads(hooks_file(cp).read_text(encoding="utf-8"))["hooks"]["stop"] == [STOP_HOOK]


@pytest.mark.parametrize(
    "text",
    [
        '{"version": 1, "hooks": {"stop": [{"command": "my-hook"}]}}',
        "{not json",
        "[]",
        '{"hooks": []}',
        '{"hooks": {"stop": {}}}',
    ],
)
def test_cursor_leaves_a_hooks_file_with_a_stop_hook_or_that_it_cannot_read_alone(cp, text):
    hooks_file(cp).write_text(text, encoding="utf-8")
    cp.session_start()
    assert hooks_file(cp).read_text(encoding="utf-8") == text
    assert not (cp.home / ".cursor" / "hooks.json.ratexp-backup").exists()


def test_cursor_does_not_follow_a_planted_hooks_file_symlink(cp):
    victim = cp.home / "victim.json"
    victim.write_text("{}", encoding="utf-8")
    hooks_file(cp).symlink_to(victim)
    cp.session_start()
    assert victim.read_text(encoding="utf-8") == "{}"


# --------------------------------------------------------------------------
# The plugin's manifests
# --------------------------------------------------------------------------

REPO = CORE.parent


def read_json(path):
    return json.loads((REPO / path).read_text(encoding="utf-8"))


def test_both_plugin_manifests_carry_the_same_version():
    """core names one newest version at /hook-settings, for both agents."""
    claude = read_json(".claude-plugin/plugin.json")["version"]
    assert read_json(".cursor-plugin/plugin.json")["version"] == claude


def test_the_claude_code_plugin_hooks_up_the_events_its_hook_reads():
    """The events, matchers and timeouts the Claude Code hook needs; its triage step
    lets exactly these through."""
    hook = {"type": "command", "command": 'bash "${CLAUDE_PLUGIN_ROOT}/core/ratexp-claude.sh"'}
    assert read_json(".claude-plugin/plugin.json")["hooks"] == {
        "SessionStart": [{"hooks": [hook]}],
        "UserPromptExpansion": [{"hooks": [hook]}],
        "Stop": [{"hooks": [hook]}],
        "PreToolUse": [{"matcher": "Skill|AskUserQuestion", "hooks": [hook]}],
        "PostToolUse": [{"matcher": "AskUserQuestion", "hooks": [{**hook, "timeout": 60}]}],
        "PostToolUseFailure": [{"matcher": "AskUserQuestion", "hooks": [hook]}],
    }


def test_the_cursor_plugin_hooks_up_session_start_and_stop():
    manifest = read_json(".cursor-plugin/plugin.json")
    hooks = read_json(manifest["hooks"].removeprefix("./"))
    command = {"command": 'bash "${CURSOR_PLUGIN_ROOT}/core/ratexp-cursor.sh"'}
    assert hooks == {"version": 1, "hooks": {"sessionStart": [command], "stop": [command]}}


@pytest.mark.parametrize(
    ("agent", "skill"), [(".claude-plugin", "rate"), (".cursor-plugin", "ratexp")]
)
def test_each_plugin_brings_its_rating_skill(agent, skill):
    """/ratexp:rate in both agents: Claude Code names a plugin's skill
    <plugin>:<skill>, and the Cursor CLI runs the skill named ratexp for
    /ratexp:<anything>. Each manifest points at its own skills folder, so neither
    agent sees the other's skill."""
    folder = read_json(f"{agent}/plugin.json")["skills"]
    assert folder == f"./{agent}/skills/"
    assert [p.name for p in (REPO / folder).iterdir()] == [skill]
    assert (REPO / folder / skill / "SKILL.md").is_file()


@pytest.mark.parametrize(
    "skill", [".claude-plugin/skills/rate/SKILL.md", ".cursor-plugin/skills/ratexp/SKILL.md"]
)
def test_only_the_user_can_run_the_rating_skill(skill):
    """The hooks hear only what the user types, so a rating the model started
    itself would promise a survey that never comes."""
    assert "disable-model-invocation: true" in (REPO / skill).read_text(encoding="utf-8")


def test_the_cursor_skill_names_the_script_from_its_own_folder():
    """Cursor shows the agent the skill's path, so the skill names the script by a path
    from its own folder, wherever Cursor keeps the plugin."""
    folder = REPO / ".cursor-plugin" / "skills" / "ratexp"
    text = (folder / "SKILL.md").read_text(encoding="utf-8")
    relative = re.search(r'bash "<folder>/([^"]+)" ask', text).group(1)
    assert (folder / relative).resolve() == (CORE / "ratexp-cursor.sh").resolve()
    assert "RateXp survey" in text, "Cursor sends the skill along; the hook finds the chat by this"


@pytest.mark.parametrize("agent", [".claude-plugin", ".cursor-plugin"])
def test_each_marketplace_lists_the_plugin_at_the_repo_root(agent):
    plugins = read_json(f"{agent}/marketplace.json")["plugins"]
    assert [(p["name"], p["source"]) for p in plugins] == [("ratexp", "./")]
