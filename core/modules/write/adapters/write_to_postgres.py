"""Shared PostgreSQL write logic for the psql destination adapters.

``PostgresWriteAdapter`` holds everything the psql destinations have in common (lazy
pool + migrations, the two INSERTs, keeping only the newest ratings); the concrete
adapters that use it live in their own files and differ only in where they get their
connection:

- ``write_to_app_be_psql.py`` -> ``AppBePostgresWriteAdapter`` (RateXp's own database).
- ``write_to_custom_psql.py`` -> ``CustomPostgresWriteAdapter`` (an adopter's own database).

The pool and migrations are built lazily on first write, so a database that is
briefly unreachable at boot doesn't disable the adapter - the next write retries.
"""

from __future__ import annotations

import json

from api.record_schemas import Feedback, Transcript

# Everything older than the Nth newest rating goes, ratings and conversations alike. core
# stamps each record as it arrives and a hook posts a rating before its conversation, so a
# kept rating's conversation is never older than the cutoff. Ratings tied with the cutoff
# all stay.
_DELETE_OLDER_THAN_NTH_NEWEST_RATING = """
    WITH cutoff AS (
        SELECT created_at FROM feedback ORDER BY created_at DESC OFFSET %(skip)s LIMIT 1
    ), old_ratings AS (
        DELETE FROM feedback WHERE created_at < (SELECT created_at FROM cutoff)
    )
    DELETE FROM transcript WHERE created_at < (SELECT created_at FROM cutoff)
"""


class PostgresWriteAdapter:
    def __init__(self, name: str, *, dsn: str, auth: str, keep_newest: int | None = None) -> None:
        self.name = name
        self._dsn = dsn
        self._auth = auth
        self._keep_newest = keep_newest
        self._pool = None  # opened lazily so a boot-time DB hiccup isn't fatal

    def _ensure_pool(self, *, migrate: bool = True):
        if self._pool is None:
            from modules.write.connect_to_postgres import make_pool
            from modules.write.schema.apply_migrations import apply_migrations

            if migrate:
                apply_migrations(dsn=self._dsn, auth=self._auth)
            self._pool = make_pool(dsn=self._dsn, auth=self._auth)
        return self._pool

    def write_feedback(self, record: Feedback) -> None:
        with self._ensure_pool().connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO feedback
                  (created_at, session_id, skill_name, agent, eval_name, score, comment, request_id,
                   labels)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (request_id) WHERE request_id IS NOT NULL DO NOTHING
                """,
                (
                    record.created_at,
                    record.session_id,
                    record.skill_name,
                    record.agent,
                    record.eval_name,
                    record.score,
                    record.comment,
                    record.request_id,
                    json.dumps(record.labels),
                ),
            )

    def write_transcript(self, record: Transcript) -> None:
        with self._ensure_pool().connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO transcript
                  (created_at, session_id, skill_name, agent, schema_version, atif, request_id,
                   labels)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
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
                    json.dumps(record.labels),
                ),
            )

    def delete_old_ratings(self) -> None:
        if self._keep_newest is None:
            return
        # Only the retention Function deletes, and its role may only SELECT and DELETE
        # (infra/grant-db-access.sql), so it never runs the migrations; core's writes do.
        with self._ensure_pool(migrate=False).connection() as conn, conn.cursor() as cur:
            cur.execute(_DELETE_OLDER_THAN_NTH_NEWEST_RATING, {"skip": self._keep_newest - 1})

    def close(self) -> None:
        if self._pool is not None:
            self._pool.close()
            self._pool = None
