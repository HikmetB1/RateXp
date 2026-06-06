"""Shared fixtures. Replaces the connection pool with an in-memory fake."""

from __future__ import annotations

import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

_PKG_DIR = Path(__file__).resolve().parent.parent
if str(_PKG_DIR) not in sys.path:
    sys.path.insert(0, str(_PKG_DIR))


class _Col:
    """Minimal stand-in for a psycopg column descriptor (only `.name` is used)."""

    def __init__(self, name):
        self.name = name


class FakeCursor:
    """Records SQL/params; returns canned rows (and columns) for SELECTs."""

    def __init__(self, store):
        self._store = store
        self._next_select_rows: list[tuple] = []
        self._next_columns: list[str] = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, sql, params=()):
        # SET LOCAL / SET TRANSACTION pre-statements pass through harmlessly;
        # only a real SELECT arms the canned rows + description.
        self._store["sql"] = sql
        self._store["params"] = params
        if "SELECT" in sql.upper():
            self._store["last_select_rows"] = self._next_select_rows
            self._store["last_columns"] = self._next_columns

    @property
    def description(self):
        cols = self._store.get("last_columns", [])
        return [_Col(c) for c in cols] if cols else None

    def fetchall(self):
        return self._store.get("last_select_rows", [])


class FakeConnection:
    def __init__(self, store):
        self._store = store

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    @contextmanager
    def transaction(self):
        yield self

    def cursor(self):
        cur = FakeCursor(self._store)
        cur._next_select_rows = self._store.get("__select_rows__", [])
        cur._next_columns = self._store.get("__columns__", [])
        return cur


class FakePool:
    """Drop-in for the psycopg connection pool used by the server."""

    def __init__(self):
        self.store: dict = {}
        self.raise_on_execute: Exception | None = None

    @contextmanager
    def connection(self):
        if self.raise_on_execute is not None:
            raise self.raise_on_execute
        yield FakeConnection(self.store)

    def close(self):
        pass

    def set_select_rows(self, rows):
        self.store["__select_rows__"] = rows

    def set_columns(self, columns):
        self.store["__columns__"] = columns


@pytest.fixture
def app_with_fake_pool(monkeypatch):
    """Boot the FastAPI app with a fake pool installed (no real database)."""
    import importlib

    import server

    importlib.reload(server)

    fake_pool = FakePool()
    monkeypatch.setattr(server, "make_pool", lambda *_a, **_k: fake_pool)

    from fastapi.testclient import TestClient

    with TestClient(server.app) as client:
        yield client, fake_pool
