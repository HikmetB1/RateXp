"""Black-box tests for core/ratexp-cursor.sh.

Installed once, in ~/.cursor, by the person using Cursor. It rates the whole chat
every Nth turn on its own (through the stop hook) and on /ratexp, and any skill's
most recent run on /ratexp <skill>. Rating needs no hook: `ask` finds the chat's
transcript where Cursor's editor and CLI both keep it, the agent asks the user,
and `report` sends the answer. Consent is a required word, never a default.

The sandbox, fake curl and helpers come from test_hook.py.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time

import pytest
from test_hook import CORE, EARLIER, LOCAL_URL, SENTINEL, Hook

SKILL = "poem-creator"


class CursorHook(Hook):
    """The script in ~/.cursor, one skill, and one chat transcript."""

    script_name = "ratexp-cursor.sh"

    def __init__(self, tmp_path):
        super().__init__(tmp_path)
        # Finding a skill's newest run means finding a line in a long file.
        os.symlink(shutil.which("grep"), self.bin / "grep")
        text = self.script.read_text(encoding="utf-8")
        self.skill = SKILL
        self.agent_dir = self.home / ".cursor"
        self.skills = self.agent_dir / "skills"
        self.add_skill(SKILL)
        self.script = self.agent_dir / "ratexp-cursor.sh"
        self.script.write_text(text, encoding="utf-8")
        self.script.chmod(0o755)
        # Where Cursor's editor and CLI both keep a chat's transcript.
        chat = self.home / ".cursor" / "projects" / "ws" / "agent-transcripts" / self.session
        chat.mkdir(parents=True)
        self.transcript = chat / f"{self.session}.jsonl"
        self.line(EARLIER)

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

    def request(self, text="/ratexp"):
        """The user's /ratexp message, with the command body Cursor sends along."""
        self.line(f"# RateXp survey\n{text}")

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

    def ask(self, *target, **kw):
        return self.run("ask", *target, **kw)

    def report(self, *args, **kw):
        return self.run("report", *args, **kw)

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
# /ratexp: the whole chat
# --------------------------------------------------------------------------


def test_ratexp_rates_the_whole_chat(c):
    c.use(work="SKILL-WORK")
    c.line("ORDINARY-WORK", role="assistant")
    c.request()
    out, rc = c.ask()
    assert rc == 0
    assert '"Rate this session:"' in out
    assert f"to {LOCAL_URL}?" in out, "consent names the destination"
    assert f'bash "{c.script}" report' in out, "the agent is told exactly what to run"

    out, rc = c.report("good", "share")
    assert rc == 0
    assert c.endpoints() == ["feedback", "transcript"]
    fields = c.calls()[0]["fields"]
    assert fields["agent"] == "cursor"
    assert fields["session_id"] == c.session
    assert fields["score"] == "1"
    assert "skill_name" not in fields, "a session rating names no skill"
    body = c.calls()[1]["body"]
    assert EARLIER.encode() in body, "the whole chat, from byte zero"
    assert b"SKILL-WORK" in body and b"ORDINARY-WORK" in body
    assert "transcript accepted" in out


def test_the_comment_is_handed_over_in_single_quotes(c):
    """Inside double quotes, `backticks` or $(...) the user typed would run as commands."""
    c.request()
    out, _ = c.ask()
    assert "<share|private> '<comment>'" in out


def test_the_survey_itself_is_not_uploaded(c):
    """What is rated ends where the user asked; their answer is not part of it."""
    c.request()
    c.ask()
    c.line("SURVEY-ANSWER")
    c.report("good", "share")
    assert b"SURVEY-ANSWER" not in c.calls()[1]["body"]


def test_nothing_is_asked_without_a_ratexp_request(c):
    """The chat is found by its /ratexp request; without one there is nothing to rate."""
    out, rc = c.ask()
    assert rc == 1
    assert "could not find this chat" in out


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
    other_chat(c, "# RateXp survey\n/ratexp", "now tidy up .cursor/ratexp-cursor.sh")
    c.ask()
    c.report("good", "private")
    assert c.calls()[0]["fields"]["session_id"] == c.session


def test_the_chat_cursor_names_is_the_one_rated(c):
    """Cursor tells the agent's commands which chat they belong to; no guessing then."""
    c.request()
    other_chat(c, "# RateXp survey\n/ratexp")  # asking too, and newer
    env = {"CURSOR_CONVERSATION_ID": c.session, "AGENT_TRANSCRIPTS": c.transcript.parent.parent}
    c.ask(env=env)
    c.report("good", "private")
    assert c.calls()[0]["fields"]["session_id"] == c.session


def test_an_answer_rates_the_chat_it_was_given_in(c):
    """Two chats asked at once. The answer given in the first never sends the
    second, even though the second's survey is the newer one."""
    transcripts = c.transcript.parent.parent
    other_chat(c, "# RateXp survey\n/ratexp")
    c.ask(env={"CURSOR_CONVERSATION_ID": "other-chat", "AGENT_TRANSCRIPTS": transcripts})
    c.request()
    c.ask(env={"CURSOR_CONVERSATION_ID": c.session, "AGENT_TRANSCRIPTS": transcripts})
    c.report("good", "private", env={"CURSOR_CONVERSATION_ID": "other-chat"})
    assert c.calls()[0]["fields"]["session_id"] == "other-chat"


# --------------------------------------------------------------------------
# /ratexp <skill>: that skill's newest run
# --------------------------------------------------------------------------


def test_a_skill_is_rated_on_its_newest_run_only(c):
    c.use(work="RUN-1")
    c.line("BETWEEN-RUNS", role="assistant")
    c.use(work="RUN-2")
    c.request(f"/ratexp {SKILL}")
    out, rc = c.ask(SKILL)
    assert rc == 0
    assert f'"Rate {SKILL}:"' in out
    assert f"Upload this run of {SKILL}" in out

    c.report("bad", "share", "too short")
    fields = c.calls()[0]["fields"]
    assert fields["skill_name"] == SKILL
    assert fields["score"] == "2"
    assert fields["comment"] == "too short"
    body = c.calls()[1]["body"]
    assert b"RUN-2" in body
    for other in (b"RUN-1", b"BETWEEN-RUNS", EARLIER.encode()):
        assert other not in body, f"an earlier part of the chat leaked: {other!r}"


def test_a_skill_rating_leaves_out_what_came_after_the_run(c):
    """The run ends when the conversation moves on, not at /ratexp. Its question
    and the user's answer belong to it; the next request does not."""
    c.run_start = c.transcript.stat().st_size
    c.line(f"Skill Name: {SKILL}\nPath: {c.skills / SKILL / 'SKILL.md'}")
    c.line("Which mood would you like?", role="assistant")
    c.line("SAD-PLEASE")
    c.line("THE-POEM", role="assistant")
    c.line("UNRELATED-REQUEST")
    c.line("UNRELATED-WORK", role="assistant")
    c.request(f"/ratexp {SKILL}")
    c.ask(SKILL)
    c.report("good", "share")
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
    c.request(f"/ratexp {SKILL}")
    assert c.ask(SKILL)[1] == 0
    c.report("good", "share")
    body = c.calls()[1]["body"]
    assert b"PICKED-RUN" in body
    assert EARLIER.encode() not in body


def test_a_skill_that_never_ran_cannot_be_rated(c):
    c.request(f"/ratexp {SKILL}")
    out, rc = c.ask(SKILL)
    assert rc == 1
    assert f"no run of {SKILL}" in out
    assert c.report("good", "share")[1] == 1, "nothing was handed out to answer"


@pytest.mark.parametrize("name", ["../etc", "a b", "-rf", "x;y"])
def test_a_skill_name_that_is_not_a_name_is_refused(c, name):
    c.request()
    assert c.ask(name)[1] == 1


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
    assert f'bash "{c.script}" ask`' in text, "the same survey /ratexp starts, for the whole chat"


def test_the_survey_turn_is_not_counted(c):
    env = {"RATEXP_EVERY": "2"}
    c.end_turn("gen-1", env=env)
    c.line("RateXp survey for this whole chat: run ...")  # the followup Cursor sent
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
    c.line("good, keep it private")
    c.report("good", "private")
    assert followup(c.end_turn("gen-3", env=env)) == ""  # the survey answered
    c.line("next task")
    assert followup(c.end_turn("gen-4", env=env)) != ""


def test_a_turn_that_only_names_the_script_is_counted(c):
    env = {"RATEXP_EVERY": "2"}
    c.end_turn("gen-1", env=env)
    c.line("tidy up .cursor/ratexp-cursor.sh")
    assert followup(c.end_turn("gen-2", env=env)) != ""


def test_a_turn_is_counted_once_and_only_when_it_finished(c):
    env = {"RATEXP_EVERY": "2"}
    c.end_turn("gen-1", env=env)
    assert followup(c.end_turn("gen-1", env=env)) == "", "the same turn again"
    assert followup(c.end_turn("gen-2", status="aborted", env=env)) == ""
    assert followup(c.end_turn("gen-3", env=env)) != ""


def test_the_followup_leads_to_a_rating_of_the_whole_chat(c):
    env = {"RATEXP_EVERY": "1"}
    c.line("THE-WORK", role="assistant")
    c.line(followup(c.end_turn("gen-1", env=env)))  # Cursor sends it as the next prompt
    out, rc = c.ask()
    assert rc == 0 and '"Rate this session:"' in out
    c.report("good", "share")
    assert b"THE-WORK" in c.calls()[1]["body"]


# --------------------------------------------------------------------------
# The /ratexp command: the script writes it itself
# --------------------------------------------------------------------------


def test_session_start_writes_the_ratexp_command(c):
    assert json.loads(c.session_start()) == {}
    commands = c.agent_dir / "commands"
    assert [p.name for p in commands.iterdir()] == ["ratexp.md"], "one file, no per-skill entries"
    text = (commands / "ratexp.md").read_text(encoding="utf-8")
    assert f'bash "{c.script}" ask <that-name>' in text
    assert f'bash "{c.script}" ask`' in text
    # Cursor reads /ratexp:<skill> as /ratexp followed by the skill's name.
    assert "`/ratexp:<name>`" in text
    assert "RateXp survey" in text, "the chat is found by this"


def test_an_existing_command_is_left_alone(c):
    commands = c.agent_dir / "commands"
    commands.mkdir()
    (commands / "ratexp.md").write_text("MINE\n", encoding="utf-8")
    c.session_start()
    assert (commands / "ratexp.md").read_text(encoding="utf-8") == "MINE\n"


def test_ask_writes_the_command_too(c):
    """The CLI may never fire sessionStart, but its stop hook's followup runs ask."""
    c.request()
    c.ask()
    assert (c.agent_dir / "commands" / "ratexp.md").exists()


def test_a_path_that_would_break_the_command_writes_none(tmp_path):
    """The path lands inside a shell command the agent runs, so only plain
    characters are written into it; anything else and the file is left out."""
    c = CursorHook(tmp_path)
    odd = c.home / "odd$dir"
    c.agent_dir.rename(odd)
    c.agent_dir, c.script = odd, odd / c.script.name
    c.session_start()
    assert not (odd / "commands").exists()


# --------------------------------------------------------------------------
# The report
# --------------------------------------------------------------------------


def test_a_private_rating_sends_feedback_and_nothing_else(c):
    c.request()
    c.ask()
    out, rc = c.report("good", "private")
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
    c.report("good", "share")
    assert [call["fields"]["agent"] for call in c.calls()] == [label, label]


def test_the_agent_label_is_plain_cursor_when_no_hook_fired(c):
    c.request()
    c.ask()
    c.report("good", "private")
    assert c.calls()[0]["fields"]["agent"] == "cursor"


@pytest.mark.parametrize(
    "args",
    [
        ("sideways", "private"),
        ("good", "maybe"),
        ("good",),
        ("", ""),
        # The consent word is never optional: an agent that drops it must fail
        # loudly rather than have the chat quietly uploaded or quietly kept.
        ("share", "good"),
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
    assert c.report("good", "share")[1] == 0
    out, rc = c.report("good", "share")
    assert rc == 1
    assert "no survey is waiting" in out
    assert c.endpoints() == ["feedback", "transcript"], "exactly one submission"


def test_a_stale_survey_is_not_answerable(c):
    c.request()
    c.ask()
    c.age_pending(901)  # past the fifteen-minute window
    assert c.report("good", "share")[1] == 1
    assert c.calls() == []


def test_a_swapped_transcript_file_is_not_uploaded(c):
    c.request()
    c.ask()
    replacement = c.transcript.with_suffix(".new")
    replacement.write_bytes(c.transcript.read_bytes() + b"x" * 64)
    os.replace(replacement, c.transcript)
    out, _ = c.report("good", "share")
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
    assert not (c.agent_dir / "commands").exists()


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
)


def shell_function(path, name):
    """A shell function's source, from its opening line to its closing brace."""
    lines = path.read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(f"{name}() {{"))
    end = start if lines[start].endswith("}") else lines.index("}", start)
    return lines[start : end + 1]


@pytest.mark.parametrize("name", SHARED)
def test_the_code_both_hooks_share_is_the_same_in_each(name):
    claude = shell_function(CORE / "ratexp-claude.sh", name)
    cursor = shell_function(CORE / "ratexp-cursor.sh", name)
    assert claude == cursor, f"{name}() differs between the two hooks; change both copies"
