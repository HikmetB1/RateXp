"""The local hourly delete: what docker-compose.yml's opt-in `retention` profile runs."""

from __future__ import annotations

import pytest
from api import delete_old_ratings_hourly


class _Stop(Exception):
    pass


def test_it_deletes_at_once_then_once_an_hour(monkeypatch):
    events: list = []
    monkeypatch.setattr(
        delete_old_ratings_hourly, "delete_old_ratings_everywhere", lambda: events.append("delete")
    )

    def sleep(seconds):
        events.append(seconds)
        if events.count("delete") == 2:
            raise _Stop

    monkeypatch.setattr(delete_old_ratings_hourly.time, "sleep", sleep)
    with pytest.raises(_Stop):
        delete_old_ratings_hourly.delete_old_ratings_hourly()
    assert events == ["delete", 3600, "delete", 3600]
