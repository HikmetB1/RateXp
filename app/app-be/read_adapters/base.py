"""The interface every read adapter implements.

A read adapter is the one source the dashboard reads from. It mirrors the write
side's 2×2 destinations, but is single-select (exactly one enabled, chosen by
config.yaml ``read_adapters`` / ``RATEXP_READ_ADAPTER``). Each concrete source lives
in its own file:

- ``app_be_psql.py`` / ``custom_psql.py`` - PostgreSQL, filter box speaks SQL.
- ``app_be_dynatrace.py`` / ``custom_dynatrace.py`` - Dynatrace, filter box speaks DQL.

The two shared bases they build on live in ``utils/`` (``utils/postgres.py`` ->
``PostgresReadAdapter``, ``utils/dynatrace.py`` -> ``DynatraceReadAdapter``). The
adapter owns the queries; server.py keeps the HTTP shaping/formatting.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class ReadAdapter(Protocol):
    name: str
    # The filter box's query language for this source, shown in the UI ("SQL" / "DQL").
    query_language: str
    # A one-line example query in that language (the box's placeholder).
    query_example: str

    def select_feedback(self, limit: int) -> list[tuple]:
        """Newest `limit` feedback rows (created_at, session_id, skill_name, agent, score, comment, request_id)."""
        ...

    def select_transcript(self, limit: int) -> list[tuple]:
        """Newest `limit` transcript rows (created_at, session_id, skill_name, agent, schema_version, atif, request_id)."""
        ...

    def select_transcripts_by_ids(self, request_ids: list, session_ids: list) -> list[tuple]:
        """Transcript rows matching any of the given request_id / session_id keys."""
        ...

    def select_top_skills(self, limit: int) -> list[dict]:
        """Most-rated skills with good/bad tallies, as dicts."""
        ...

    def run_query(self, query: str, max_rows: int, timeout_ms: int) -> tuple[list[str], list[tuple]]:
        """Validate + cap + run a read-only query in this source's language (SQL or DQL).

        Returns (columns, rows). Raises ValueError for a rejected/invalid query, which
        the /query endpoint maps to HTTP 400.
        """
        ...

    def change_signature(self) -> tuple:
        """A cheap fingerprint of the tables so the live feed can skip unchanged data."""
        ...

    def close(self) -> None:
        """Release resources (connection pool)."""
        ...
