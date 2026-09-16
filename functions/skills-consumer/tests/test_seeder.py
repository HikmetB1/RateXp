"""Seeder helpers - pure unit tests, no network or LLM calls (those are stubbed)."""

from __future__ import annotations

import json
import urllib.error
from types import SimpleNamespace

import seeder


def _msg(kind, content="", tool_calls=None, usage=None):
    """A minimal stand-in for a LangChain message (only the fields `_steps` reads)."""
    return SimpleNamespace(
        type=kind, content=content, tool_calls=tool_calls or [], usage_metadata=usage
    )


def test_config_applies_env_overrides(monkeypatch):
    monkeypatch.setenv("MODEL", "openai:gpt-4o")
    monkeypatch.setenv("RATEXP_CORE_URL", "http://core:8000/")  # trailing slash trimmed
    seeder.config.cache_clear()
    cfg = seeder.config()
    assert cfg["model"] == "openai:gpt-4o"
    assert cfg["core_url"] == "http://core:8000"
    seeder.config.cache_clear()


def test_model_name_is_last_segment(monkeypatch):
    monkeypatch.setenv("MODEL", "azure_openai:my-deploy")
    seeder.config.cache_clear()
    assert seeder._model_name() == "my-deploy"
    seeder.config.cache_clear()


def test_skills_loads_bundled_skills():
    pool = seeder.skills()
    assert pool, "ships with skills/*/SKILL.md"
    assert all(s["name"] and s["prompt"] for s in pool)


def test_text_joins_text_blocks_and_ignores_non_dicts():
    assert seeder._text("hi") == "hi"
    assert seeder._text(None) == ""
    assert seeder._text([{"text": "a"}, "skip", {"text": "b"}]) == "a\nb"


def test_steps_maps_sources_calls_and_metrics():
    messages = [
        _msg("human", "hello"),
        _msg(
            "ai",
            "on it",
            tool_calls=[{"id": "t1", "name": "load_skill", "args": {}}],
            usage={"input_tokens": 10, "output_tokens": 4},
        ),
        _msg("tool", "tool output"),
        _msg("ai", ""),  # empty agent turn, no calls -> dropped
    ]
    steps = seeder._steps(messages)
    assert [s["source"] for s in steps] == ["user", "agent", "system"]
    assert steps[0]["message"] == "hello"
    assert steps[1]["tool_calls"][0]["name"] == "load_skill"
    assert steps[1]["metrics"] == {"prompt_tokens": 10, "completion_tokens": 4}
    assert steps[2]["observation"] == "tool output"


def _ctx():
    return {"skill": "demo", "agent": "agent", "session_id": "s", "request_id": "r"}


def _cfg(oversized_ratio):
    return {"core_url": "http://core", "model": "openai:gpt-4o-mini",
            "oversized_ratio": oversized_ratio}


def test_build_atif_pads_past_size_limit_when_oversized(monkeypatch):
    monkeypatch.setattr(seeder, "config", lambda: _cfg(1))  # always oversized
    atif = seeder._build_atif(_ctx(), [])
    # The ATIF body exceeds core's max_transcript_bytes (256 KiB), so core will stub it.
    assert len(json.dumps(atif).encode()) > 262144
    # Kept totals reflect the real run (no real steps), not the synthetic padding.
    assert atif["final_metrics"]["total_steps"] == 0


def test_build_atif_no_padding_when_disabled(monkeypatch):
    monkeypatch.setattr(seeder, "config", lambda: _cfg(0))  # never oversized
    assert seeder._build_atif(_ctx(), [])["steps"] == []


class _Response:
    """Minimal stand-in for what urlopen() returns (a context manager with .status)."""

    def __init__(self, status):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _capture_posts(monkeypatch, status=201):
    """Record every urllib POST the seeder makes instead of sending it."""
    sent = []

    def fake_urlopen(request, timeout=None):
        sent.append({"url": request.full_url, "method": request.get_method(),
                     "headers": {k.lower(): v for k, v in request.header_items()},
                     "body": json.loads(request.data.decode())})
        return _Response(status)

    monkeypatch.setattr(seeder.urllib.request, "urlopen", fake_urlopen)
    return sent


def test_post_feedback_sends_rating_as_json(monkeypatch):
    monkeypatch.setattr(seeder, "config", lambda: _cfg(0))
    sent = _capture_posts(monkeypatch)
    assert seeder._post_feedback(_ctx(), seeder.Rating(score=2, comment="clunky")) is True
    assert sent[0]["url"] == "http://core/feedback"
    assert sent[0]["method"] == "POST"
    assert sent[0]["headers"]["content-type"] == "application/json"
    assert sent[0]["body"] == {"skill_name": "demo", "agent": "agent", "session_id": "s",
                               "request_id": "r", "score": 2, "comment": "clunky"}


def test_post_transcript_sends_atif_as_json(monkeypatch):
    monkeypatch.setattr(seeder, "config", lambda: _cfg(0))
    sent = _capture_posts(monkeypatch)
    assert seeder._post_transcript(_ctx(), []) is True
    assert sent[0]["url"] == "http://core/transcript"
    assert sent[0]["body"]["atif"]["session_id"] == "s"


def test_post_is_false_on_non_2xx(monkeypatch):
    monkeypatch.setattr(seeder, "config", lambda: _cfg(0))
    _capture_posts(monkeypatch, status=500)
    assert seeder._post("/feedback", {}) is False


def test_post_is_false_when_the_request_raises(monkeypatch):
    monkeypatch.setattr(seeder, "config", lambda: _cfg(0))

    def boom(request, timeout=None):
        raise urllib.error.URLError("core is down")

    monkeypatch.setattr(seeder.urllib.request, "urlopen", boom)
    assert seeder._post("/feedback", {}) is False


class _Agent:
    """Stand-in for a compiled langchain agent: returns a fixed final state."""

    def __init__(self, state):
        self.state = state

    def invoke(self, _inputs, _config=None):
        return self.state


def _stub_agent(monkeypatch, state):
    monkeypatch.setattr(seeder, "_init_model", lambda: None)
    monkeypatch.setattr(seeder, "create_agent", lambda **kwargs: _Agent(state))


def _run_cfg():
    return {**_cfg(0), "max_rounds": 3, "critical_ratio": 0, "temperature": 0.7,
            "system_prompt": "system {name} {max_rounds}",
            "task_prompt": "task {name} {max_rounds}", "critical_prompt": "be tough"}


def test_run_skill_posts_the_structured_rating(monkeypatch):
    monkeypatch.setattr(seeder, "config", lambda: _run_cfg())
    _stub_agent(monkeypatch, {"messages": [_msg("human", "hello")],
                              "structured_response": seeder.Rating(score=1, comment="clear")})
    sent = _capture_posts(monkeypatch)
    assert seeder._run_skill({"name": "demo", "prompt": "x"}) == (True, True)
    assert [s["url"] for s in sent] == ["http://core/feedback", "http://core/transcript"]
    assert sent[0]["body"]["score"] == 1
    assert sent[0]["body"]["comment"] == "clear"
    # Both posts describe the same run.
    assert sent[0]["body"]["request_id"] == sent[1]["body"]["request_id"]


def test_run_skill_without_a_rating_still_stores_the_transcript(monkeypatch):
    monkeypatch.setattr(seeder, "config", lambda: _run_cfg())
    _stub_agent(monkeypatch, {"messages": [], "structured_response": None})
    sent = _capture_posts(monkeypatch)
    assert seeder._run_skill({"name": "demo", "prompt": "x"}) == (False, True)
    assert [s["url"] for s in sent] == ["http://core/transcript"]


def test_seed_once_reports_when_no_skills(monkeypatch):
    monkeypatch.setattr(seeder, "skills", lambda: ())
    result = seeder.seed_once()
    assert result["feedback_sent"] is False
    assert "no skills" in result["error"]


def test_seed_once_returns_run_result(monkeypatch):
    monkeypatch.setattr(seeder, "skills", lambda: ({"name": "demo", "prompt": "x"},))
    monkeypatch.setattr(seeder, "_run_skill", lambda skill: (True, True))
    assert seeder.seed_once() == {"skill": "demo", "feedback_sent": True, "transcript_stored": True}


def test_seed_once_swallows_run_errors(monkeypatch):
    monkeypatch.setattr(seeder, "skills", lambda: ({"name": "demo", "prompt": "x"},))

    def boom(skill):
        raise RuntimeError("nope")

    monkeypatch.setattr(seeder, "_run_skill", boom)
    result = seeder.seed_once()
    assert result["skill"] == "demo"
    assert result["error"] == "nope"
    assert result["feedback_sent"] is False
