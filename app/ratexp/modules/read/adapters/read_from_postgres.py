"""Shared SQL read logic for the PostgreSQL read adapters (app_be_psql, custom_psql).

Reads the feedback/transcript tables, runs the dashboard's SQL filter box (SELECT-only,
validated, capped, read-only) and the Dashboard view's SQL - panels, dropdowns, download
(read-only, timed). The pool is built lazily from the dsn/auth the concrete adapter
supplies (see read_from_app_be_psql.py / read_from_custom_psql.py), so a database that's
briefly unreachable at boot doesn't disable the adapter.
"""

from __future__ import annotations

import re

from load_config import LIST_MAX_LIMIT
from modules.read.connect_to_postgres import make_pool

# Defense-in-depth on top of the read-only transaction; also catches data-modifying CTEs.
_FORBIDDEN_SQL = re.compile(
    r"\b(insert|update|delete|drop|alter|create|truncate|grant|revoke|copy|vacuum|merge|call|do)\b",
    re.IGNORECASE,
)


def _validate_select(sql: str) -> str:
    """Return a cleaned single SELECT statement, or raise ValueError."""
    cleaned = sql.strip().rstrip(";").strip()
    if not cleaned:
        raise ValueError("empty query")
    if ";" in cleaned:
        raise ValueError("only a single statement is allowed")
    if not re.match(r"(?is)^\s*(select|with)\b", cleaned):
        raise ValueError("only SELECT queries are allowed")
    if _FORBIDDEN_SQL.search(cleaned):
        raise ValueError("only read-only SELECT queries are allowed")
    return cleaned


class PostgresReadAdapter:
    query_language = "SQL"
    query_example = "SELECT * FROM feedback WHERE skill_name = '...'"

    def __init__(self, name: str, *, dsn: str, auth: str) -> None:
        self.name = name
        self._dsn = dsn
        self._auth = auth
        self._pool = None  # opened lazily so a boot-time DB hiccup isn't fatal

    def _ensure_pool(self):
        if self._pool is None:
            self._pool = make_pool(self._dsn, self._auth)
        return self._pool

    def select_feedback(self, limit: int) -> list[tuple]:
        with self._ensure_pool().connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT created_at, session_id, skill_name, agent, score, comment, request_id,
                       eval_name
                FROM feedback
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (limit,),
            )
            return cur.fetchall()

    def select_transcript(self, limit: int) -> list[tuple]:
        with self._ensure_pool().connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT created_at, session_id, skill_name, agent, schema_version, atif, request_id
                FROM transcript
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (limit,),
            )
            return cur.fetchall()

    def select_transcripts_by_request_ids(self, request_ids: list) -> list[tuple]:
        if not request_ids:
            return []
        with self._ensure_pool().connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT created_at, session_id, skill_name, agent, schema_version, atif, request_id
                FROM transcript
                WHERE request_id = ANY(%s)
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (request_ids, LIST_MAX_LIMIT),
            )
            return cur.fetchall()

    def select_top_skills(self, limit: int) -> list[dict]:
        with self._ensure_pool().connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT skill_name,
                       COUNT(*) AS total,
                       COUNT(*) FILTER (WHERE score = 1) AS good,
                       COUNT(*) FILTER (WHERE score = 2) AS bad
                FROM feedback
                WHERE skill_name IS NOT NULL
                GROUP BY skill_name
                ORDER BY total DESC, skill_name ASC
                LIMIT %s
                """,
                (limit,),
            )
            rows = cur.fetchall()
        return [{"skill_name": r[0], "total": r[1], "good": r[2], "bad": r[3]} for r in rows]

    def run_query(
        self, query: str, max_rows: int, timeout_ms: int
    ) -> tuple[list[str], list[tuple]]:
        # Validate SELECT-only, wrap in a row-capping subquery, run read-only + timed.
        wrapped = f"SELECT * FROM ({_validate_select(query)}) AS _q LIMIT %s"
        return self._select_read_only(wrapped, (max_rows,), timeout_ms)

    def run_dashboard_sql(
        self, sql: str, params: dict, timeout_ms: int
    ) -> tuple[list[str], list[tuple]]:
        # The SQL is the Dashboard view's - a panel, a dropdown or the download, from
        # core/modules/dashboard/dashboard_for_app.yaml - ours, not a user's, so the filter
        # box's SELECT-only check would only guard against ourselves; the read-only
        # transaction still holds. Named parameters throughout: psycopg refuses to mix them
        # with the positional %s the filter box binds its LIMIT with.
        return self._select_read_only(sql, params, timeout_ms)

    def _select_read_only(self, sql: str, params, timeout_ms: int) -> tuple[list[str], list[tuple]]:
        with self._ensure_pool().connection() as conn, conn.transaction(), conn.cursor() as cur:
            # SET needs a literal, not a bound param; int() keeps the inlining injection-safe.
            cur.execute(f"SET LOCAL statement_timeout = {int(timeout_ms)}")
            cur.execute("SET TRANSACTION READ ONLY")
            cur.execute(sql, params)
            columns = [d.name for d in cur.description] if cur.description else []
            rows = cur.fetchall()
        return columns, rows

    def change_signature(self) -> tuple:
        with self._ensure_pool().connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT count(*), max(created_at) FROM feedback")
            feedback = cur.fetchall()
            cur.execute("SELECT count(*), max(created_at) FROM transcript")
            transcript = cur.fetchall()
        return (str(feedback), str(transcript))

    def close(self) -> None:
        if self._pool is not None:
            self._pool.close()
            self._pool = None
