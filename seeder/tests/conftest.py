"""Shared fixtures. Nothing here reaches a model, a core, or the network.

Config arrives as module-level constants (see load_config.py), so a test wanting a
different value patches it on the module that imported it - `monkeypatch.setattr`
on, say, `build_trajectory.OVERSIZED_RATIO`, never on load_config itself.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

# pytest puts this folder on sys.path, not its parent, so `api.*` and `modules.*`
# would not resolve. Add seeder/ itself, the directory the container imports from.
_SEEDER_DIR = Path(__file__).resolve().parent.parent
if str(_SEEDER_DIR) not in sys.path:
    sys.path.insert(0, str(_SEEDER_DIR))


def message(kind, content="", tool_calls=None, usage=None):
    """A minimal stand-in for a LangChain message (only the fields ATIF building reads)."""
    return SimpleNamespace(
        type=kind, content=content, tool_calls=tool_calls or [], usage_metadata=usage
    )


@pytest.fixture
def run():
    """The identity both submissions carry, with fixed ids so tests can assert on them."""
    from api.record_schemas import SeededRun

    return SeededRun(
        skill_name="demo", agent="langchain gpt-4o-mini", session_id="s", request_id="r"
    )


class _Response:
    """Minimal stand-in for what urlopen() returns (a context manager with .status)."""

    def __init__(self, status):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def posted(monkeypatch):
    """Capture every POST the seeder would send instead of sending it.

    `.sent` is the list of captured requests; set `.status` before the call under
    test to have core answer with something other than 201.
    """
    from modules.submit import post_to_core

    capture = SimpleNamespace(sent=[], status=201)

    def fake_urlopen(request, timeout=None):
        capture.sent.append(
            {
                "url": request.full_url,
                "method": request.get_method(),
                "headers": {k.lower(): v for k, v in request.header_items()},
                "body": json.loads(request.data.decode()),
            }
        )
        return _Response(capture.status)

    monkeypatch.setattr(post_to_core.urllib.request, "urlopen", fake_urlopen)
    return capture
