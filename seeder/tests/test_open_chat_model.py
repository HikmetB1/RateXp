"""What the seeder calls its model - the name stamped on every record it submits."""

from __future__ import annotations

from modules.agent import open_chat_model as model_module


def test_model_name_drops_the_provider_prefix(monkeypatch):
    monkeypatch.setattr(model_module, "MODEL", "azure_openai:my-deploy")
    assert model_module.model_name() == "my-deploy"


def test_model_name_is_the_whole_id_when_there_is_no_prefix(monkeypatch):
    monkeypatch.setattr(model_module, "MODEL", "gpt-4o-mini")
    assert model_module.model_name() == "gpt-4o-mini"
