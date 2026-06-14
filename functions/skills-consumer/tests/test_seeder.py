"""Seeder helpers - pure unit tests, no network or LLM calls (those are stubbed)."""

from __future__ import annotations

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


def test_seed_once_reports_when_no_skills(monkeypatch):
    monkeypatch.setattr(seeder, "skills", lambda: ())
    result = seeder.seed_once()
    assert result["feedback_sent"] is False
    assert "no skills" in result["error"]


def test_seed_once_returns_run_result(monkeypatch):
    monkeypatch.setattr(seeder, "skills", lambda: ({"name": "demo", "prompt": "x"},))
    monkeypatch.setattr(seeder, "_run_skill", lambda skill, session: (True, True))
    assert seeder.seed_once() == {"skill": "demo", "feedback_sent": True, "transcript_stored": True}


def test_seed_once_swallows_run_errors(monkeypatch):
    monkeypatch.setattr(seeder, "skills", lambda: ({"name": "demo", "prompt": "x"},))

    def boom(skill, session):
        raise RuntimeError("nope")

    monkeypatch.setattr(seeder, "_run_skill", boom)
    result = seeder.seed_once()
    assert result["skill"] == "demo"
    assert result["error"] == "nope"
    assert result["feedback_sent"] is False
