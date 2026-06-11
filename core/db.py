"""PostgreSQL connection helpers with two auth modes (`RATEXP_DB_AUTH`).

- `password` (default, local): the password comes from `DATABASE_URL`.
- `entra` (cloud): no stored password. The Managed Identity fetches a short-lived
  Entra ID token and uses it as the password, fetched fresh per connection.

`DATABASE_URL` is a standard libpq string; in `entra` mode it carries everything
but the password.
"""

from __future__ import annotations

import os
import threading

import psycopg
from psycopg_pool import ConnectionPool

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://ratexp:ratexp@localhost:5432/ratexp",
)
DB_AUTH = os.environ.get("RATEXP_DB_AUTH", "password").lower()

# Azure Database for PostgreSQL Entra token audience.
_ENTRA_SCOPE = "https://ossrdbms-aad.database.windows.net/.default"

_token_lock = threading.Lock()
_cached_token: tuple[str, float] | None = None  # (token, expires_on epoch seconds)


def _entra_token() -> str:
    """Return a cached Entra access token, refreshing shortly before expiry.

    Imported lazily so `azure-identity` is only needed in the cloud image.
    """
    global _cached_token
    import time

    with _token_lock:
        now = time.time()
        if _cached_token and _cached_token[1] - now > 300:
            return _cached_token[0]
        from azure.identity import DefaultAzureCredential

        token = DefaultAzureCredential().get_token(_ENTRA_SCOPE)
        _cached_token = (token.token, float(token.expires_on))
        return token.token


class _EntraConnection(psycopg.Connection):
    """psycopg connection that injects a fresh Entra token as the password."""

    @classmethod
    def connect(cls, conninfo: str = "", **kwargs):  # type: ignore[override]
        return super().connect(conninfo, password=_entra_token(), **kwargs)


def _pool_kwargs() -> dict:
    if DB_AUTH == "entra":
        return {"connection_class": _EntraConnection}
    return {}


def make_pool(*, min_size: int = 1, max_size: int = 10) -> ConnectionPool:
    """Open a connection pool using the configured auth mode."""
    return ConnectionPool(
        DATABASE_URL,
        min_size=min_size,
        max_size=max_size,
        open=True,
        kwargs={},
        **_pool_kwargs(),
    )


def connect() -> psycopg.Connection:
    """Open a single connection (used by migrations) with the configured auth."""
    if DB_AUTH == "entra":
        return _EntraConnection.connect(DATABASE_URL)
    return psycopg.connect(DATABASE_URL)
