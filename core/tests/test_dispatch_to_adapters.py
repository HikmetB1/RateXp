"""The fan-out: build the enabled destinations, write to all of them, at least one
must accept.

What each destination does with the record is in test_write_adapters.py.
"""

from __future__ import annotations

import logging

import pytest
from api.record_schemas import Feedback, Transcript
from modules.write import dispatch_to_adapters


class _Recorder:
    def __init__(self, name: str, *, boom: bool = False, boom_on_close: bool = False):
        self.name = name
        self.boom = boom
        self.boom_on_close = boom_on_close
        self.feedback: list = []
        self.transcripts: list = []
        self.closed = False

    def write_feedback(self, record):
        if self.boom:
            raise RuntimeError(f"{self.name} down")
        self.feedback.append(record)

    def write_transcript(self, record):
        if self.boom:
            raise RuntimeError(f"{self.name} down")
        self.transcripts.append(record)

    def close(self):
        self.closed = True
        if self.boom_on_close:
            raise RuntimeError(f"{self.name} would not close")


def _use(monkeypatch, *adapters: _Recorder) -> None:
    monkeypatch.setattr(dispatch_to_adapters, "_adapters", list(adapters))


def _feedback() -> Feedback:
    return Feedback(skill_name="demo", agent="claude-code")


def _transcript() -> Transcript:
    return Transcript(skill_name="demo", agent="claude-code", atif={"steps": []})


def test_every_destination_receives_the_record(monkeypatch):
    first, second = _Recorder("first"), _Recorder("second")
    _use(monkeypatch, first, second)
    dispatch_to_adapters.write_feedback(_feedback())
    assert len(first.feedback) == 1
    assert len(second.feedback) == 1


def test_one_destination_failing_does_not_stop_the_others(monkeypatch):
    bad, good = _Recorder("bad", boom=True), _Recorder("good")
    _use(monkeypatch, bad, good)
    # `good` accepted it, so the write succeeded despite `bad` blowing up.
    dispatch_to_adapters.write_transcript(_transcript())
    assert len(good.transcripts) == 1


def test_a_failing_destination_is_named_in_the_log(monkeypatch, caplog):
    # A destination can be down for days without anything else going wrong, so
    # the log line is the only way anyone finds out which one.
    _use(monkeypatch, _Recorder("bad", boom=True), _Recorder("good"))
    with caplog.at_level(logging.WARNING):
        dispatch_to_adapters.write_feedback(_feedback())
    assert "bad" in caplog.text


def test_a_rating_no_destination_accepted_raises(monkeypatch):
    _use(monkeypatch, _Recorder("a", boom=True), _Recorder("b", boom=True))
    with pytest.raises(dispatch_to_adapters.WriteError):
        dispatch_to_adapters.write_feedback(_feedback())


def test_a_trajectory_no_destination_accepted_raises(monkeypatch):
    _use(monkeypatch, _Recorder("a", boom=True))
    with pytest.raises(dispatch_to_adapters.WriteError):
        dispatch_to_adapters.write_transcript(_transcript())


def test_shutdown_closes_every_destination_and_forgets_them(monkeypatch):
    first, second = _Recorder("first"), _Recorder("second")
    _use(monkeypatch, first, second)
    dispatch_to_adapters.close_adapters()
    assert first.closed and second.closed
    # Cleared, so the next get_adapters() rebuilds rather than handing back
    # adapters whose pools and exporters are already shut down.
    assert dispatch_to_adapters._adapters is None


def test_one_destination_failing_to_close_does_not_strand_the_others(monkeypatch):
    stubborn, other = _Recorder("stubborn", boom_on_close=True), _Recorder("other")
    _use(monkeypatch, stubborn, other)
    dispatch_to_adapters.close_adapters()
    assert other.closed  # a Dynatrace flush that times out must not skip the DB pool


# --- building the destination list from config.yaml ---------------------------


def _adapter_config(**enabled_by_name) -> dict:
    """The six destinations, all off, then the named ones turned on."""
    config = {
        "app_be_psql": {"enabled": False},
        "custom_psql": {"enabled": False, "dsn_env": "UNUSED_DSN"},
        "app_be_dynatrace": {
            "enabled": False,
            "tenant_url_env": "UNUSED_TENANT",
            "token_env": "UNUSED_TOKEN",
        },
        "custom_dynatrace": {
            "enabled": False,
            "tenant_url_env": "UNUSED_TENANT",
            "token_env": "UNUSED_TOKEN",
        },
        "bluebox": {
            "enabled": False,
            "endpoint_env": "UNUSED_ENDPOINT",
            "token_env": "UNUSED_TOKEN",
        },
        "phoenix": {
            "enabled": False,
            "endpoint_env": "UNUSED_ENDPOINT",
            "api_key_env": "UNUSED_KEY",
            "project_env": "UNUSED_PROJECT",
        },
    }
    for name in enabled_by_name:
        config[name]["enabled"] = True
    return config


def test_a_disabled_destination_is_not_built(monkeypatch):
    import load_config

    monkeypatch.setattr(load_config, "WRITE_ADAPTERS", _adapter_config())
    assert dispatch_to_adapters.build_write_adapters() == []


def test_an_enabled_destination_missing_its_secret_is_skipped_not_fatal(monkeypatch):
    """A half-configured destination must not take the service down at boot.

    Every one of these is enabled but has no env var behind it, so every one
    fails to build. core still starts, and the ones that do work still work.
    """
    import load_config

    monkeypatch.setattr(
        load_config,
        "WRITE_ADAPTERS",
        _adapter_config(custom_psql=True, app_be_dynatrace=True, bluebox=True, phoenix=True),
    )
    for var in (
        "UNUSED_DSN",
        "UNUSED_TENANT",
        "UNUSED_TOKEN",
        "UNUSED_ENDPOINT",
        "UNUSED_KEY",
        "UNUSED_PROJECT",
    ):
        monkeypatch.delenv(var, raising=False)
    assert dispatch_to_adapters.build_write_adapters() == []


def test_an_enabled_destination_is_built_without_touching_it(monkeypatch):
    # The pool opens on the first write, not here, so a database that is slow to
    # come up does not block the boot.
    import load_config

    monkeypatch.setattr(load_config, "WRITE_ADAPTERS", _adapter_config(app_be_psql=True))
    assert [a.name for a in dispatch_to_adapters.build_write_adapters()] == ["app_be_psql"]


def test_a_config_naming_a_destination_that_does_not_exist_is_skipped(monkeypatch):
    import load_config

    monkeypatch.setattr(load_config, "WRITE_ADAPTERS", {"typo_psql": {"enabled": True}})
    assert dispatch_to_adapters.build_write_adapters() == []
