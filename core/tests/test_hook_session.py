"""Black-box tests for plugins/claude-code/ratexp-claude.sh across a whole session,
where Claude Code runs no rating panel.

The whole session is rated every Nth turn on its own and whenever the user types
`/ratexp:rate`, always from byte zero, on core's default eval. Where the rating panel
runs, the same Stop hook counts the turns and leaves the survey to the panel: see
test_hook_panel.py. The sandbox, fake curl and event helpers come from test_hook.py.
"""

from __future__ import annotations

import json

import pytest
from test_hook import CONSENT, DEFAULT_EVAL, EARLIER, SENTINEL, Hook

# What the session survey asks.
SESSION_QUESTION = "Rate this Claude Code session — check all that apply or type a comment."


class SessionHook(Hook):
    """The Claude Code hook, rating the whole session."""

    script_name = "ratexp-claude.sh"

    def turn(self, text=SENTINEL, env=None):
        """One assistant turn: work lands in the transcript, then Stop fires."""
        self.append(type="assistant", text=text)
        return self.stop(env)

    def ratexp_command(self, env=None):
        """The user typing /ratexp:rate."""
        event = self.event("UserPromptExpansion", command_name="ratexp:rate", command_args="")
        return self.run_hook(event, env)

    def ask(self, text=SENTINEL, env=None):
        """The user typing /ratexp:rate, and the turn that follows. Returns its picker."""
        self.ratexp_command(env)
        return self.turn(text, env)


@pytest.fixture
def s(tmp_path):
    return SessionHook(tmp_path)


# --------------------------------------------------------------------------
# Every Nth turn, and on /ratexp:rate
# --------------------------------------------------------------------------


def test_the_session_is_asked_about_every_nth_turn(s):
    env = {"RATEXP_EVERY": "3"}
    asked = [s.turn(f"TURN-{i}", env=env) is not None for i in range(6)]
    assert asked == [False, False, True, False, False, True]


def test_the_turns_core_sent_apply_when_nothing_overrides_them(s):
    """core sends its `default_survey_every`; the harness keeps 5."""
    env = {"RATEXP_EVERY": None}
    assert [s.turn(env=env) is not None for _ in range(5)] == [False] * 4 + [True]


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
    assert picker is not None, "/ratexp:rate asks at once"
    assert s.turn(env=env) is not None, "and the count carries on where it was"


def test_a_skill_is_never_asked_about_on_its_own(s):
    env = {"RATEXP_EVERY": "1"}
    s.run_hook(s.event("UserPromptExpansion", command_name="handoff"), env)
    picker = s.turn(env=env)
    assert picker["questions"][0]["question"] == SESSION_QUESTION, "only the session is"


def test_ratexp_asks_at_the_end_of_that_turn(s):
    assert s.turn() is None
    picker = s.ask()
    assert picker is not None, "/ratexp:rate must ask"
    assert picker["questions"][0]["question"] == SESSION_QUESTION
    assert picker["questions"][0]["header"] == "RateXp"


def test_ratexp_arms_exactly_one_survey(s):
    """Asking once must not leave every later turn asking too."""
    assert s.ask() is not None
    assert s.turn() is None, "the turn after /ratexp:rate must be quiet again"


def test_another_command_does_not_arm_a_survey(s):
    """Only /ratexp:rate asks; every other slash command is none of this hook's business."""
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
# Evals: which survey is asked
# --------------------------------------------------------------------------


def test_every_nth_turn_asks_the_default_eval(s):
    """The survey asked on its own is core's default eval, as /ratexp:rate's is."""
    env = {"RATEXP_EVERY": "1"}
    picker = s.turn(env=env)
    assert picker["questions"][0]["question"] == SESSION_QUESTION
    s.pre(picker, env=env)
    s.run_hook(s.answer(picker, "Good"), env)
    assert s.calls()[0]["fields"]["eval_name"] == DEFAULT_EVAL


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


def test_a_quoted_consent_label_still_uploads_the_session(s):
    """Claude Code quotes a label that holds a comma: `Good, "Yes, store trajectory", great`."""
    picker = s.ask()
    s.pre(picker)
    out, _, _ = s.run_hook(s.answer(picker, 'Good, "Yes, store trajectory", great'))
    assert s.endpoints() == ["feedback", "transcript"]
    assert s.calls()[0]["fields"]["comment"] == "great"
