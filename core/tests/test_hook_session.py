"""Black-box tests for core/ratexp-coding-agent.sh.

Its own script, beside ratexp-skill.sh in core/. It rates whole conversations
rather than one skill's runs: it counts turns, so the survey lands wherever the
Nth turn falls - part way through a long session, at the end of a short one - and
`/ratexp` asks for it by name. What is rated is always the session so far, from byte
zero. The sandbox, fake curl and event helpers all come from test_hook.py.
"""

from __future__ import annotations

import json

import pytest
from test_hook import CONSENT, EARLIER, SENTINEL, Hook

# What the session survey asks. The skill survey says "Rate <skill> - ..." instead.
SESSION_QUESTION = "Rate this Claude Code session — check all that apply or type a comment."


class SessionHook(Hook):
    """The coding-agent hook: its own script in core/, rating the whole session."""

    script_name = "ratexp-coding-agent.sh"

    def turn(self, text=SENTINEL, env=None):
        """One assistant turn: work lands in the transcript, then Stop fires."""
        self.append(type="assistant", text=text)
        return self.stop(env)

    def ratexp_command(self, env=None):
        """The user typing /ratexp."""
        return self.run_hook(self.event("UserPromptExpansion", command_name="ratexp"), env)


@pytest.fixture
def s(tmp_path):
    return SessionHook(tmp_path)


# --------------------------------------------------------------------------
# Counting turns
# --------------------------------------------------------------------------


def test_the_survey_asks_on_the_nth_turn(s):
    """RATEXP_EVERY=3 means turns 1 and 2 pass quietly and turn 3 asks."""
    env = {"RATEXP_EVERY": "3"}
    assert s.turn(env=env) is None, "turn 1 must stay silent"
    assert s.turn(env=env) is None, "turn 2 must stay silent"
    picker = s.turn(env=env)
    assert picker is not None, "turn 3 must ask"
    assert picker["questions"][0]["question"] == SESSION_QUESTION
    assert picker["questions"][0]["header"] == "RateXp"


def test_it_asks_again_later_in_the_same_session(s):
    """A long session is rated more than once, every Nth turn throughout."""
    env = {"RATEXP_EVERY": "2"}
    asked = [s.turn(env=env) is not None for _ in range(6)]
    assert asked == [False, True, False, True, False, True]


def test_a_short_session_is_never_asked(s):
    """Fewer turns than the interval means no survey at all - it does not nag."""
    env = {"RATEXP_EVERY": "10"}
    assert [s.turn(env=env) for _ in range(4)] == [None, None, None, None]
    assert s.calls() == []


# --------------------------------------------------------------------------
# /ratexp
# --------------------------------------------------------------------------


def test_ratexp_asks_without_waiting_for_the_count(s):
    """The user can ask for the survey by name at any point."""
    env = {"RATEXP_EVERY": "50"}  # far out of reach on its own
    assert s.turn(env=env) is None
    s.ratexp_command(env)
    assert s.turn(env=env) is not None, "/ratexp must bring the survey forward"


def test_ratexp_arms_exactly_one_survey(s):
    """Asking once must not leave every later turn asking too."""
    env = {"RATEXP_EVERY": "50"}
    s.ratexp_command(env)
    assert s.turn(env=env) is not None
    assert s.turn(env=env) is None, "the turn after /ratexp must be quiet again"


def test_another_command_does_not_arm_a_survey(s):
    """Only /ratexp asks; every other slash command is none of this hook's business."""
    env = {"RATEXP_EVERY": "50"}
    s.run_hook(s.event("UserPromptExpansion", command_name="clear"), env)
    assert s.turn(env=env) is None
    assert s.calls() == []


# --------------------------------------------------------------------------
# What gets sent
# --------------------------------------------------------------------------


def test_a_session_rating_carries_no_skill_name(s):
    """No skill ran, so the field is absent and the dashboard shows an empty cell."""
    env = {"RATEXP_EVERY": "1"}
    picker = s.turn(env=env)
    s.pre(picker, env=env)
    s.run_hook(s.answer(picker, "Good"), env)
    fields = s.calls()[0]["fields"]
    assert "skill_name" not in fields
    assert fields["agent"] == "claude-code"
    assert fields["session_id"] == s.session
    assert fields["score"] == "1"


def test_the_upload_is_the_whole_session_not_one_turn(s):
    """A session rating covers everything so far, including earlier turns."""
    env = {"RATEXP_EVERY": "2"}
    s.turn("FIRST-TURN-WORK", env=env)
    picker = s.turn("SECOND-TURN-WORK", env=env)
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
    env = {"RATEXP_EVERY": "1"}
    picker = s.turn(env=env)
    s.pre(picker, env=env)
    out, _, _ = s.run_hook(s.answer(picker, "Bad"), env)
    assert s.endpoints() == ["feedback"]
    assert SENTINEL.encode() not in s.curl_log_bytes()
    assert "kept private" in out


def test_a_typed_comment_is_sent_with_the_session_rating(s):
    env = {"RATEXP_EVERY": "1"}
    picker = s.turn(env=env)
    s.pre(picker, env=env)
    s.run_hook(s.answer(picker, "Good", notes="the refactor went well"), env)
    assert s.calls()[0]["fields"]["comment"] == "the refactor went well"


# --------------------------------------------------------------------------
# Picker integrity
# --------------------------------------------------------------------------


def test_an_edited_session_picker_is_denied(s):
    """The survey wording is the hook's in session mode too."""
    env = {"RATEXP_EVERY": "1"}
    picker = s.turn(env=env)
    edited = json.loads(json.dumps(picker))
    edited["questions"][0]["options"][0]["label"] = "Great"

    out, _, _ = s.pre(edited, env=env)
    assert json.loads(out)["hookSpecificOutput"]["permissionDecision"] == "deny"
    s.run_hook(s.answer(edited, "Good"), env)
    assert s.calls() == []


def test_a_skills_survey_is_left_alone_by_this_hook(s):
    """The two hooks are separate scripts owning different questions. A skill's
    picker is none of this one's business: it is passed over in silence, not
    denied, and above all never answered on the skill's behalf."""
    env = {"RATEXP_EVERY": "1"}
    picker = s.turn(env=env)
    foreign = json.loads(json.dumps(picker))
    foreign["questions"][0]["question"] = (
        "Rate poem-creator — check all that apply or type a comment."
    )

    out, _, _ = s.pre(foreign, env=env)
    assert out == "", "another hook's picker must not be denied, only ignored"
    s.run_hook(s.answer(foreign, CONSENT), env)
    assert s.calls() == []
    assert SENTINEL.encode() not in s.curl_log_bytes()
