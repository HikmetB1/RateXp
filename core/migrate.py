"""Numbered-SQL migration applier. Self-contained per service (not shared)."""

from __future__ import annotations

import re
from pathlib import Path

from db import connect

_MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
_VERSION_RE = re.compile(r"^(\d+)_")
_SCHEMA_VERSION_DDL = """
CREATE TABLE IF NOT EXISTS schema_version (
    version    INTEGER PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


def apply_migrations() -> None:
    """Apply any migration files not yet recorded in schema_version."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(_SCHEMA_VERSION_DDL)
        cur.execute("SELECT version FROM schema_version")
        applied = {row[0] for row in cur.fetchall()}
        conn.commit()

        for path in sorted(_MIGRATIONS_DIR.glob("*.sql")):
            m = _VERSION_RE.match(path.name)
            if not m:
                continue
            version = int(m.group(1))
            if version in applied:
                continue
            cur.execute(path.read_text(encoding="utf-8"))
            cur.execute("INSERT INTO schema_version (version) VALUES (%s)", (version,))
            conn.commit()
