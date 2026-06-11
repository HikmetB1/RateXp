"""Writes feedback and transcripts to PostgreSQL.

core is the only writer; the dashboard reads the same tables. Schema is managed
by migrate.py. The server holds one FeedbackStore (the pool) for its lifetime.
"""

from __future__ import annotations

import json

from migrate import apply_migrations
from models import Feedback, Transcript


class FeedbackStore:
    def __init__(self) -> None:
        apply_migrations()
        from db import make_pool

        self.pool = make_pool()

    def append(self, record: Feedback) -> None:
        with self.pool.connection() as conn, conn.cursor() as cur:
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

    def append_transcript(self, record: Transcript) -> None:
        with self.pool.connection() as conn, conn.cursor() as cur:
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
        self.pool.close()
