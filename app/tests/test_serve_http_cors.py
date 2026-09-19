"""resolve_cors_origins - defaults to wildcard in local; requires an allowlist in prod.

We patch the module-level ENV / CORS_ORIGINS_RAW directly rather than reloading the
module, because reload would re-execute the `app.add_middleware` line and fail before
the test could call the function.
"""

from __future__ import annotations

import pytest


def _patch_env(monkeypatch, env_value: str, origins_value: str | None):
    from api import serve_http

    monkeypatch.setattr(serve_http, "ENV", env_value)
    monkeypatch.setattr(serve_http, "CORS_ORIGINS_RAW", origins_value)
    return serve_http


def test_local_env_defaults_to_wildcard(monkeypatch):
    serve_http = _patch_env(monkeypatch, env_value="local", origins_value=None)
    assert serve_http.resolve_cors_origins() == ["*"]


def test_empty_env_defaults_to_wildcard(monkeypatch):
    serve_http = _patch_env(monkeypatch, env_value="", origins_value=None)
    assert serve_http.resolve_cors_origins() == ["*"]


def test_prod_env_without_origins_raises(monkeypatch):
    serve_http = _patch_env(monkeypatch, env_value="prod", origins_value=None)
    with pytest.raises(RuntimeError, match="requires RATEXP_CORS_ORIGINS"):
        serve_http.resolve_cors_origins()


def test_cors_origins_parsed_with_whitespace_stripped(monkeypatch):
    serve_http = _patch_env(
        monkeypatch,
        env_value="prod",
        origins_value=" https://a.test , https://b.test ",
    )
    assert serve_http.resolve_cors_origins() == ["https://a.test", "https://b.test"]


def test_cors_origins_empty_values_dropped(monkeypatch):
    serve_http = _patch_env(
        monkeypatch,
        env_value="prod",
        origins_value="https://a.test,,https://b.test,",
    )
    assert serve_http.resolve_cors_origins() == ["https://a.test", "https://b.test"]
