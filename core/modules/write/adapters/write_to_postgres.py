"""Shared PostgreSQL write logic for the psql destination adapters.

``PostgresWriteAdapter`` holds everything the psql destinations have in common (lazy
pool + migrations, the two INSERTs); the concrete adapters that use it live in
their own files and differ only in where they get their connection:

- ``write_to_app_be_psql.py`` -> ``AppBePostgresWriteAdapter`` (RateXp's own database).
- ``write_to_custom_psql.py`` -> ``CustomPostgresWriteAdapter`` (an adopter's own database).

The pool and migrations are built lazily on first write, so a database that is
briefly unreachable at boot doesn't disable the adapter - the next write retries.
"""

from __future__ import annotations

import json

from api.record_schemas import Feedback, Transcript


class PostgresWriteAdapter:
    def __init__(self, name: str, *, dsn: str, auth: str) -> None:
        self.name = name
        self._dsn = dsn
        self._auth = auth
        self._pool = None  # opened lazily so a boot-time DB hiccup isn't fatal

    def _ensure_pool(self):
        if self._pool is None:
            from modules.write.connect_to_postgres import make_pool
            from modules.write.schema.apply_migrations import apply_migrations

            apply_migrations(dsn=self._dsn, auth=self._auth)
            self._pool = make_pool(dsn=self._dsn, auth=self._auth)
        return self._pool

    def write_feedback(self, record: Feedback) -> None:
        with self._ensure_pool().connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO feedback
                  (created_at, session_id, skill_name, agent, score, comment, request_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (request_id) WHERE request_id IS NOT NULL DO NOTHING
                """,
                (
                    record.created_at,
                    record.session_id,
                    record.skill_name,
                    record.agent,
                    record.score,
                    record.comment,
                    record.request_id,
                ),
            )

    def write_transcript(self, record: Transcript) -> None:
        with self._ensure_pool().connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO transcript
                  (created_at, session_id, skill_name, agent, schema_version, atif, request_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (request_id) WHERE request_id IS NOT NULL DO NOTHING
                """,
                (
                    record.created_at,
                    record.session_id,
                    record.skill_name,
                    record.agent,
                    record.schema_version,
                    json.dumps(record.atif),
                    record.request_id,
                ),
            )

    def close(self) -> None:
        if self._pool is not None:
            self._pool.close()
            self._pool = None
