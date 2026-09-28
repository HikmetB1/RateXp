"""Black-box tests for core/ratexp-claude.sh rating a skill, and the harness
every hook test shares.

The Claude Code hook is installed once, in ~/.claude, by the person using Claude
Code. It rates any skill's most recent run when they type /ratexp <skill>; the
whole-session survey is tested in test_hook_session.py.

The hook has to run on a bare machine: Bash 3.2+, curl, and a short list of
standard utilities - no Python, no jq, no node. Nothing here imports or reads
the script's logic. Every test spawns `/bin/bash <copy of the hook>` in a
subprocess whose PATH contains ONLY symlinks to the utilities the script's own
preflight loop checks for (line: `for token in curl cksum mkdir rmdir mv date
od stat head tail sort`), plus a fake `curl` that records each call and prints a
status the test chooses. If the script ever grew a Python/jq/node dependency,
these tests would stop producing output instead of passing.

Every run gets its own XDG_STATE_HOME and an explicit RATEXP_URL, so runs
never share state and never touch the network.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.name != "posix" or not Path("/bin/bash").exists(),
    reason="the hook is a POSIX shell script and needs /bin/bash",
)

# Taken verbatim from the script's own preflight loop. `curl` is replaced by a
# fake; the rest are symlinked to the real system binaries. /dev/urandom and
# /dev/fd/3 are devices, not binaries, so they need no entry here.
ALLOWED_UTILS = ("cksum", "mkdir", "rmdir", "mv", "date", "od", "stat", "head", "tail", "sort")

# Tools the script must NOT need. The sandbox deliberately hides them.
FORBIDDEN_UTILS = ("python", "python3", "jq", "node", "perl", "awk", "sed", "grep", "cat")

CORE = Path(__file__).resolve().parents[1]
PLACEHOLDER = "'__RATEXP_URL__'"
EVERY_PLACEHOLDER = "'__RATEXP_EVERY__'"
# What the tests bake in where a real copy would carry config.yaml's value.
BAKED_EVERY = 5
# The default every test runs with: far out of reach, so the whole-session survey
# never interrupts a test that is not about it.
NEVER = "32768"

# Loopback is the only http:// origin the script accepts, and nothing listens
# on this port - the fake curl means no socket is ever opened anyway.
LOCAL_URL = "http://127.0.0.1:9999"

# The skill being run and rated.
DEFAULT_SKILL = "poem-creator"

# Private text planted inside the run being rated. It must never show up in the
# hook's stdout/stderr (checked on every single run) and must only reach the
# curl log when the user explicitly consented.
SENTINEL = "RATEXP-PRIVATE-SENTINEL-7f3a9c2e"

# Text written before the run being rated - an earlier use of the skill, or plain
# chat. A consented upload carries one run, so this must never be part of it.
EARLIER = "RATEXP-EARLIER-TURN-b41d8e60"

TOOL_ID = "toolu_01ratexp"

# The exact comma-joined answer Claude returns for "Good" + the consent label.
CONSENT = "Good, Yes, store trajectory"

# The NUL-separated fields of the stored picker, in the order the hook writes
# them. Tests rewrite them to play the part of a local process with write
# access to the state directory.
PENDING_FIELDS = (
    "request",
    "born",
    "picker",
    "transcript",
    "size",
    "start",
    "identity",
    "url",
    "target",
)

# Stand-in for curl: records argv (NUL-separated, so newlines inside a comment
# survive) plus the piped body, then prints the status the test asked for.
FAKE_CURL = """#!/bin/bash
dir=${RATEXP_CURL_LOG:?}
id=$$-$RANDOM$RANDOM
wants_body=0
for arg in "$@"; do [[ $arg == 'transcript=<-' ]] && wants_body=1; done
for arg in "$@"; do printf '%s\\0' "$arg"; done > "$dir/argv-$id"
if (( wants_body )); then
    IFS= read -r -d '' body
    printf '%s' "$body" > "$dir/body-$id"
fi
printf '%s' "${RATEXP_CURL_STATUS:-201}"
"""


def reorder(obj):
    """Re-serialise with object keys in the opposite order (values untouched)."""
    if isinstance(obj, dict):
        return {k: reorder(v) for k, v in reversed(list(obj.items()))}
    if isinstance(obj, list):
        return [reorder(v) for v in obj]
    return obj


class Hook:
    """Runs the hook script, as core serves it, in a sandbox and reads back what curl saw."""

    # Which script this harness runs; a subclass testing another one overrides it.
    script_name = "ratexp-claude.sh"

    def __init__(self, tmp_path: Path):
        self.tmp = tmp_path
        self.session = "sess-hook-1"
        self.skill = DEFAULT_SKILL

        # The script as core serves it: the URL and the frequency baked in.
        text = (CORE / self.script_name).read_text(encoding="utf-8")
        for name in (PLACEHOLDER, EVERY_PLACEHOLDER):
            assert name in text, f"canonical script lost its {name} placeholder"
        text = text.replace(PLACEHOLDER, f"'{LOCAL_URL}'")
        text = text.replace(EVERY_PLACEHOLDER, f"'{BAKED_EVERY}'")
        # Installed once for every project, in the home folder.
        self.home = tmp_path / "home"
        self.agent_dir = self.home / ".claude"
        self.agent_dir.mkdir(parents=True)
        self.script = self.agent_dir / self.script_name
        self.script.write_text(text, encoding="utf-8")
        self.script.chmod(0o755)

        # PATH holds nothing but the allowed utilities and the fake curl.
        self.bin = tmp_path / "bin"
        self.bin.mkdir()
        for name in ALLOWED_UTILS:
            real = shutil.which(name)
            if real is None:
                pytest.skip(f"{name} is missing; the hook cannot run here")
            os.symlink(real, self.bin / name)
        fake = self.bin / "curl"
        fake.write_text(FAKE_CURL, encoding="utf-8")
        fake.chmod(0o755)

        self.state = tmp_path / "state"
        self.curl_log = tmp_path / "curl-log"
        self.curl_log.mkdir()
        self.cwd = tmp_path / "cwd"
        self.cwd.mkdir()

        self.transcript = tmp_path / "session.jsonl"
        self.transcript.write_text(
            json.dumps({"type": "user", "text": EARLIER}) + "\n", encoding="utf-8"
        )
        # Byte offset where the run being rated starts; arm() keeps it current.
        self.run_start = 0

    # ---------------------------------------------------------------- running

    def env(self, **overrides) -> dict:
        env = {
            "PATH": str(self.bin),
            "HOME": str(self.home),
            "XDG_STATE_HOME": str(self.state),
            "RATEXP_URL": LOCAL_URL,
            "RATEXP_EVERY": NEVER,
            "RATEXP_CURL_LOG": str(self.curl_log),
            "RATEXP_CURL_STATUS": "201",
        }
        # A None override unsets the variable, so a test can check what the copy
        # itself carries rather than what the environment says.
        for key, value in overrides.items():
            if value is None:
                env.pop(key, None)
            else:
                env[key] = str(value)
        return env

    def run_hook(self, event_json, env=None):
        """Feed one hook event to the script. Returns (stdout, stderr, rc)."""
        if not isinstance(event_json, bytes | bytearray):
            event_json = json.dumps(event_json, ensure_ascii=False).encode("utf-8")
        done = subprocess.run(
            ["/bin/bash", str(self.script)],
            input=bytes(event_json),
            capture_output=True,
            env=self.env(**(env or {})),
            cwd=str(self.cwd),
            timeout=60,
        )
        out = done.stdout.decode("utf-8", "replace")
        err = done.stderr.decode("utf-8", "replace")
        # Holds for every test: the hook never echoes transcript contents.
        assert SENTINEL not in out
        assert SENTINEL not in err
        assert done.returncode == 0, f"hook must always exit 0, got {done.returncode}"
        return out, err, done.returncode

    # ----------------------------------------------------------------- events

    def event(self, name, **extra):
        base = {
            "session_id": self.session,
            "transcript_path": str(self.transcript),
            "cwd": str(self.cwd),
            "hook_event_name": name,
        }
        base.update(extra)
        return base

    def append(self, **fields):
        """Add one line to the session transcript, the way the agent does."""
        with self.transcript.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(fields) + "\n")

    def arm(self, env=None):
        """Start one skill run, the way a `/poem-creator` expansion does.

        The hook notes the transcript's length at that moment as where the run
        starts. The expansion fires before this run has written anything, so its
        own turn lands afterwards - that span is what a consented upload sends.
        """
        self.append(type="assistant", text=EARLIER)
        out = self.run_hook(self.event("UserPromptExpansion", command_name=self.skill), env)
        self.run_start = self.transcript.stat().st_size  # the length the hook just noted
        self.append(type="user", text=SENTINEL)
        return out

    def run_slice(self) -> bytes:
        """The part of the transcript belonging to the run now being rated."""
        return self.transcript.read_bytes()[self.run_start :]

    def stop(self, env=None):
        """Run a Stop event; return the picker dict, or None if none was asked for."""
        out, _, _ = self.run_hook(self.event("Stop", stop_hook_active=False), env)
        if not out.strip():
            return None
        doc = json.loads(out)
        assert doc["decision"] == "block"
        # The reason is a one-line instruction, then the picker JSON.
        return json.loads(doc["reason"].split("\n", 1)[1])

    def pre(self, picker, tool_id=TOOL_ID, env=None):
        return self.run_hook(
            self.event(
                "PreToolUse",
                tool_name="AskUserQuestion",
                tool_use_id=tool_id,
                tool_input=picker,
            ),
            env,
        )

    def answer(self, picker, selected, notes=None, tool_id=TOOL_ID, tool_input=None):
        """Build the PostToolUse payload. The question text is the answers key."""
        question = picker["questions"][0]["question"]
        if not isinstance(selected, str):
            selected = ", ".join(selected)
        response = {"answers": {question: selected}}
        if notes is not None:
            response["annotations"] = {question: {"notes": notes}}
        return self.event(
            "PostToolUse",
            tool_name="AskUserQuestion",
            tool_use_id=tool_id,
            tool_input=picker if tool_input is None else tool_input,
            tool_response=response,
        )

    def request(self, target=None, env=None):
        """The user choosing /ratexp:<skill> - this skill unless another is named."""
        name = f"ratexp:{target or self.skill}"
        return self.run_hook(self.event("UserPromptExpansion", command_name=name), env)

    def ask(self, env=None, tool_id=TOOL_ID):
        """arm -> /ratexp -> Stop -> PreToolUse. Returns the picker ready to be answered."""
        self.arm(env)
        self.request(env=env)
        picker = self.stop(env)
        assert picker is not None
        out, _, _ = self.pre(picker, tool_id=tool_id, env=env)
        assert out == "", f"an unmodified picker must be allowed silently: {out!r}"
        return picker

    # ------------------------------------------------------------ curl replay

    def calls(self):
        """Every fake-curl invocation, oldest first.

        Ties on the file timestamp are broken by endpoint, because the script
        always posts the feedback before it streams a transcript.
        """
        rank = {"feedback": 0, "transcript": 1}
        found = []
        for path in self.curl_log.iterdir():
            if not path.name.startswith("argv-"):
                continue
            raw = path.read_bytes().split(b"\0")[:-1]
            args = [a.decode("utf-8", "surrogateescape") for a in raw]
            fields = {}
            for i, arg in enumerate(args):
                if arg in ("--form-string", "--form") and i + 1 < len(args):
                    key, _, value = args[i + 1].partition("=")
                    fields[key] = value
            body = self.curl_log / ("body-" + path.name[len("argv-") :])
            endpoint = args[-1].rsplit("/", 1)[-1]
            found.append(
                {
                    "args": args,
                    "url": args[-1],
                    "endpoint": endpoint,
                    "fields": fields,
                    "body": body.read_bytes() if body.exists() else None,
                    "_order": (path.stat().st_mtime_ns, rank.get(endpoint, 9), path.name),
                }
            )
        found.sort(key=lambda c: c["_order"])
        return found

    def endpoints(self):
        return [c["endpoint"] for c in self.calls()]

    def curl_log_bytes(self) -> bytes:
        return b"".join(p.read_bytes() for p in sorted(self.curl_log.iterdir()))

    # ----------------------------------------------------------- state pokery

    def pending_path(self) -> Path:
        candidates = list(self.state.glob("ratexp/*/runs/*/pending"))
        candidates += list(self.state.glob("ratexp/*/pending"))
        assert candidates, "no pending picker was recorded"
        return max(candidates, key=lambda p: p.stat().st_mtime_ns)

    def age_pending(self, seconds: int):
        """Backdate the stored picker so the 15-minute window can be tested."""
        path = self.pending_path()
        parts = path.read_bytes().split(b"\0")
        parts[1] = str(int(parts[1]) - seconds).encode()
        path.write_bytes(b"\0".join(parts))

    def patch_pending(self, **fields):
        """Rewrite named fields of the stored picker, as a local attacker would."""
        path = self.pending_path()
        parts = path.read_bytes().split(b"\0")
        for name, value in fields.items():
            parts[PENDING_FIELDS.index(name)] = str(value).encode()
        path.write_bytes(b"\0".join(parts))

    def base_dir(self) -> Path:
        """The session's state directory, `<state>/ratexp/<script-hash>-<session>`."""
        dirs = [p for p in (self.state / "ratexp").iterdir() if p.is_dir()]
        assert len(dirs) == 1, f"expected one state directory, got {dirs}"
        return dirs[0]

    def run_dir(self) -> Path:
        """Where the current invocation keeps its picker; the base until one is armed."""
        base = self.base_dir()
        current = base / "current"
        if current.is_file():
            return base / "runs" / current.read_text(encoding="utf-8")
        return base

    def plant_symlink(self, path: Path, name: str) -> Path:
        """Point `path` at a fresh victim file, the way a planted symlink would."""
        victim = self.tmp / f"victim-{name}"
        victim.write_text("KEEP ME\n", encoding="utf-8")
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_file():
            path.unlink()
        path.symlink_to(victim)
        return victim


@pytest.fixture
def hook(tmp_path):
    return Hook(tmp_path)


# --------------------------------------------------------------------------
# The sandbox itself
# --------------------------------------------------------------------------


def test_sandbox_hides_python_jq_and_node(hook):
    """Guard: if PATH leaked, every other test would prove nothing."""
    probe = "\n".join(f"command -v {t} >/dev/null && echo {t}" for t in FORBIDDEN_UTILS)
    done = subprocess.run(
        ["/bin/bash", "-c", probe + "\nexit 0"],
        capture_output=True,
        env=hook.env(),
        text=True,
    )
    assert done.stdout == "", f"sandbox PATH still exposes: {done.stdout.split()}"


def test_full_round_trip_reaches_curl(hook):
    """Baseline: the script talks to the server with only the allowed utilities."""
    picker = hook.ask()
    out, _, _ = hook.run_hook(hook.answer(picker, "Good"))
    assert "feedback accepted" in out
    call = hook.calls()[0]
    assert call["endpoint"] == "feedback"
    assert call["fields"]["skill_name"] == hook.skill
    assert call["fields"]["agent"] == "claude-code"
    assert call["fields"]["session_id"] == hook.session
    assert len(call["fields"]["request_id"]) == 36  # uuid-shaped


# --------------------------------------------------------------------------
# Answer parsing
# --------------------------------------------------------------------------


def test_good_alone_scores_one(hook):
    """ "Good" is the only signal, so it becomes score=1."""
    picker = hook.ask()
    hook.run_hook(hook.answer(picker, "Good"))
    assert hook.calls()[0]["fields"]["score"] == "1"


def test_bad_alone_scores_two(hook):
    picker = hook.ask()
    hook.run_hook(hook.answer(picker, "Bad"))
    assert hook.calls()[0]["fields"]["score"] == "2"


def test_good_and_bad_together_send_no_score(hook):
    """Contradictory ticks cancel out; the typed note still has to survive."""
    picker = hook.ask()
    hook.run_hook(hook.answer(picker, ["Good", "Bad"], notes="torn on this one"))
    fields = hook.calls()[0]["fields"]
    assert "score" not in fields
    assert fields["comment"] == "torn on this one"


def test_nothing_chosen_and_nothing_typed_sends_nothing(hook):
    """An empty survey result must not create a record."""
    picker = hook.ask()
    out, _, _ = hook.run_hook(hook.answer(picker, ""))
    assert out == ""
    assert hook.calls() == []


# --------------------------------------------------------------------------
# Labels that contain commas
# --------------------------------------------------------------------------


def test_a_quoted_consent_label_still_grants_consent(hook):
    """Claude Code quotes a label that holds a comma: `Good, "Yes, store trajectory", great`."""
    picker = hook.ask()
    out, _, _ = hook.run_hook(hook.answer(picker, 'Good, "Yes, store trajectory", great'))
    fields = hook.calls()[0]["fields"]
    assert fields["score"] == "1"
    assert fields["comment"] == "great"
    assert hook.endpoints() == ["feedback", "transcript"]
    assert "transcript accepted" in out


def test_a_quoted_refusal_still_refuses(hook):
    picker = hook.ask()
    hook.run_hook(hook.answer(picker, 'Good, "No, do not store"'))
    assert hook.endpoints() == ["feedback"]
    assert "comment" not in hook.calls()[0]["fields"]


def test_consent_label_is_not_split_on_its_own_comma(hook):
    """The joined answer contains commas inside labels; naive splitting breaks it."""
    picker = hook.ask()
    out, _, _ = hook.run_hook(hook.answer(picker, "Good, Yes, store trajectory"))
    fields = hook.calls()[0]["fields"]
    assert fields["score"] == "1"
    assert "comment" not in fields  # "store trajectory" is not stray free text
    assert hook.endpoints() == ["feedback", "transcript"]
    assert "transcript accepted" in out


def test_no_overrides_yes_when_both_consent_labels_are_ticked(hook):
    """A refusal always wins over a simultaneous agreement."""
    picker = hook.ask()
    out, _, _ = hook.run_hook(hook.answer(picker, "Good, Yes, store trajectory, No, do not store"))
    assert hook.endpoints() == ["feedback"]
    assert "kept private" in out
    assert SENTINEL.encode() not in hook.curl_log_bytes()


# --------------------------------------------------------------------------
# Free text
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "comment",
    [
        pytest.param("héllo — 世界 ✓ naïve", id="unicode"),
        pytest.param('he said "very nice" indeed', id="double-quotes"),
        pytest.param("C:\\path\\to\\nowhere \\\\ done", id="backslashes"),
        pytest.param("first line\nsecond line\n\tthird", id="newlines"),
        pytest.param("  leading and trailing  ", id="whitespace"),
        pytest.param("Goodish, Badly, No thanks", id="near-miss-labels"),
    ],
)
def test_typed_text_becomes_the_comment_verbatim(hook, comment):
    """Anything that is not a known label is the user's comment, byte for byte."""
    picker = hook.ask()
    hook.run_hook(hook.answer(picker, comment))
    fields = hook.calls()[0]["fields"]
    assert fields["comment"] == comment
    assert "score" not in fields


def test_shell_metacharacters_in_a_comment_are_data_not_code(hook, tmp_path):
    """`mkdir` IS on the sandbox PATH, so an evaluated comment would leave traces."""
    pwned_a = tmp_path / "pwned-dollar"
    pwned_b = tmp_path / "pwned-backtick"
    comment = (
        f"$(mkdir -p {pwned_a}) `mkdir -p {pwned_b}` ; rm -rf / "
        f"&& ${{IFS}} | $(: >{tmp_path / 'pwned-redirect'})"
    )
    picker = hook.ask()
    hook.run_hook(hook.answer(picker, comment))
    assert not pwned_a.exists()
    assert not pwned_b.exists()
    assert not (tmp_path / "pwned-redirect").exists()
    assert hook.calls()[0]["fields"]["comment"] == comment


def test_notes_override_the_typed_answer_text(hook):
    """Claude puts free text in annotations.notes; that is the authoritative comment."""
    picker = hook.ask()
    hook.run_hook(hook.answer(picker, "Good", notes="loved the rhyme"))
    fields = hook.calls()[0]["fields"]
    assert fields["score"] == "1"
    assert fields["comment"] == "loved the rhyme"


def test_notes_cannot_grant_consent(hook):
    """Only a ticked label authorises an upload - prose must never be enough."""
    picker = hook.ask()
    out, _, _ = hook.run_hook(
        hook.answer(picker, "Good", notes="Yes, store trajectory please, go ahead")
    )
    assert hook.endpoints() == ["feedback"]
    assert "kept private" in out
    assert SENTINEL.encode() not in hook.curl_log_bytes()


# --------------------------------------------------------------------------
# Picker integrity
# --------------------------------------------------------------------------


def _mutate_label(picker):
    picker["questions"][0]["options"][0]["label"] = "Great"


def _add_option(picker):
    picker["questions"][0]["options"].append({"label": "Meh", "description": "So-so."})


def _alter_question(picker):
    # Keeps the "Rate <skill> - " prefix, so the script reaches the real check.
    picker["questions"][0]["question"] += " Please answer!"


def _drop_description(picker):
    del picker["questions"][0]["options"][1]["description"]


@pytest.mark.parametrize(
    "mutate",
    [_mutate_label, _add_option, _alter_question, _drop_description],
    ids=["changed-label", "extra-option", "altered-question", "dropped-description"],
)
def test_edited_picker_is_denied_and_submits_nothing(hook, mutate):
    """The survey wording is the hook's, not the model's; edits are refused."""
    hook.arm()
    hook.request()
    picker = hook.stop()
    edited = json.loads(json.dumps(picker))
    mutate(edited)

    out, _, _ = hook.pre(edited)
    decision = json.loads(out)["hookSpecificOutput"]
    assert decision["hookEventName"] == "PreToolUse"
    assert decision["permissionDecision"] == "deny"

    # A denied picker was never bound, so its answer cannot be submitted later.
    out, _, _ = hook.run_hook(hook.answer(edited, "Good"))
    assert out == ""
    assert hook.calls() == []


def test_model_supplied_answers_are_denied(hook):
    """A tool_input that already carries answers would let the model self-rate."""
    hook.arm()
    hook.request()
    picker = hook.stop()
    forged = json.loads(json.dumps(picker))
    question = forged["questions"][0]["question"]
    forged["answers"] = {question: "Good, Yes, store trajectory"}
    forged["annotations"] = {question: {"notes": "great"}}

    out, _, _ = hook.pre(forged)
    assert json.loads(out)["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert hook.calls() == []


def test_key_order_does_not_matter(hook):
    """JSON objects are unordered; re-serialising must not look like tampering."""
    hook.arm()
    hook.request()
    picker = hook.stop()
    shuffled = reorder(picker)
    assert json.dumps(shuffled) != json.dumps(picker)  # genuinely reordered

    out, _, _ = hook.pre(shuffled)
    assert out == "", "a reordered but identical picker must be accepted"
    hook.run_hook(hook.answer(shuffled, "Good"))
    assert hook.calls()[0]["fields"]["score"] == "1"


def test_another_skills_picker_passes_through_untouched(hook):
    """The hook owns one header/question; every other survey is none of its business."""
    picker = hook.ask()
    foreign = {
        "questions": [
            {
                "question": "Which mood?",
                "header": "Poem",
                "multiSelect": False,
                "options": [{"label": "Calm", "description": "Gentle."}],
            }
        ]
    }
    out, _, _ = hook.pre(foreign, tool_id="toolu_other")
    assert out == "", "no output and, crucially, no denial"

    out, _, _ = hook.run_hook(
        hook.event(
            "PostToolUse",
            tool_name="AskUserQuestion",
            tool_use_id="toolu_other",
            tool_input=foreign,
            tool_response={"answers": {"Which mood?": "Calm"}},
        )
    )
    assert out == ""
    assert hook.calls() == []

    # The RateXp picker is still pending and still works.
    hook.run_hook(hook.answer(picker, "Good"))
    assert hook.endpoints() == ["feedback"]


# --------------------------------------------------------------------------
# Asking only on /ratexp
# --------------------------------------------------------------------------


def test_a_run_is_never_rated_without_ratexp(hook):
    """Using the skill, however often, never asks on its own."""
    for _ in range(3):
        hook.arm()
        assert hook.stop() is None
    assert hook.calls() == []


def test_ratexp_colon_skill_asks_about_the_newest_run(hook):
    hook.arm()
    hook.request()
    picker = hook.stop()
    assert picker is not None
    assert picker["questions"][0]["question"].startswith(f"Rate {hook.skill} — ")
    assert picker["questions"][0]["header"] == "RateXp"


def test_ratexp_with_the_skill_name_typed_after_it_also_asks(hook):
    """`/ratexp poem-creator`: Claude Code passes the name as the command's arguments."""
    hook.arm()
    hook.run_hook(
        hook.event(
            "UserPromptExpansion",
            command_name="ratexp",
            command_args=hook.skill,
        )
    )
    assert hook.stop() is not None


def test_skill_tool_call_also_starts_a_run(hook):
    """Skills can start as a Skill tool call instead of a slash-command expansion."""
    hook.run_hook(
        hook.event(
            "PreToolUse",
            tool_name="Skill",
            tool_use_id="toolu_skill_1",
            tool_input={"skill": hook.skill},
        )
    )
    hook.request()
    assert hook.stop() is not None


# --------------------------------------------------------------------------
# Replay, concurrency and late answers
# --------------------------------------------------------------------------


def test_replayed_answer_submits_exactly_once(hook):
    """Hook delivery is at-least-once; the second copy must be a no-op."""
    picker = hook.ask()
    payload = hook.answer(picker, "Good, Yes, store trajectory")
    hook.run_hook(payload)
    out, _, _ = hook.run_hook(payload)
    assert out == ""
    assert hook.endpoints() == ["feedback", "transcript"]


def test_concurrent_answers_submit_exactly_once(hook):
    """Two hook processes racing on one tool_use_id must not double-report."""
    picker = hook.ask()
    payload = hook.answer(picker, "Good")
    barrier = threading.Barrier(2)
    results = []

    def fire():
        barrier.wait()
        results.append(hook.run_hook(payload)[0])

    threads = [threading.Thread(target=fire) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert hook.endpoints() == ["feedback"]
    assert sum(1 for out in results if out.strip()) == 1


def test_late_answer_binds_to_its_original_invocation(hook):
    """A second run may start before the first answer lands; IDs must not cross."""
    first = hook.ask()
    first_request = None

    # A second invocation arms and asks its own question in the same session.
    hook.arm()
    hook.request()
    second = hook.stop()
    assert second is not None
    hook.pre(second, tool_id="toolu_02")

    # Now the slow answer to the FIRST picker arrives.
    hook.run_hook(hook.answer(first, "Good"))
    calls = hook.calls()
    assert len(calls) == 1
    first_request = calls[0]["fields"]["request_id"]

    # Answering the second picker produces a different request id, proving the
    # late answer was consumed by run #1 and not by the newer run.
    hook.run_hook(hook.answer(second, "Bad", tool_id="toolu_02"))
    calls = hook.calls()
    assert len(calls) == 2
    assert calls[1]["fields"]["request_id"] != first_request
    assert calls[0]["fields"]["score"] == "1"
    assert calls[1]["fields"]["score"] == "2"


# --------------------------------------------------------------------------
# Malformed input and bad configuration
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param(b"{not json", id="truncated"),
        pytest.param(b"", id="empty"),
        pytest.param(b"[]", id="not-an-object"),
        pytest.param(b'{"a":1}{"b":2}', id="trailing-garbage"),
        pytest.param(
            b'{"hook_event_name":"Stop","session_id":"x","session_id":"y"}', id="duplicate-keys"
        ),
        pytest.param(b'{"hook_event_name":"Stop","session_id":"bad/session"}', id="bad-session-id"),
    ],
)
def test_malformed_stdin_is_inert(hook, payload):
    """Anything the strict reader dislikes must do nothing at all, quietly."""
    hook.ask()  # a picker is pending, so a sloppy parser would have something to do
    out, err, rc = hook.run_hook(payload)
    assert (out, err, rc) == ("", "", 0)
    assert hook.calls() == []


def test_oversized_stdin_is_inert(hook):
    """The reader caps input at 128 KiB so a huge event cannot be parsed at all."""
    hook.arm()
    hook.request()
    event = hook.event("Stop", stop_hook_active=False, padding="x" * 200_000)
    raw = json.dumps(event).encode()
    assert len(raw) > 131_072
    out, err, rc = hook.run_hook(raw)
    assert (out, err, rc) == ("", "", 0)


def foreign_picker(hook, total: int) -> bytes:
    """Another skill's AskUserQuestion call, padded to exactly `total` bytes."""
    question = {
        "question": "Which mood? ",
        "header": "Poem",
        "multiSelect": False,
        "options": [{"label": "Calm", "description": "Gentle."}],
    }
    event = hook.event(
        "PreToolUse",
        tool_name="AskUserQuestion",
        tool_use_id="toolu_other",
        tool_input={"questions": [question]},
    )
    question["question"] += "y" * (total - len(json.dumps(event).encode()))
    raw = json.dumps(event).encode()
    assert len(raw) == total
    return raw


def test_huge_foreign_picker_is_dropped_without_stalling_the_turn(hook):
    """PreToolUse fires for every AskUserQuestion, including ones far too big to parse.

    The exact reader walks a payload one character at a time, so a picker this
    size used to hold the user's turn for over half a minute. It has to be
    recognised as someone else's and dropped before the reader ever starts -
    silently, because denying another skill's tool call is not this hook's job.
    """
    picker = hook.ask()  # real work is pending, so a sloppy filter would do it
    raw = foreign_picker(hook, 131_000)  # just under the reader's 128 KiB cap
    start = time.monotonic()
    out, err, rc = hook.run_hook(raw)
    elapsed = time.monotonic() - start
    assert (out, err, rc) == ("", "", 0), "neither a denial nor an answer"
    assert elapsed < 1.0, f"took {elapsed:.1f}s; the payload reached the reader"
    assert hook.calls() == []

    # The pending RateXp picker was left alone and still answers normally.
    hook.run_hook(hook.answer(picker, "Good"))
    assert hook.endpoints() == ["feedback"]


def test_a_long_assistant_message_does_not_stall_the_stop_hook(hook):
    """Stop carries the turn's last assistant message, and it can be very long.

    Unlike a foreign picker this one cannot be filtered out - the Stop hook has to
    do its work - so the reader itself has to stay quick as the payload grows.
    """
    hook.arm()
    hook.request()
    event = hook.event(
        "Stop",
        stop_hook_active=False,
        last_assistant_message="A" * 120_000,  # a turn that dumped a big file
    )
    start = time.monotonic()
    out, err, rc = hook.run_hook(event)
    elapsed = time.monotonic() - start
    assert rc == 0 and err == ""
    assert json.loads(out)["decision"] == "block"  # the survey still came through
    assert elapsed < 5.0, f"took {elapsed:.1f}s reading one long message"


def test_a_long_typed_comment_is_still_submitted(hook):
    """The size ceiling on foreign tool calls must not clip a real, wordy answer."""
    picker = hook.ask()
    comment = "why I liked it: " + "x" * 9_000
    payload = hook.answer(picker, "Good", notes=comment)
    assert len(json.dumps(payload).encode()) > 8192, "not past the ceiling; test proves nothing"
    hook.run_hook(payload)
    assert hook.calls()[0]["fields"]["comment"] == comment


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc",
        "http://evil.example.com",
        "ftp://x",
        "http://localhost.evil.com",
        "https://ok.example.com/x?token=1",
        "http://127.0.0.1:9999 ; rm -rf /",
    ],
)
def test_rejected_url_makes_the_hook_inert(hook, url):
    """A destination outside https:// or loopback http:// must never be contacted."""
    picker = hook.ask()  # set up a real, answerable picker first
    out, _, _ = hook.run_hook(hook.answer(picker, "Good"), env={"RATEXP_URL": url})
    assert out == ""
    assert hook.calls() == [], "no curl invocation at all"


def test_loopback_http_url_is_allowed(hook):
    """The local dashboard is served over plain http on 127.0.0.1; that must work."""
    picker = hook.ask()
    hook.run_hook(hook.answer(picker, "Good"))
    assert hook.calls()[0]["url"] == f"{LOCAL_URL}/feedback"


def test_destination_is_pinned_when_the_picker_is_shown(hook):
    """The consent text names one server; a later RATEXP_URL must not redirect it."""
    picker = hook.ask()
    assert LOCAL_URL in picker["questions"][0]["options"][2]["description"]
    hook.run_hook(hook.answer(picker, CONSENT), env={"RATEXP_URL": "https://elsewhere.example.com"})
    assert [c["url"] for c in hook.calls()] == [
        f"{LOCAL_URL}/feedback",
        f"{LOCAL_URL}/transcript",
    ]


def test_expired_picker_is_refused(hook):
    """An answer that arrives after 15 minutes no longer belongs to that run."""
    picker = hook.ask()
    hook.age_pending(901)
    out, _, _ = hook.run_hook(hook.answer(picker, "Good"))
    assert out == ""
    assert hook.calls() == []


def test_picker_just_inside_the_window_is_accepted(hook):
    """The boundary matters: 899 seconds old is still the same conversation."""
    picker = hook.ask()
    hook.age_pending(890)
    hook.run_hook(hook.answer(picker, "Good"))
    assert hook.endpoints() == ["feedback"]


# --------------------------------------------------------------------------
# Transcript safety
# --------------------------------------------------------------------------


def test_transcript_is_uploaded_only_with_consent(hook):
    """The happy path: ticking the consent label sends the session file."""
    picker = hook.ask()
    mine = hook.run_slice()
    out, _, _ = hook.run_hook(hook.answer(picker, CONSENT))
    calls = hook.calls()
    assert [c["endpoint"] for c in calls] == ["feedback", "transcript"]
    assert calls[1]["body"] == mine
    assert SENTINEL.encode() in calls[1]["body"]  # this run did travel
    assert EARLIER.encode() not in calls[1]["body"]  # what came before did not
    assert calls[1]["fields"]["request_id"] == calls[0]["fields"]["request_id"]
    assert "feedback and transcript accepted" in out


def test_transcript_never_leaks_without_consent(hook):
    """Without the label, the file's bytes must appear nowhere in the curl log."""
    picker = hook.ask()
    out, _, _ = hook.run_hook(hook.answer(picker, "Good"))
    assert hook.endpoints() == ["feedback"]
    assert SENTINEL.encode() not in hook.curl_log_bytes()
    assert "kept private" in out


def test_swapped_transcript_file_is_not_uploaded(hook):
    """A path swapped between Stop and the answer is a different file; refuse it."""
    picker = hook.ask()
    decoy = hook.tmp / "decoy.jsonl"
    decoy.write_text("DECOY-CONTENT\n" * 50, encoding="utf-8")
    os.replace(decoy, hook.transcript)  # same path, new inode

    out, _, _ = hook.run_hook(hook.answer(picker, CONSENT))
    assert hook.endpoints() == ["feedback"]
    assert b"DECOY-CONTENT" not in hook.curl_log_bytes()
    assert "Transcript could not be sent" in out


def test_shrunken_transcript_is_not_uploaded(hook):
    """If the file lost bytes, the snapshot no longer describes it."""
    picker = hook.ask()
    with hook.transcript.open("r+b") as fh:
        fh.truncate(10)
    out, _, _ = hook.run_hook(hook.answer(picker, CONSENT))
    assert hook.endpoints() == ["feedback"]
    assert "Transcript could not be sent" in out


def test_transcript_over_four_mib_is_not_uploaded(hook):
    """Oversized sessions are dropped rather than streamed at the user."""
    hook.arm()
    hook.request()
    with hook.transcript.open("ab") as fh:
        fh.write(b"x" * (4 * 1024 * 1024 + 1))
    assert hook.transcript.stat().st_size > 4 * 1024 * 1024
    picker = hook.stop()
    hook.pre(picker)

    out, _, _ = hook.run_hook(hook.answer(picker, CONSENT))
    assert hook.endpoints() == ["feedback"]
    assert "Transcript could not be sent" in out


def test_only_the_skills_own_turns_are_uploaded(hook):
    """The run ends when the conversation moves on - not at /ratexp.

    Its question and the user's answer belong to it; the unrelated request the
    user made afterwards, and the agent's work on that, do not.
    """
    hook.arm()  # `/poem-creator`
    hook.append(type="assistant", text="Which mood would you like?")
    hook.append(type="user", text="SAD-PLEASE")
    hook.append(type="assistant", text="THE-POEM-BEING-RATED")
    hook.append(type="user", text="UNRELATED-REQUEST")
    hook.append(type="assistant", text="UNRELATED-WORK")
    hook.append(type="user", text="/ratexp:poem-creator")
    hook.request()
    picker = hook.stop()
    hook.pre(picker)
    hook.run_hook(hook.answer(picker, CONSENT))

    body = hook.calls()[1]["body"]
    for kept in (b"SAD-PLEASE", b"THE-POEM-BEING-RATED"):
        assert kept in body
    for dropped in (
        b"UNRELATED-REQUEST",
        b"UNRELATED-WORK",
        b"/ratexp:poem-creator",
        EARLIER.encode(),
    ):
        assert dropped not in body, f"not part of the run: {dropped!r}"


def test_a_skill_that_asks_through_the_picker_keeps_its_answer(hook):
    """AskUserQuestion answers come back as tool results, not the user speaking."""
    hook.arm()
    hook.append(
        type="assistant", message={"content": [{"type": "tool_use", "name": "AskUserQuestion"}]}
    )
    hook.append(
        type="user",
        message={"content": [{"type": "tool_result", "content": "ANSWERED-VIA-PICKER"}]},
    )
    hook.append(type="assistant", text="THE-POEM")
    hook.append(type="user", text="NEXT-TASK")
    hook.request()
    picker = hook.stop()
    hook.pre(picker)
    hook.run_hook(hook.answer(picker, CONSENT))
    body = hook.calls()[1]["body"]
    assert b"ANSWERED-VIA-PICKER" in body and b"THE-POEM" in body
    assert b"NEXT-TASK" not in body


def test_a_later_run_does_not_resend_the_earlier_ones(hook):
    """Rating the third use of a skill must send the third run, not the session.

    One session can hold many runs of the same skill plus unrelated chat. Each
    upload is bounded at both ends - it starts where its own run started, so the
    user consents to this run rather than to everything they have done today.
    """
    marks = [f"RUN-{i}-CONTENT" for i in range(3)]
    for i, mark in enumerate(marks):
        tool_id = f"toolu_run{i}"
        hook.arm()  # a fresh `/poem-creator`; this run starts here
        hook.request()
        hook.append(type="assistant", text=mark)  # the work it did
        picker = hook.stop()
        assert picker is not None, f"run {i} should have been surveyed"
        hook.pre(picker, tool_id=tool_id)
        hook.run_hook(hook.answer(picker, CONSENT, tool_id=tool_id))

    bodies = [c["body"] for c in hook.calls() if c["endpoint"] == "transcript"]
    assert len(bodies) == 3
    for i, body in enumerate(bodies):
        assert marks[i].encode() in body, f"run {i} must carry its own turns"
        others = [m for j, m in enumerate(marks) if j != i]
        for other in others:
            assert other.encode() not in body, f"run {i} also carried {other}"
        assert EARLIER.encode() not in body  # nor the chat before it


def test_symlinked_transcript_is_not_uploaded(hook):
    """A symlink could point anywhere; the hook only uploads a real file."""
    real = hook.tmp / "real.jsonl"
    real.write_text(f"{SENTINEL}\n", encoding="utf-8")
    hook.transcript.unlink()
    hook.transcript.symlink_to(real)

    hook.arm()
    hook.request()
    picker = hook.stop()
    assert picker is not None
    hook.pre(picker)
    out, _, _ = hook.run_hook(hook.answer(picker, CONSENT))
    assert hook.endpoints() == ["feedback"]
    assert "Transcript could not be sent" in out


# --------------------------------------------------------------------------
# Delivery failures
# --------------------------------------------------------------------------


def test_failed_feedback_blocks_the_transcript_and_is_not_retried(hook):
    """A rejected rating means the server has no record to attach a transcript to."""
    picker = hook.ask()
    out, _, _ = hook.run_hook(hook.answer(picker, CONSENT), env={"RATEXP_CURL_STATUS": "500"})
    assert hook.endpoints() == ["feedback"], "exactly one attempt, no retry"
    assert SENTINEL.encode() not in hook.curl_log_bytes()
    assert "could not be sent" in json.loads(out)["systemMessage"]


def test_failed_feedback_still_consumes_the_picker(hook):
    """Consuming before sending is what makes replay safe; a failure is final."""
    picker = hook.ask()
    hook.run_hook(hook.answer(picker, "Good"), env={"RATEXP_CURL_STATUS": "500"})
    out, _, _ = hook.run_hook(hook.answer(picker, "Good"))
    assert out == ""
    assert hook.endpoints() == ["feedback"]


@pytest.mark.parametrize("status", ["200", "204", "400", "503", "not-a-status"])
def test_only_201_counts_as_stored(hook, status):
    """The wire contract is 201; anything else is reported as a failure."""
    picker = hook.ask()
    out, _, _ = hook.run_hook(hook.answer(picker, "Good"), env={"RATEXP_CURL_STATUS": status})
    assert "could not be sent" in json.loads(out)["systemMessage"]


def test_stop_is_silent_the_second_time(hook):
    """One picker per invocation, even if the model stops again straight away."""
    hook.arm()
    hook.request()
    assert hook.stop() is not None
    assert hook.stop() is None


# --------------------------------------------------------------------------
# Poisoned local state
#
# The state directory is a plain directory owned by the user, so any process
# running as that user - including a model holding Bash or Write - can edit it.
# Nothing found in there may be treated as evidence, and no write into it may
# follow a symlink out to some other file.
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "poisoned",
    [
        pytest.param("-K/tmp/ratexp-evil.curlrc", id="curl-config-file"),
        pytest.param("https://evil.example", id="another-host"),
    ],
)
def test_poisoned_destination_in_the_stored_picker_sends_nothing(hook, poisoned):
    """The stored address gets the same check the configured one got.

    A leading `-` would otherwise become a curl option (`-K` reads a whole
    config file, so the attacker picks the destination, headers and uploads),
    and a plain https host would simply redirect the consented transcript.
    """
    picker = hook.ask()
    hook.patch_pending(url=poisoned)
    out, _, _ = hook.run_hook(hook.answer(picker, CONSENT))
    assert out == ""
    assert hook.calls() == [], "no curl invocation at all"
    assert SENTINEL.encode() not in hook.curl_log_bytes()


def test_poisoned_transcript_path_uploads_no_other_file(hook):
    """The device/inode check cannot vouch for a path from the same poisoned file.

    An attacker who names a file also writes its real stat values, so the
    upload has to start from the path this hook event carried instead.
    """
    secret = hook.tmp / "secret.txt"
    secret.write_text("TOP-SECRET-NOT-THE-TRANSCRIPT\n" * 20, encoding="utf-8")
    info = secret.stat()

    picker = hook.ask()
    hook.patch_pending(
        transcript=str(secret), size=info.st_size, identity=f"{info.st_dev}:{info.st_ino}"
    )
    out, _, _ = hook.run_hook(hook.answer(picker, CONSENT))
    assert hook.endpoints() == ["feedback"]
    assert b"TOP-SECRET" not in hook.curl_log_bytes()
    assert SENTINEL.encode() not in hook.curl_log_bytes()
    assert "Transcript could not be sent" in out


@pytest.mark.parametrize("name", ["count", "last-turn", "current.tmp"])
def test_planted_symlink_does_not_redirect_a_counter_write(hook, name):
    """Counting a turn must never write through a link left in the state directory."""
    hook.arm()  # creates the state directory, so the link can be planted inside
    victim = hook.plant_symlink(hook.base_dir() / name, name)
    hook.append(type="assistant", text="ANOTHER-TURN")
    hook.stop({"RATEXP_EVERY": "1"})
    hook.arm()
    hook.request()
    hook.stop()
    assert victim.read_text(encoding="utf-8") == "KEEP ME\n"


def test_planted_symlink_does_not_redirect_the_stored_picker(hook):
    """Stop writes the picker to `pending`; a link there stops it, never redirects it."""
    hook.arm()
    hook.request()
    # The run this Stop will use is named for the transcript as it stands now.
    info = hook.transcript.stat()
    run = hook.base_dir() / "runs" / f"turn-{info.st_dev}-{info.st_ino}-{info.st_size}"
    run.mkdir(parents=True)
    (run / "ask").touch()
    (hook.base_dir() / "current").write_text(run.name, encoding="utf-8")
    victim = hook.plant_symlink(run / "pending", "pending")
    assert hook.stop() is None, "a poisoned state directory must not produce a picker"
    assert victim.read_text(encoding="utf-8") == "KEEP ME\n"


def test_planted_symlink_does_not_redirect_the_delivery_note(hook):
    """The note still reaches the user, but the copy on disk is skipped, not followed."""
    picker = hook.ask()
    victim = hook.plant_symlink(hook.run_dir() / "status", "status")
    out, _, _ = hook.run_hook(hook.answer(picker, "Good"))
    assert "feedback accepted" in out
    assert victim.read_text(encoding="utf-8") == "KEEP ME\n"


def test_planted_symlink_does_not_redirect_the_tool_binding(hook):
    """PreToolUse records which run owns a tool id; that write must not follow a link."""
    hook.arm()
    hook.request()
    picker = hook.stop()
    assert picker is not None
    victim = hook.plant_symlink(hook.base_dir() / "tools" / TOOL_ID, "tools")
    out, _, _ = hook.pre(picker)
    assert out == "", "an unmodified picker is still allowed silently"
    assert victim.read_text(encoding="utf-8") == "KEEP ME\n"
