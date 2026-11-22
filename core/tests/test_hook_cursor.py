"""Black-box tests for plugins/cursor/ratexp-cursor.sh.

The RateXp plugin runs it for whoever uses Cursor. It asks every Nth turn on its own
(through the stop hook) and on /ratexp:rate, in one question menu: what to rate - the
whole chat, the newest run of a skill, or both - True or False for each eval the user
picks, consent, and one comment for every rating. Rating needs no hook: the plugin's ratexp skill has the agent run
`ask`, which finds the chat's transcript where Cursor's editor and CLI both keep it
and prints the questions; the agent asks the user, and `report` sends one rating per
rated eval of each rated target. Consent is a required word, never a default.

The sandbox, fake curl and helpers come from test_hook.py.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time

import pytest
from test_hook import (
    CLAUDE_PLUGIN,
    CURSOR_PLUGIN,
    DEFAULT_EVAL,
    EARLIER,
    EVALS,
    SENTINEL,
    Hook,
)

SKILL = "poem-creator"


class CursorHook(Hook):
    """The script in the Cursor plugin, one skill of the user's, and one chat transcript."""

    source = CURSOR_PLUGIN
    script_name = "ratexp-cursor.sh"
    manifest_dir = ".cursor-plugin"

    def __init__(self, tmp_path):
        super().__init__(tmp_path)
        # Finding a skill's newest run means finding a line in a long file.
        os.symlink(shutil.which("grep"), self.bin / "grep")
        self.skill = SKILL
        self.skills = self.home / ".cursor" / "skills"
        self.add_skill(SKILL)
        # Where Cursor's editor and CLI both keep a chat's transcript.
        chat = self.home / ".cursor" / "projects" / "ws" / "agent-transcripts" / self.session
        chat.mkdir(parents=True)
        self.transcript = chat / f"{self.session}.jsonl"
        self.line(EARLIER)

    def calls(self, settings=False):
        """Every fake-curl call, oldest first. `ask` also asks core for the surveys each
        time, as the user waits for one anyway; those calls are left out unless
        `settings` is set."""
        found = super().calls()
        return found if settings else [c for c in found if c["endpoint"] != "hook-settings"]

    def add_skill(self, name):
        folder = self.skills / name
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "SKILL.md").write_text(f"---\nname: {name}\n---\nDo it.\n", encoding="utf-8")
        return folder

    def line(self, text, role="user"):
        """One transcript line, in Cursor's shape."""
        self.append(role=role, message={"content": [{"type": "text", "text": text}]})

    def use(self, name=SKILL, work=SENTINEL):
        """The user typing /<skill>: Cursor attaches its SKILL.md, then the agent works."""
        self.run_start = self.transcript.stat().st_size
        self.line(f"Skill Name: {name}\nPath: {self.skills / name / 'SKILL.md'}")
        self.line(work, role="assistant")

    def request(self, text="/ratexp:rate"):
        """The user's /ratexp:rate message, with the plugin's ratexp skill that Cursor
        attaches to it."""
        skill = self.plugin / "skills" / "ratexp" / "SKILL.md"
        self.line(
            f"<manually_attached_skills>\nSkill Name: ratexp\nPath: {skill}\n"
            "SKILL.md content:\n# RateXp survey\n\nRun ...\n</manually_attached_skills>\n"
            f"<user_query>\n{text}\n</user_query>"
        )

    def run(self, *args, cwd=None, env=None):
        """The agent running the script. Returns stdout and stderr joined, and rc."""
        done = subprocess.run(
            ["/bin/bash", str(self.script), *args],
            capture_output=True,
            env=self.env(**(env or {})),
            cwd=str(cwd or self.cwd),
            timeout=60,
        )
        out = done.stdout.decode("utf-8", "replace") + done.stderr.decode("utf-8", "replace")
        assert SENTINEL not in out, "the script must never echo the transcript"
        return out, done.returncode

    def ask(self, **kw):
        """`ask`, as the plugin's skill and the stop hook's followup both run it."""
        return self.run("ask", **kw)

    def report(self, *args, **kw):
        return self.run("report", *args, **kw)

    def rate(self, what="chat", sharing="share", evals=((DEFAULT_EVAL, "good"),), comment="", **kw):
        """`report` the way the agent runs it: what is rated, consent, the comment, then two
        words for each rated eval - its name, and good or bad."""
        return self.report(what, sharing, comment, *(word for one in evals for word in one), **kw)

    def end_turn(self, generation, status="completed", env=None, model=None):
        """Cursor's stop hook at the end of a turn. Returns what it printed."""
        event = {
            "hook_event_name": "stop",
            "conversation_id": self.session,
            "generation_id": generation,
            "transcript_path": str(self.transcript),
            "status": status,
        }
        if model is not None:
            event["model"] = model
        return self.run_hook(event, env)[0]

    def session_start(self):
        event = {"hook_event_name": "sessionStart", "workspace_roots": [str(self.cwd)]}
        out, _, _ = self.run_hook(event)
        return out


@pytest.fixture
def c(tmp_path):
    return CursorHook(tmp_path)


# --------------------------------------------------------------------------
# /ratexp:rate: what the survey asks
# --------------------------------------------------------------------------


def test_ratexp_rate_asks_what_to_rate_the_evals_and_consent(c):
    c.use(work="SKILL-WORK")
    c.request()
    out, rc = c.ask()
    assert rc == 0
    assert out.startswith("RateXp survey for this chat.")
    assert f'"Eval what?" - options "This chat", "Last skill: {SKILL}"' in out
    for name, (question, good, good_meaning, bad, bad_meaning) in EVALS.items():
        question = question.replace("{subject}", "it")
        assert f'"{question} — {good}: {good_meaning}"' in out, "each row says what it means"
        assert f'"{question} — {bad}: {bad_meaning}"' in out
        assert f'"{question}" is {name}' in out, "the agent maps each question to its eval"
    assert '"Store the trajectory?" - options "yes", then "no"' in out
    assert '"Any comment?" - options "No comment"' in out
    assert "one more AskQuestion" not in out, "one menu asks everything"
    assert f'bash "{c.script}" report' in out, "the agent is told exactly what to run"


def test_without_a_skill_only_the_chat_is_offered(c):
    c.request()
    out, rc = c.ask()
    assert rc == 0
    assert "Eval what?" not in out
    assert "- First chat." in out


def test_ratexps_own_skill_is_not_a_run(c):
    """The /ratexp:rate request attaches the plugin's own ratexp skill."""
    c.use(work="THE-RUN")
    c.request()
    out, _ = c.ask()
    assert f'"Last skill: {SKILL}"' in out


def test_the_newest_skill_is_offered(c):
    c.add_skill("haiku")
    c.use(work="POEM")
    c.use("haiku", work="HAIKU")
    c.request()
    out, _ = c.ask()
    assert '"Last skill: haiku"' in out


def test_plain_ratexp_asks_the_same(c):
    """The plugin's skill is named ratexp, so Cursor also takes plain /ratexp."""
    c.request("/ratexp")
    out, rc = c.ask()
    assert rc == 0
    assert out.startswith("RateXp survey for this chat.")


def test_the_comment_is_handed_over_in_single_quotes(c):
    """Inside double quotes, `backticks` or $(...) the user typed would run as commands."""
    c.request()
    out, _ = c.ask()
    assert "<share|private> '<comment>' [<eval> <good|bad>]..." in out


def test_nothing_is_asked_without_a_ratexp_request(c):
    """The chat is found by its /ratexp:rate request; without one there is nothing to rate."""
    out, rc = c.ask()
    assert rc == 1
    assert "could not find this chat" in out


# --------------------------------------------------------------------------
# What is rated: the chat, the skill's newest run, or both
# --------------------------------------------------------------------------


def test_the_chat_is_rated_from_byte_zero(c):
    c.use(work="SKILL-WORK")
    c.line("ORDINARY-WORK", role="assistant")
    c.request()
    c.ask()
    out, rc = c.rate("chat")
    assert rc == 0
    assert c.endpoints() == ["feedback", "transcript"]
    fields = c.calls()[0]["fields"]
    assert fields["agent"] == "cursor"
    assert fields["session_id"] == c.session
    assert fields["eval_name"] == DEFAULT_EVAL
    assert fields["score"] == "1"
    assert "skill_name" not in fields, "a chat rating names no skill"
    body = c.calls()[1]["body"]
    assert EARLIER.encode() in body, "the whole chat, from byte zero"
    assert b"SKILL-WORK" in body and b"ORDINARY-WORK" in body
    assert "transcript accepted" in out


def test_the_survey_itself_is_not_uploaded(c):
    """What is rated ends where the user asked; their answer is not part of it."""
    c.request()
    c.ask()
    c.line("SURVEY-ANSWER")
    c.rate("chat")
    assert b"SURVEY-ANSWER" not in c.calls()[1]["body"]


def test_a_skill_is_rated_on_its_newest_run_only(c):
    c.use(work="RUN-1")
    c.line("BETWEEN-RUNS", role="assistant")
    c.use(work="RUN-2")
    c.request()
    c.ask()
    c.rate("skill", evals=[(DEFAULT_EVAL, "bad")], comment="too short")
    fields = c.calls()[0]["fields"]
    assert fields["skill_name"] == SKILL
    assert fields["score"] == "2"
    assert fields["comment"] == "too short"
    body = c.calls()[1]["body"]
    assert b"RUN-2" in body
    for other in (b"RUN-1", b"BETWEEN-RUNS", EARLIER.encode()):
        assert other not in body, f"an earlier part of the chat leaked: {other!r}"


def test_a_skill_rating_leaves_out_what_came_after_the_run(c):
    """The run ends when the conversation moves on, not at /ratexp:rate. Its question
    and the user's answer belong to it; the next request does not."""
    c.line(f"Skill Name: {SKILL}\nPath: {c.skills / SKILL / 'SKILL.md'}")
    c.line("Which mood would you like?", role="assistant")
    c.line("SAD-PLEASE")
    c.line("THE-POEM", role="assistant")
    c.line("UNRELATED-REQUEST")
    c.line("UNRELATED-WORK", role="assistant")
    c.request()
    c.ask()
    c.rate("skill")
    body = c.calls()[1]["body"]
    assert b"SAD-PLEASE" in body and b"THE-POEM" in body
    for dropped in (b"UNRELATED-REQUEST", b"UNRELATED-WORK", b"RateXp survey"):
        assert dropped not in body, f"not part of the run: {dropped!r}"


def test_a_skill_the_agent_picked_itself_is_found(c):
    """Without /<skill>, the agent loads a skill by reading its SKILL.md."""
    c.append(
        role="assistant",
        message={
            "content": [
                {
                    "type": "tool_use",
                    "name": "Read",
                    "input": {"path": str(c.skills / SKILL / "SKILL.md")},
                }
            ]
        },
    )
    c.line("PICKED-RUN", role="assistant")
    c.request()
    out, rc = c.ask()
    assert rc == 0 and f'"Last skill: {SKILL}"' in out
    c.rate("skill")
    body = c.calls()[1]["body"]
    assert b"PICKED-RUN" in body
    assert EARLIER.encode() not in body


def test_both_rates_each_eval_for_the_chat_and_for_the_skill(c):
    c.use(work="THE-RUN")
    c.line("NEXT-TASK")
    c.line("LATER-WORK", role="assistant")
    c.request()
    c.ask()
    out, rc = c.rate(
        "both", evals=[(DEFAULT_EVAL, "good"), ("code-quality", "bad")], comment="fine"
    )
    assert rc == 0
    feedback = [call for call in c.calls() if call["endpoint"] == "feedback"]
    assert [
        (f["fields"].get("skill_name"), f["fields"]["eval_name"], f["fields"]["score"])
        for f in feedback
    ] == [
        (None, DEFAULT_EVAL, "1"),
        (None, "code-quality", "2"),
        (SKILL, DEFAULT_EVAL, "1"),
        (SKILL, "code-quality", "2"),
    ]
    assert [f["fields"].get("comment") for f in feedback] == ["fine"] * 4, "one comment for all"
    assert len({f["fields"]["request_id"] for f in feedback}) == 4, "each rating is its own"
    bodies = [call["body"] for call in c.calls() if call["endpoint"] == "transcript"]
    assert len(bodies) == 4, "each rating carries its own conversation"
    assert all(b"LATER-WORK" in body for body in bodies[:2]), "the chat's"
    assert all(b"LATER-WORK" not in body for body in bodies[2:]), "the skill's run only"
    assert "feedback and transcripts accepted" in out and "for 4 ratings" in out


def test_a_skill_cannot_be_rated_when_none_ran(c):
    c.request()
    c.ask()
    out, rc = c.rate("skill")
    assert rc == 1
    assert "no skill has run in this chat" in out
    assert c.calls() == []
    assert c.rate("chat")[1] == 0, "the survey is still waiting for a usable answer"


def other_chat(c, *user_lines):
    """A second chat, written to after this one - as when an agent still works there."""
    other = c.transcript.parent.parent / "other-chat" / "other-chat.jsonl"
    other.parent.mkdir()
    other.write_text(
        "".join(json.dumps({"role": "user", "message": {"content": t}}) + "\n" for t in user_lines),
        encoding="utf-8",
    )
    later = time.time() + 5
    os.utime(other, (later, later))


def test_the_chat_that_asked_is_rated_not_the_newest_one(c):
    """Rated a minute ago and still busy, the other chat has the survey and the
    script's path in it - only its latest message counts, and that is not a request."""
    c.request()
    other_chat(c, "# RateXp survey\n/ratexp:rate", "now tidy up core/ratexp-cursor.sh")
    c.ask()
    c.rate("chat", "private")
    assert c.calls()[0]["fields"]["session_id"] == c.session


def test_the_chat_cursor_names_is_the_one_rated(c):
    """Cursor tells the agent's commands which chat they belong to; no guessing then."""
    c.request()
    other_chat(c, "# RateXp survey\n/ratexp:rate")  # asking too, and newer
    env = {"CURSOR_CONVERSATION_ID": c.session, "AGENT_TRANSCRIPTS": c.transcript.parent.parent}
    c.ask(env=env)
    c.rate("chat", "private")
    assert c.calls()[0]["fields"]["session_id"] == c.session


def test_an_answer_rates_the_chat_it_was_given_in(c):
    """Two chats asked at once. The answer given in the first never sends the
    second, even though the second's survey is the newer one."""
    transcripts = c.transcript.parent.parent
    other_chat(c, "# RateXp survey\n/ratexp:rate")
    c.ask(env={"CURSOR_CONVERSATION_ID": "other-chat", "AGENT_TRANSCRIPTS": transcripts})
    c.request()
    c.ask(env={"CURSOR_CONVERSATION_ID": c.session, "AGENT_TRANSCRIPTS": transcripts})
    c.rate("chat", "private", env={"CURSOR_CONVERSATION_ID": "other-chat"})
    assert c.calls()[0]["fields"]["session_id"] == "other-chat"


# --------------------------------------------------------------------------
# Evals: which are rated
# --------------------------------------------------------------------------


def test_only_the_evals_the_answer_names_are_rated(c):
    c.request()
    c.ask()
    c.rate("chat", "private", evals=[("code-quality", "bad")], comment="a typo or two")
    fields = [call["fields"] for call in c.calls()]
    assert len(fields) == 1
    assert fields[0]["eval_name"] == "code-quality"
    assert fields[0]["score"] == "2"
    assert fields[0]["comment"] == "a typo or two"


def test_no_eval_rated_sends_nothing_and_ends_the_survey(c):
    """Every eval left with both or neither option ticked: nothing to send."""
    c.request()
    c.ask()
    out, rc = c.rate("chat", evals=[])
    assert rc == 0
    assert out.strip() == "RateXp: feedback not sent: no eval was rated."
    assert c.calls() == []
    assert c.rate("chat")[1] == 1, "that answer ended the survey"


def test_an_eval_core_does_not_offer_is_refused(c):
    c.request()
    c.ask()
    out, rc = c.rate("chat", evals=[("nope", "good")])
    assert rc == 1
    assert "no eval named nope" in out
    assert ", ".join(EVALS) in out, "every eval core offers is listed"
    assert c.calls() == []
    assert c.rate("chat")[1] == 0, "the survey is still waiting for a usable answer"


@pytest.mark.parametrize(
    "comment",
    [
        pytest.param("it's fine", id="single-quote"),
        pytest.param("héllo — 世界 ✓", id="unicode"),
        pytest.param("$(touch pwned) `id`", id="shell-metacharacters"),
    ],
)
def test_a_comment_arrives_verbatim(c, comment):
    c.request()
    c.ask()
    c.rate("chat", "private", comment=comment)
    assert c.calls()[0]["fields"]["comment"] == comment
    assert not (c.cwd / "pwned").exists()


# --------------------------------------------------------------------------
# Every Nth turn: the stop hook
# --------------------------------------------------------------------------


def followup(out):
    return json.loads(out).get("followup_message", "")


def test_the_chat_is_asked_about_every_nth_turn(c):
    env = {"RATEXP_EVERY": "2"}
    assert followup(c.end_turn("gen-1", env=env)) == ""
    text = followup(c.end_turn("gen-2", env=env))
    assert "RateXp survey" in text, "its own turn is recognised by this"
    assert f'bash "{c.script}" ask`' in text, "the same survey /ratexp:rate starts"


def test_the_survey_turn_is_not_counted(c):
    env = {"RATEXP_EVERY": "2"}
    c.end_turn("gen-1", env=env)
    c.line("RateXp survey: run ...")  # the followup Cursor sent
    assert followup(c.end_turn("gen-2", env=env)) == ""
    c.line("next task")
    assert followup(c.end_turn("gen-3", env=env)) != ""


def test_a_ratexp_turn_is_not_counted(c):
    env = {"RATEXP_EVERY": "2"}
    c.end_turn("gen-1", env=env)
    c.request()
    assert followup(c.end_turn("gen-2", env=env)) == ""


def test_the_turn_that_answers_the_survey_is_not_counted(c):
    """Without a question tool the user answers in a message of their own. That
    turn is still the survey, not work."""
    env = {"RATEXP_EVERY": "2"}
    c.end_turn("gen-1", env=env)
    c.request()
    c.ask()
    assert followup(c.end_turn("gen-2", env=env)) == ""  # the survey asked
    c.line("1. This chat 2. Satisfied True 3. no")
    c.rate("chat", "private")
    assert followup(c.end_turn("gen-3", env=env)) == ""  # the survey answered
    c.line("next task")
    assert followup(c.end_turn("gen-4", env=env)) != ""


def test_a_turn_that_only_names_the_script_is_counted(c):
    env = {"RATEXP_EVERY": "2"}
    c.end_turn("gen-1", env=env)
    c.line("tidy up core/ratexp-cursor.sh")
    assert followup(c.end_turn("gen-2", env=env)) != ""


def test_a_turn_is_counted_once_and_only_when_it_finished(c):
    env = {"RATEXP_EVERY": "2"}
    c.end_turn("gen-1", env=env)
    assert followup(c.end_turn("gen-1", env=env)) == "", "the same turn again"
    assert followup(c.end_turn("gen-2", status="aborted", env=env)) == ""
    assert followup(c.end_turn("gen-3", env=env)) != ""


def test_the_followup_leads_to_the_same_survey(c):
    env = {"RATEXP_EVERY": "1"}
    c.line("THE-WORK", role="assistant")
    c.line(followup(c.end_turn("gen-1", env=env)))  # Cursor sends it as the next prompt
    out, rc = c.ask()
    assert rc == 0 and out.startswith("RateXp survey for this chat.")
    c.rate("chat")
    assert c.calls()[0]["fields"]["eval_name"] == DEFAULT_EVAL
    assert b"THE-WORK" in c.calls()[1]["body"]


# --------------------------------------------------------------------------
# The report
# --------------------------------------------------------------------------


def test_a_private_rating_sends_feedback_and_nothing_else(c):
    c.request()
    c.ask()
    out, rc = c.rate("chat", "private")
    assert rc == 0
    assert c.endpoints() == ["feedback"]
    assert SENTINEL.encode() not in c.curl_log_bytes()
    assert "kept private" in out


@pytest.mark.parametrize(
    ("model", "label"),
    [
        ("gpt-5.1-codex", "cursor gpt-5.1-codex"),
        ("claude-4.6-opus-high-thinking", "cursor claude-4.6-opus-high-thinking"),
        ("default", "cursor auto"),
        # A space would split the label into a different model.
        ("gpt 5", "cursor"),
        (7, "cursor"),
    ],
)
def test_the_model_the_stop_hook_saw_goes_into_the_agent_label(c, model, label):
    """Cursor's transcript names no model; its stop event does."""
    c.line("WORK", role="assistant")
    c.end_turn("gen-1", model=model)
    c.request()
    c.ask()
    c.rate("chat")
    assert [call["fields"]["agent"] for call in c.calls()] == [label, label]


def test_the_agent_label_is_plain_cursor_when_no_hook_fired(c):
    c.request()
    c.ask()
    c.rate("chat", "private")
    assert c.calls()[0]["fields"]["agent"] == "cursor"


@pytest.mark.parametrize(
    "args",
    [
        ("sideways", "private"),
        ("chat", "maybe"),
        ("chat",),
        ("", ""),
        # The consent word is never optional: an agent that drops it must fail
        # loudly rather than have the chat quietly uploaded or quietly kept.
        ("chat", "", DEFAULT_EVAL, "good"),
        ("share", "chat"),
        # The comment is never optional either, so an eval's name is never read as one.
        ("chat", "share"),
        # Each rated eval is two words.
        ("chat", "share", "", DEFAULT_EVAL),
        ("chat", "share", "", DEFAULT_EVAL, "sideways"),
    ],
)
def test_an_answer_the_agent_garbled_is_refused(c, args):
    c.request()
    c.ask()
    _, rc = c.report(*args)
    assert rc == 1
    assert c.calls() == [], "nothing may be sent on a malformed answer"


def test_answering_twice_submits_exactly_once(c):
    c.request()
    c.ask()
    assert c.rate("chat")[1] == 0
    out, rc = c.rate("chat")
    assert rc == 1
    assert "no survey is waiting" in out
    assert c.endpoints() == ["feedback", "transcript"], "exactly one submission"


def test_a_stale_survey_is_not_answerable(c):
    c.request()
    c.ask()
    c.age_pending(901)  # past the fifteen-minute window
    assert c.rate("chat")[1] == 1
    assert c.calls() == []


def test_a_swapped_transcript_file_is_not_uploaded(c):
    c.request()
    c.ask()
    replacement = c.transcript.with_suffix(".new")
    replacement.write_bytes(c.transcript.read_bytes() + b"x" * 64)
    os.replace(replacement, c.transcript)
    out, _ = c.rate("chat")
    assert c.endpoints() == ["feedback"]
    assert "Transcript could not be sent" in out


def test_macos_stat_uploads_the_transcript(c):
    """macOS stat gives /dev/fd/N a device of its own; the same file must still match."""
    c.use_macos_stat()
    c.request()
    c.ask()
    out, _ = c.rate("chat")
    assert c.endpoints() == ["feedback", "transcript"]
    assert "transcript accepted" in out


def test_macos_stat_still_refuses_a_swapped_transcript(c):
    c.use_macos_stat()
    c.request()
    c.ask()
    replacement = c.transcript.with_suffix(".new")
    replacement.write_bytes(c.transcript.read_bytes() + b"x" * 64)
    os.replace(replacement, c.transcript)
    out, _ = c.rate("chat")
    assert c.endpoints() == ["feedback"]
    assert "Transcript could not be sent" in out


# --------------------------------------------------------------------------
# Bad input
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "payload",
    [b"", b"not json", b"{", b"[]", b'{"hook_event_name":"stop"}', b"null"],
)
def test_malformed_stdin_gets_an_empty_answer(c, payload):
    out, _, _ = c.run_hook(payload)
    assert json.loads(out) == {}
    assert c.calls() == []
    assert not (c.home / ".cursor" / "hooks.json").exists()


def test_an_unknown_mode_is_refused(c):
    assert c.run("rate-everything")[1] == 1


# --------------------------------------------------------------------------
# The code both hooks carry
# --------------------------------------------------------------------------

# Each hook is one standalone download, so both carry the same JSON reader and
# helpers. A fix to one copy has to reach the other.
SHARED = (
    "fail",
    "white",
    "hex4",
    "utf8",
    "string",
    "value",
    "get",
    "quote",
    "good_url",
    "post",
    "file_info",
    "open_file_info",
    "new_request_id",
    "upload_slice",
    "send_ratings",
    "sent_line",
    "find_eval",
    "fetch_hook_settings",
    "load_hook_settings",
    "manifest_version",
    "is_newer",
)


def shell_function(path, name):
    """A shell function's source, from its opening line to its closing brace."""
    lines = path.read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(f"{name}() {{"))
    end = start if lines[start].endswith("}") else lines.index("}", start)
    return lines[start : end + 1]


@pytest.mark.parametrize("name", SHARED)
def test_the_code_both_hooks_share_is_the_same_in_each(name):
    claude = shell_function(CLAUDE_PLUGIN / "ratexp-claude.sh", name)
    cursor = shell_function(CURSOR_PLUGIN / "ratexp-cursor.sh", name)
    assert claude == cursor, f"{name}() differs between the two hooks; change both copies"
