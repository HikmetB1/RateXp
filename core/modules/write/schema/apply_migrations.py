"""Numbered-SQL migration applier. Self-contained per service (not shared).

The ``NNN_*.sql`` files next to this one are applied in ascending number order,
and a number already recorded in ``schema_version`` is never re-run. So an
applied file must not be edited - add the next number instead.
"""

from __future__ import annotations

import re
from pathlib import Path

from modules.write.connect_to_postgres import connect

_MIGRATIONS_DIR = Path(__file__).resolve().parent
_VERSION_RE = re.compile(r"^(\d+)_")
_SCHEMA_VERSION_DDL = """
CREATE TABLE IF NOT EXISTS schema_version (
    version    INTEGER PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


def apply_migrations(dsn: str | None = None, auth: str | None = None) -> None:
    """Apply any migration files not yet recorded in schema_version.

    With no arguments, targets RateXp's own database (env defaults). A destination
    adapter passes dsn/auth to migrate another PostgreSQL (see
    ../adapters/write_to_postgres.py).
    """
    conn_ctx = connect() if dsn is None else connect(dsn, auth or "password")
    with conn_ctx as conn, conn.cursor() as cur:
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
