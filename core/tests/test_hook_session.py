"""Black-box tests for core/ratexp-claude.sh across a whole session.

The whole session is rated every Nth turn on its own and whenever the user types
`/ratexp`, always from byte zero; `/ratexp <skill>` picks one skill's newest run
out of it; and the hook writes `/ratexp` itself, plus a `/ratexp:<skill>` menu
entry for every installed skill. The sandbox, fake curl and event helpers come
from test_hook.py.
"""

from __future__ import annotations

import json

import pytest
from test_hook import CONSENT, EARLIER, SENTINEL, Hook

# What the session survey asks. The skill survey says "Rate <skill> - ..." instead.
SESSION_QUESTION = "Rate this Claude Code session — check all that apply or type a comment."


class SessionHook(Hook):
    """The Claude Code hook, rating the whole session."""

    script_name = "ratexp-claude.sh"

    def turn(self, text=SENTINEL, env=None):
        """One assistant turn: work lands in the transcript, then Stop fires."""
        self.append(type="assistant", text=text)
        return self.stop(env)

    def ratexp_command(self, env=None):
        """The user typing /ratexp."""
        return self.run_hook(self.event("UserPromptExpansion", command_name="ratexp"), env)

    def ask(self, text=SENTINEL, env=None):
        """The user typing /ratexp, and the turn that follows. Returns its picker."""
        self.ratexp_command(env)
        return self.turn(text, env)


@pytest.fixture
def s(tmp_path):
    return SessionHook(tmp_path)


# --------------------------------------------------------------------------
# Every Nth turn, and on /ratexp
# --------------------------------------------------------------------------


def test_the_session_is_asked_about_every_nth_turn(s):
    env = {"RATEXP_EVERY": "3"}
    asked = [s.turn(f"TURN-{i}", env=env) is not None for i in range(6)]
    assert asked == [False, False, True, False, False, True]


def test_the_baked_in_frequency_applies_when_nothing_overrides_it(s):
    """core stamps `default_survey_every` into the hook it serves; the harness bakes 2."""
    env = {"RATEXP_EVERY": None}
    assert [s.turn(env=env) is not None for _ in range(2)] == [False, True]


def test_a_repeated_stop_is_one_turn(s):
    env = {"RATEXP_EVERY": "2"}
    s.turn(env=env)
    assert s.stop(env) is None, "the same turn stopping again must not count twice"
    assert s.turn(env=env) is not None


def test_the_ratexp_turn_is_not_counted(s):
    """Asking to rate is not work, so it does not bring the next survey closer."""
    env = {"RATEXP_EVERY": "2"}
    assert s.turn(env=env) is None
    s.ratexp_command(env)
    picker = s.turn(env=env)
    assert picker is not None, "/ratexp asks at once"
    assert s.turn(env=env) is not None, "and the count carries on where it was"


def test_a_skill_is_never_asked_about_on_its_own(s):
    env = {"RATEXP_EVERY": "1"}
    s.run_hook(s.event("UserPromptExpansion", command_name="handoff"), env)
    picker = s.turn(env=env)
    assert picker["questions"][0]["question"] == SESSION_QUESTION, "only the session is"


def test_ratexp_asks_at_the_end_of_that_turn(s):
    assert s.turn() is None
    picker = s.ask()
    assert picker is not None, "/ratexp must ask"
    assert picker["questions"][0]["question"] == SESSION_QUESTION
    assert picker["questions"][0]["header"] == "RateXp"


def test_ratexp_arms_exactly_one_survey(s):
    """Asking once must not leave every later turn asking too."""
    assert s.ask() is not None
    assert s.turn() is None, "the turn after /ratexp must be quiet again"


def test_another_command_does_not_arm_a_survey(s):
    """Only /ratexp asks; every other slash command is none of this hook's business."""
    s.run_hook(s.event("UserPromptExpansion", command_name="clear"))
    assert s.turn() is None
    assert s.calls() == []


# --------------------------------------------------------------------------
# What gets sent
# --------------------------------------------------------------------------


def test_a_session_rating_carries_no_skill_name(s):
    """No skill ran, so the field is absent and the dashboard shows an empty cell."""
    env = {}
    picker = s.ask(env=env)
    s.pre(picker, env=env)
    s.run_hook(s.answer(picker, "Good"), env)
    fields = s.calls()[0]["fields"]
    assert "skill_name" not in fields
    assert fields["agent"] == "claude-code"
    assert fields["session_id"] == s.session
    assert fields["score"] == "1"


def test_the_upload_is_the_whole_session_not_one_turn(s):
    """A session rating covers everything so far, including earlier turns."""
    env = {}
    s.turn("FIRST-TURN-WORK", env=env)
    picker = s.ask("SECOND-TURN-WORK", env=env)
    assert picker is not None
    s.pre(picker, env=env)
    out, _, _ = s.run_hook(s.answer(picker, CONSENT), env)

    assert s.endpoints() == ["feedback", "transcript"]
    body = s.calls()[1]["body"]
    assert b"FIRST-TURN-WORK" in body, "earlier turns belong to the session too"
    assert b"SECOND-TURN-WORK" in body
    assert EARLIER.encode() in body, "the session is rated from byte zero"
    assert "transcript accepted" in out


def test_without_consent_nothing_of_the_session_travels(s):
    env = {}
    picker = s.ask(env=env)
    s.pre(picker, env=env)
    out, _, _ = s.run_hook(s.answer(picker, "Bad"), env)
    assert s.endpoints() == ["feedback"]
    assert SENTINEL.encode() not in s.curl_log_bytes()
    assert "kept private" in out


def test_a_typed_comment_is_sent_with_the_session_rating(s):
    env = {}
    picker = s.ask(env=env)
    s.pre(picker, env=env)
    s.run_hook(s.answer(picker, "Good", notes="the refactor went well"), env)
    assert s.calls()[0]["fields"]["comment"] == "the refactor went well"


# --------------------------------------------------------------------------
# Picker integrity
# --------------------------------------------------------------------------


def test_an_edited_session_picker_is_denied(s):
    """The survey wording is the hook's in session mode too."""
    env = {}
    picker = s.ask(env=env)
    edited = json.loads(json.dumps(picker))
    edited["questions"][0]["options"][0]["label"] = "Great"

    out, _, _ = s.pre(edited, env=env)
    assert json.loads(out)["hookSpecificOutput"]["permissionDecision"] == "deny"
    s.run_hook(s.answer(edited, "Good"), env)
    assert s.calls() == []


# --------------------------------------------------------------------------
# /ratexp <skill>: one skill's newest run
# --------------------------------------------------------------------------

SKILL = "handoff"  # any skill; nothing inside it knows about RateXp


def start_skill(s, name=SKILL, via="command"):
    """The user typing /<skill>, or Claude calling the Skill tool."""
    if via == "command":
        s.run_hook(s.event("UserPromptExpansion", command_name=name))
    else:
        s.run_hook(
            s.event(
                "PreToolUse", tool_name="Skill", tool_use_id="toolu_s1", tool_input={"skill": name}
            )
        )


def rate(s, name=SKILL):
    """/ratexp:<skill>, then the turn ends."""
    s.run_hook(s.event("UserPromptExpansion", command_name=f"ratexp:{name}"))
    return s.turn("THE-RATING-TURN")


@pytest.mark.parametrize("via", ["command", "tool"])
def test_a_skill_is_rated_on_its_newest_run_only(s, via):
    s.turn("BEFORE-THE-SKILL")
    start_skill(s, via=via)
    s.append(type="assistant", text="FIRST-RUN")
    start_skill(s, via=via)
    s.append(type="assistant", text="SECOND-RUN")
    picker = rate(s)
    assert picker["questions"][0]["question"].startswith(f"Rate {SKILL} — ")
    consent = picker["questions"][0]["options"][2]["description"]
    assert consent.startswith(f"Upload this run of {SKILL},"), "only the run is uploaded"
    s.pre(picker)
    s.run_hook(s.answer(picker, CONSENT))

    fields = s.calls()[0]["fields"]
    assert fields["skill_name"] == SKILL
    assert fields["agent"] == "claude-code"
    body = s.calls()[1]["body"]
    assert b"SECOND-RUN" in body
    for other in (b"FIRST-RUN", b"BEFORE-THE-SKILL", EARLIER.encode()):
        assert other not in body, f"an earlier part of the session leaked: {other!r}"


def test_the_newest_ratexp_request_decides(s):
    """An interrupted turn fires no Stop, so its /ratexp request is still waiting
    when the user asks again - and the new request decides what is rated."""
    start_skill(s)
    s.append(type="assistant", text="THE-RUN")
    s.run_hook(s.event("UserPromptExpansion", command_name="ratexp"))  # then interrupted
    picker = rate(s)
    assert picker["questions"][0]["question"].startswith(f"Rate {SKILL} — ")


def test_a_skill_that_never_ran_cannot_be_rated(s):
    s.run_hook(s.event("UserPromptExpansion", command_name=f"ratexp:{SKILL}"))
    out, _, _ = s.run_hook(s.event("Stop", stop_hook_active=False))
    assert f"no run of {SKILL}" in json.loads(out)["systemMessage"]
    assert s.calls() == []


def test_the_ratexp_request_is_not_taken_for_a_skill_run(s):
    start_skill(s)
    s.append(type="assistant", text="THE-RUN")
    picker = rate(s)
    s.pre(picker)
    s.run_hook(s.answer(picker, CONSENT))
    assert b"THE-RUN" in s.calls()[1]["body"], "the run started at /handoff, not at /ratexp"


# --------------------------------------------------------------------------
# Menu entries: skill names autocomplete after /ratexp
# --------------------------------------------------------------------------


def test_session_start_writes_ratexp_itself(s):
    s.run_hook(s.event("SessionStart", source="startup"))
    text = (s.script.parent / "commands" / "ratexp.md").read_text(encoding="utf-8")
    assert "RateXp target: $ARGUMENTS" in text, "a skill typed after /ratexp is the target"
    assert 'argument-hint: "[skill-name]"' in text


def test_session_start_adds_one_entry_per_installed_skill(s):
    for root in (s.cwd, s.home):
        for name in ("in-project", "in-home") if root is s.cwd else ("in-home",):
            folder = root / ".claude" / "skills" / name
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "SKILL.md").write_text("---\nname: x\n---\n", encoding="utf-8")
    s.run_hook(s.event("SessionStart", source="startup"))
    entries = s.script.parent / "commands" / "ratexp"
    assert sorted(p.name for p in entries.iterdir()) == ["in-home.md", "in-project.md"]
    text = (entries / "in-project.md").read_text(encoding="utf-8")
    assert "RateXp target: in-project" in text


def test_an_existing_command_is_left_alone(s):
    commands = s.script.parent / "commands"
    commands.mkdir()
    (commands / "ratexp.md").write_text("MINE\n", encoding="utf-8")
    s.run_hook(s.event("SessionStart", source="startup"))
    assert (commands / "ratexp.md").read_text(encoding="utf-8") == "MINE\n"


def test_a_skill_from_another_project_is_listed_but_not_rated(s):
    """Entries are global, so a skill seen in one project is listed in the next;
    it never ran in this session, so asking to rate it is refused."""
    other = s.tmp / "other-project"
    folder = other / ".claude" / "skills" / "elsewhere"
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text("---\nname: x\n---\n", encoding="utf-8")
    s.run_hook(s.event("SessionStart", source="startup", cwd=str(other)))
    assert (s.script.parent / "commands" / "ratexp" / "elsewhere.md").exists()
    s.run_hook(s.event("UserPromptExpansion", command_name="ratexp:elsewhere"))
    out, _, _ = s.run_hook(s.event("Stop", stop_hook_active=False))
    assert "no run of elsewhere" in json.loads(out)["systemMessage"]
    assert s.calls() == []


def test_only_the_user_can_run_ratexp(s):
    """The hook hears only the commands the user types, so a /ratexp the model ran
    itself would promise a survey that never comes."""
    folder = s.cwd / ".claude" / "skills" / SKILL
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text("---\nname: x\n---\n", encoding="utf-8")
    s.run_hook(s.event("SessionStart", source="startup"))
    commands = s.script.parent / "commands"
    for command in (commands / "ratexp.md", commands / "ratexp" / f"{SKILL}.md"):
        assert "disable-model-invocation: true" in command.read_text(encoding="utf-8")


def test_a_quoted_consent_label_still_uploads_the_session(s):
    """Claude Code quotes a label that holds a comma: `Good, "Yes, store trajectory", great`."""
    picker = s.ask()
    s.pre(picker)
    out, _, _ = s.run_hook(s.answer(picker, 'Good, "Yes, store trajectory", great'))
    assert s.endpoints() == ["feedback", "transcript"]
    assert s.calls()[0]["fields"]["comment"] == "great"
