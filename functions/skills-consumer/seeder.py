"""Seed RateXp with agentic feedback.

Each call to seed_once() picks a random skill, has a LangChain agent load it and do a
small task, then gives RateXp feedback: an honest good/bad score, a comment, and its
consent to store the conversation transcript. A timer trigger (see seed/__init__.py)
calls it on a schedule so feedback keeps trickling in. Everything tunable lives in
config.yaml.
"""

from __future__ import annotations

import logging
import os
import random
import re
import sched
import shutil
import tempfile
import time
import uuid
from functools import lru_cache
from pathlib import Path

log = logging.getLogger("seeder")

import requests
import yaml
from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langchain.tools import tool

HERE = Path(__file__).resolve().parent
FRAMEWORK = "langchain"
_SOURCE = {"human": "user", "ai": "agent", "tool": "system"}


@lru_cache(maxsize=1)
def config() -> dict:
    load_dotenv(HERE / ".env")  # keys/endpoints live in .env; real env vars win
    cfg = yaml.safe_load((HERE / "config.yaml").read_text())
    cfg["model"] = os.environ.get("MODEL", cfg["model"])
    cfg["core_url"] = os.environ.get("RATEXP_CORE_URL", cfg["core_url"]).rstrip("/")
    return cfg


@lru_cache(maxsize=1)
def skills() -> tuple[dict, ...]:
    found = []
    for md in sorted((HERE / "skills").glob("*/SKILL.md")):
        text = md.read_text()
        name, body = md.parent.name, text
        if text.startswith("---") and (end := text.find("\n---", 3)) != -1:
            match = re.search(r'^name:\s*"?([^"\n]+)"?', text[3:end], re.M)
            name = match.group(1).strip() if match else name
            body = text[end + 4:].lstrip("\n")
        found.append({"name": name, "prompt": body})
    return tuple(found)


def _model_name() -> str:
    return config()["model"].split(":")[-1]


def _init_model():
    """Build the chat model. For Azure OpenAI with no API key set, auth passwordlessly
    with the host's Managed Identity (locally: your `az login`) via an Entra token - this
    is how the deployed function reaches AI Foundry (it holds "Cognitive Services OpenAI
    User" on the account). A plain openai: model, or an explicit key, takes its usual path.
    """
    cfg = config()
    kwargs = {"temperature": cfg["temperature"]}
    if cfg["model"].startswith("azure_openai:") and not os.environ.get("AZURE_OPENAI_API_KEY"):
        from azure.identity import DefaultAzureCredential, get_bearer_token_provider

        kwargs["azure_ad_token_provider"] = get_bearer_token_provider(
            DefaultAzureCredential(), "https://cognitiveservices.azure.com/.default")
    return init_chat_model(cfg["model"], **kwargs)


def _text(content) -> str:
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content if isinstance(b, dict))
    return str(content or "")


def _steps(messages) -> list[dict]:
    """LangChain messages -> ATIF transcript steps (with per-agent-turn token usage)."""
    steps: list[dict] = []
    for msg in messages:
        source = _SOURCE.get(getattr(msg, "type", None))
        if not source:
            continue
        step = {"step_id": len(steps) + 1, "source": source}
        text = _text(msg.content)
        if source == "system":
            step["observation"] = text[:1000]
        elif text:
            step["message"] = text
        calls = [{"tool_call_id": c.get("id") or str(uuid.uuid4()), "name": c.get("name"),
                  "arguments": c.get("args", {})} for c in getattr(msg, "tool_calls", None) or []]
        if calls:
            step["tool_calls"] = calls
        if len(step) == 2:
            continue  # no message / observation / tool_calls
        usage = getattr(msg, "usage_metadata", None) or {}
        if source == "agent" and (usage.get("input_tokens") or usage.get("output_tokens")):
            step["metrics"] = {"prompt_tokens": usage.get("input_tokens") or 0,
                               "completion_tokens": usage.get("output_tokens") or 0}
        steps.append(step)
    return steps


# Bytes of filler that reliably pushes an ATIF body past core's max_transcript_bytes
# (256 KiB), so an oversized run is stored as a meta-only stub rather than full steps.
_OVERSIZED_PAD_BYTES = 300_000


def _post_transcript(ctx: dict, messages, session: requests.Session) -> bool:
    steps = _steps(messages)
    prompt_tokens = sum(s["metrics"]["prompt_tokens"] for s in steps if "metrics" in s)
    completion_tokens = sum(s["metrics"]["completion_tokens"] for s in steps if "metrics" in s)
    total_steps = len(steps)
    # On an `oversized_ratio` share of runs, bloat the trajectory past core's size limit
    # so we exercise the "too large -> stored as a meta-only stub" path end to end. The
    # kept totals (above) reflect the real run; the padding step is just synthetic bulk.
    if random.random() < config().get("oversized_ratio", 0):
        steps.append({"step_id": len(steps) + 1, "source": "system",
                      "observation": "synthetic oversized-trajectory padding\n"
                                     + "x" * _OVERSIZED_PAD_BYTES})
    resp = session.post(f"{config()['core_url']}/transcript", timeout=60, json={
        "skill_name": ctx["skill"], "agent": ctx["agent"],
        "session_id": ctx["session_id"], "request_id": ctx["request_id"],
        "atif": {
            "schema_version": "ATIF-v1.7",
            "session_id": ctx["session_id"],
            "agent": {"name": FRAMEWORK, "model_name": _model_name()},
            "steps": steps,
            "final_metrics": {
                "total_prompt_tokens": prompt_tokens,
                "total_completion_tokens": completion_tokens,
                "total_steps": total_steps,
            },
        },
    })
    return resp.ok


def _run_skill(skill: dict, session: requests.Session) -> tuple[bool, bool]:
    """Run one skill agentically. Returns (feedback_submitted, transcript_stored)."""
    cfg = config()
    rounds = cfg["max_rounds"]
    ctx = {"skill": skill["name"], "agent": f"{FRAMEWORK} {_model_name()}",
           "session_id": str(uuid.uuid4()), "request_id": str(uuid.uuid4()),
           "submitted": False, "store_transcript": False}
    workspace = Path(tempfile.mkdtemp(prefix="ratexp-skill-"))

    def _resolve(path: str) -> Path | None:
        # Treat any path as relative to the workspace (strip leading "/"); reject
        # only real ".." escapes, and return None so the tool can warn rather than crash.
        target = (workspace / path.lstrip("/")).resolve()
        return target if target.is_relative_to(workspace) else None

    @tool
    def load_skill() -> str:
        """Load this skill's full instructions (its SKILL.md)."""
        return skill["prompt"]

    @tool
    def list_files(path: str = ".") -> str:
        """List the files in your scratch workspace."""
        base = _resolve(path)
        if base is None:
            return "Path must stay inside the workspace; use a relative path."
        names = [p.relative_to(workspace).as_posix() + ("/" if p.is_dir() else "")
                 for p in sorted(base.rglob("*"))]
        return "\n".join(names) or "(empty)"

    @tool
    def read_file(path: str) -> str:
        """Read a file from your scratch workspace."""
        target = _resolve(path)
        if target is None:
            return "Path must stay inside the workspace; use a relative path."
        return target.read_text()[:4000] if target.is_file() else f"No such file: {path}"

    @tool
    def write_file(path: str, content: str) -> str:
        """Create or overwrite a file in your scratch workspace."""
        target = _resolve(path)
        if target is None:
            return "Path must stay inside the workspace; use a relative path."
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
        return f"wrote {path} ({len(content)} bytes)"

    @tool
    def fetch_feedback_form() -> str:
        """Fetch the RateXp feedback form the skill points to."""
        return session.get(f"{cfg['core_url']}/snippet", params={"every": 1}, timeout=10).text[:4000]

    @tool
    def submit_feedback(score: int, comment: str = "", store_transcript: bool = True) -> str:
        """Submit RateXp feedback. score: 1 = good, 2 = bad.
        store_transcript: also store this conversation along with the feedback."""
        # This demo seeder always keeps its trajectory, so good and bad ratings both ship
        # one - never let a tough-review turn quietly decline consent and drop it.
        ctx["store_transcript"] = True
        resp = session.post(f"{cfg['core_url']}/feedback", timeout=10, data={
            "skill_name": ctx["skill"], "agent": ctx["agent"], "score": int(score),
            "comment": comment, "session_id": ctx["session_id"], "request_id": ctx["request_id"],
        })
        ctx["submitted"] = ctx["submitted"] or resp.ok
        return "stored" if resp.ok else "error"

    prompt_fields = {"name": skill["name"], "max_rounds": rounds}
    agent = create_agent(
        model=_init_model(),
        tools=[load_skill, list_files, read_file, write_file, fetch_feedback_form, submit_feedback],
        system_prompt=cfg["system_prompt"].format(**prompt_fields),
    )
    # On a `critical_ratio` share of runs, take the tough-reviewer stance so bad ratings
    # (score 2) keep flowing instead of an unbroken stream of praise.
    task = cfg["task_prompt"].format(**prompt_fields)
    if random.random() < cfg.get("critical_ratio", 0):
        task += "\n\n" + cfg["critical_prompt"]
    try:
        # langgraph counts ~2 steps per round (think + act); cap the loop accordingly.
        messages = agent.invoke(
            {"messages": [{"role": "user", "content": task}]},
            {"recursion_limit": 2 * rounds + 1},
        )["messages"]
    finally:
        shutil.rmtree(workspace, ignore_errors=True)

    stored = bool(ctx["store_transcript"]) and _post_transcript(ctx, messages, session)
    return ctx["submitted"], bool(stored)


def seed_once() -> dict:
    """Run one random skill end to end. Never raises - a failed run shouldn't kill the timer."""
    pool = list(skills())
    if not pool:
        return {"skill": None, "feedback_sent": False, "transcript_stored": False,
                "error": "no skills found under skills/*/SKILL.md"}
    skill = random.choice(pool)
    try:
        with requests.Session() as session:
            submitted, stored = _run_skill(skill, session)
    except Exception as exc:
        return {"skill": skill["name"], "feedback_sent": False,
                "transcript_stored": False, "error": str(exc)}
    return {"skill": skill["name"], "feedback_sent": bool(submitted),
            "transcript_stored": bool(stored)}


def run_local() -> None:
    """Seed continuously without the Functions runtime: `python seeder.py`.

    A sched scheduler re-arms itself after each run (no `while True`), so the next run
    starts `interval_seconds` after the previous one finishes - the same cadence the
    Azure timer trigger gives in production.
    """
    interval = config()["interval_seconds"]
    scheduler = sched.scheduler(time.monotonic, time.sleep)

    def tick() -> None:
        result = seed_once()
        if result.get("error"):
            log.error("seed run failed (%s): %s", result.get("skill"), result["error"])
        else:
            log.info("seeded skill=%s feedback=%s transcript=%s", result["skill"],
                     result["feedback_sent"], result["transcript_stored"])
        scheduler.enter(interval, 1, tick)  # re-arm for the next run

    log.info("seeding continuously -> %s, %ss between runs (Ctrl-C to stop)",
             config()["core_url"], interval)
    scheduler.enter(0, 1, tick)  # first run now
    scheduler.run()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        run_local()
    except KeyboardInterrupt:
        pass
