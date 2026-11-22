"""Black-box tests for what plugins/claude-code/ratexp-claude.sh does for the rating panel.

The plugin's rating panel (plugins/claude-code/hooks/rating-panel.tsx) asks; the script
keeps the state and sends. `panel-on <session>` tells the script the panel runs in that
session, so Stop counts the turns and marks the survey due instead of handing the model
a picker. `panel <session>` prints what the panel shows, as JSON, and consumes the due
mark. `send <session>` reads the answers from stdin and sends one rating per rated eval
of each rated target: the whole session, or the newest run of the skill that ran last.
The sandbox, fake curl and event helpers come from test_hook.py and test_hook_session.py.
"""

from __future__ import annotations

import json
import subprocess

import pytest
from test_hook import DEFAULT_EVAL, EARLIER, EVALS, LOCAL_URL, SENTINEL
from test_hook_session import SessionHook

SKILL = "handoff"  # any skill; nothing inside it knows about RateXp


class PanelHook(SessionHook):
    """The Claude Code hook, with the rating panel running in the session."""

    def command(self, *args, stdin=b"", env=None):
        """The panel running the script. Returns stdout, and the exit status."""
        done = subprocess.run(
            ["/bin/bash", str(self.script), *args],
            input=stdin,
            capture_output=True,
            env=self.env(**(env or {})),
            cwd=str(self.cwd),
            timeout=60,
        )
        out = done.stdout.decode("utf-8", "replace") + done.stderr.decode("utf-8", "replace")
        assert SENTINEL not in out, "the script must never echo the transcript"
        return out, done.returncode

    def panel_on(self, session=None):
        return self.command("panel-on", session or self.session)

    def panel(self, env=None):
        out, rc = self.command("panel", self.session, env=env)
        assert rc == 0
        return json.loads(out)

    def send(self, ratings, store="yes", transcript=None, session=None, env=None):
        """The panel's Send: the transcript, yes or no, then four fields per rating -
        the skill (empty for the whole session), the eval, good or bad, the comment."""
        fields = [str(transcript or self.transcript), store]
        for rating in ratings:
            fields += rating
        stdin = b"".join(field.encode("utf-8") + b"\0" for field in fields)
        out, rc = self.command("send", session or self.session, stdin=stdin, env=env)
        assert rc == 0
        return out.strip()

    def start_skill(self, name=SKILL, via="command"):
        """The user typing /<skill>, or Claude calling the Skill tool."""
        if via == "command":
            self.run_hook(self.event("UserPromptExpansion", command_name=name))
        else:
            self.run_hook(
                self.event(
                    "PreToolUse",
                    tool_name="Skill",
                    tool_use_id="toolu_s1",
                    tool_input={"skill": name},
                )
            )

    def bodies(self):
        return [c["body"] for c in self.calls() if c["endpoint"] == "transcript"]


@pytest.fixture
def h(tmp_path):
    return PanelHook(tmp_path)


SESSION_GOOD = ("", DEFAULT_EVAL, "good", "")


# --------------------------------------------------------------------------
# What the panel shows
# --------------------------------------------------------------------------


def test_the_panel_shows_every_eval_core_sent(h):
    shown = h.panel()
    assert [e["name"] for e in shown["evals"]] == list(EVALS)
    first = shown["evals"][0]
    assert first == {
        "name": DEFAULT_EVAL,
        "question": "Rate it",
        "good": "Good",
        "good_description": "The result was helpful.",
        "bad": "Bad",
        "bad_description": "Not helpful.",
    }, "each answer comes with what it means"
    assert shown["skill"] is None, "no skill has run yet"
    assert shown["due"] is False


def test_the_panel_asks_core_when_nothing_was_kept(h):
    h.settings_kept().unlink()
    assert [e["name"] for e in h.panel()["evals"]] == list(EVALS)
    assert [c["endpoint"] for c in h.calls()] == ["hook-settings"]


def test_the_panel_says_so_when_no_survey_can_be_loaded(h):
    h.settings_kept().unlink()
    h.answer_settings(None)
    assert h.panel() == {
        "error": f"RateXp: the surveys could not be loaded from {LOCAL_URL}, so no survey can be asked."
    }


@pytest.mark.parametrize("via", ["command", "tool"])
def test_the_panel_offers_the_skill_that_ran_last(h, via):
    h.start_skill("poem-creator", via=via)
    h.start_skill(SKILL, via=via)
    assert h.panel()["skill"] == SKILL


def test_ratexp_rate_is_not_taken_for_a_skill_run(h):
    h.start_skill()
    h.request()
    assert h.panel()["skill"] == SKILL


@pytest.mark.parametrize("session", ["../x", "a b", ""])
def test_a_session_that_is_not_a_name_is_refused(h, session):
    out, rc = h.command("panel", session)
    assert rc == 1 and out == ""


# --------------------------------------------------------------------------
# The survey: the panel asks, never the model
# --------------------------------------------------------------------------


def test_with_the_panel_ratexp_rate_hands_the_model_no_picker(h):
    h.panel_on()
    h.request()
    assert h.turn() is None
    assert h.calls() == []


def test_with_the_panel_every_nth_turn_is_marked_due_for_it(h):
    h.panel_on()
    env = {"RATEXP_EVERY": "2"}
    assert [h.turn(f"TURN-{i}", env=env) for i in range(2)] == [None, None], "no picker"
    assert h.panel()["due"] is True
    assert h.panel()["due"] is False, "opening the panel consumed it"
    h.turn("TURN-2", env=env)
    assert h.panel()["due"] is False
    h.turn("TURN-3", env=env)
    assert h.panel()["due"] is True


def test_a_repeated_stop_is_one_turn_for_the_panel_too(h):
    h.panel_on()
    env = {"RATEXP_EVERY": "2"}
    h.turn(env=env)
    h.stop(env)
    assert h.panel()["due"] is False


# --------------------------------------------------------------------------
# Send: what is rated
# --------------------------------------------------------------------------


def test_the_session_is_rated_from_byte_zero(h):
    h.append(type="assistant", text=SENTINEL)
    out = h.send([("", DEFAULT_EVAL, "good", "nice work")])
    assert h.endpoints() == ["feedback", "transcript"]
    fields = h.calls()[0]["fields"]
    assert fields["agent"] == "claude-code"
    assert fields["session_id"] == h.session
    assert fields["eval_name"] == DEFAULT_EVAL
    assert fields["score"] == "1"
    assert fields["comment"] == "nice work"
    assert "skill_name" not in fields, "a session rating names no skill"
    assert h.bodies() == [h.transcript.read_bytes()], "the whole session, from byte zero"
    assert out == f"RateXp: feedback and transcript accepted by {LOCAL_URL}."


def test_a_skill_is_rated_on_its_newest_run_only(h):
    """Each run is bounded at both ends: it starts where its own run started, and ends
    when the conversation moves on - not at /ratexp:rate."""
    for i in range(3):
        h.start_skill()
        h.append(type="assistant", text=f"RUN-{i}")
        h.append(type="user", text=f"AFTER-RUN-{i}")
    h.append(type="assistant", text="UNRELATED-WORK")
    h.request()
    h.send([(SKILL, DEFAULT_EVAL, "bad", "")])
    assert h.calls()[0]["fields"]["skill_name"] == SKILL
    assert h.calls()[0]["fields"]["score"] == "2"
    (body,) = h.bodies()
    assert b"RUN-2" in body
    for other in (b"RUN-0", b"RUN-1", b"AFTER-RUN-2", b"UNRELATED-WORK", EARLIER.encode()):
        assert other not in body, f"not part of the newest run: {other!r}"


def test_a_skill_that_asks_through_a_picker_keeps_its_answer(h):
    """AskUserQuestion answers come back as tool results, not the user speaking."""
    h.start_skill()
    h.append(
        type="assistant", message={"content": [{"type": "tool_use", "name": "AskUserQuestion"}]}
    )
    h.append(type="user", message={"content": [{"type": "tool_result", "content": "PICKED"}]})
    h.append(type="assistant", text="THE-POEM")
    h.append(type="user", text="NEXT-TASK")
    h.send([(SKILL, DEFAULT_EVAL, "good", "")])
    (body,) = h.bodies()
    assert b"PICKED" in body and b"THE-POEM" in body
    assert b"NEXT-TASK" not in body


def test_a_skill_that_opens_the_session_can_be_rated(h):
    """The session's first prompt comes before Claude Code writes its transcript."""
    h.transcript.unlink()
    h.start_skill()
    h.append(type="assistant", text="THE-RUN")
    h.send([(SKILL, DEFAULT_EVAL, "good", "")])
    assert b"THE-RUN" in h.bodies()[0]


def test_each_eval_of_each_target_is_a_rating_of_its_own(h):
    h.start_skill()
    h.append(type="assistant", text="THE-RUN")
    h.append(type="user", text="NEXT-TASK")
    out = h.send(
        [
            ("", DEFAULT_EVAL, "good", "fine"),
            ("", "code-quality", "bad", ""),
            (SKILL, DEFAULT_EVAL, "good", "fine"),
            (SKILL, "code-quality", "bad", ""),
        ]
    )
    feedback = [c["fields"] for c in h.calls() if c["endpoint"] == "feedback"]
    assert [(f.get("skill_name"), f["eval_name"], f["score"]) for f in feedback] == [
        (None, DEFAULT_EVAL, "1"),
        (None, "code-quality", "2"),
        (SKILL, DEFAULT_EVAL, "1"),
        (SKILL, "code-quality", "2"),
    ]
    assert len({f["request_id"] for f in feedback}) == 4
    bodies = h.bodies()
    assert len(bodies) == 4, "each rating carries its own conversation"
    assert all(b"NEXT-TASK" in body for body in bodies[:2]), "the session's"
    assert all(b"NEXT-TASK" not in body for body in bodies[2:]), "the skill's run only"
    assert out == f"RateXp: feedback and transcripts accepted by {LOCAL_URL} for 4 ratings."


def test_without_consent_nothing_of_the_session_travels(h):
    h.append(type="assistant", text=SENTINEL)
    out = h.send([SESSION_GOOD, ("", "code-quality", "good", "")], store="no")
    assert h.endpoints() == ["feedback", "feedback"]
    assert SENTINEL.encode() not in h.curl_log_bytes()
    assert (
        out == f"RateXp: feedback accepted by {LOCAL_URL} for 2 ratings. Transcripts kept private."
    )


@pytest.mark.parametrize(
    "comment",
    [
        pytest.param("first line\nsecond line", id="newlines"),
        pytest.param('he said "fine" and it\'s fine', id="quotes"),
        pytest.param("$(touch pwned) `touch pwned`", id="shell-metacharacters"),
    ],
)
def test_a_comment_arrives_verbatim(h, comment):
    h.send([("", DEFAULT_EVAL, "good", comment)], store="no")
    assert h.calls()[0]["fields"]["comment"] == comment
    assert not (h.cwd / "pwned").exists()


# --------------------------------------------------------------------------
# Send: what is refused
# --------------------------------------------------------------------------


def test_a_skill_that_never_ran_is_refused(h):
    out = h.send([(SKILL, DEFAULT_EVAL, "good", "")])
    assert out == f"RateXp: feedback not sent: there is no run of {SKILL} in this session to rate."
    assert h.calls() == []


@pytest.mark.parametrize(
    "rating",
    [
        ("", "nope", "good", ""),
        ("", DEFAULT_EVAL, "maybe", ""),
    ],
    ids=["unknown-eval", "unknown-verdict"],
)
def test_an_answer_the_script_does_not_know_sends_nothing(h, rating):
    out = h.send([SESSION_GOOD, rating])
    assert out == "RateXp: feedback not sent: the ratings could not be read."
    assert h.calls() == []


@pytest.mark.parametrize(
    "fields",
    [[], ["only-a-transcript"], [None, "maybe", *SESSION_GOOD], [None, "yes", "", DEFAULT_EVAL]],
    ids=["nothing", "no-consent-word", "bad-consent-word", "half-a-rating"],
)
def test_malformed_answers_send_nothing(h, fields):
    fields = [str(h.transcript) if f is None else f for f in fields]
    stdin = b"".join(f.encode() + b"\0" for f in fields)
    out, rc = h.command("send", h.session, stdin=stdin)
    assert rc == 0
    assert out.strip() == "RateXp: feedback not sent: the ratings could not be read."
    assert h.calls() == []


def test_a_symlinked_transcript_is_not_read(h):
    real = h.tmp / "real.jsonl"
    real.write_text(f"{SENTINEL}\n", encoding="utf-8")
    link = h.tmp / "link.jsonl"
    link.symlink_to(real)
    assert h.send([SESSION_GOOD], transcript=link) == (
        "RateXp: feedback not sent: the ratings could not be read."
    )
    assert h.calls() == []


def test_a_transcript_over_four_mib_is_not_uploaded(h):
    with h.transcript.open("ab") as fh:
        fh.write(b"x" * (4 * 1024 * 1024 + 1))
    out = h.send([SESSION_GOOD])
    assert h.endpoints() == ["feedback"]
    assert out == f"RateXp: feedback accepted by {LOCAL_URL}. Transcript could not be sent."


def test_failed_feedback_sends_no_transcript(h):
    out = h.send([SESSION_GOOD], env={"RATEXP_CURL_STATUS": "500"})
    assert h.endpoints() == ["feedback"], "exactly one attempt, no retry"
    assert out == f"RateXp: feedback could not be sent to {LOCAL_URL}."
