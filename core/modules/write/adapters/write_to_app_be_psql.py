"""app_be_psql - RateXp's own PostgreSQL, the database the live dashboard reads.

Uses core's process-wide connection (``DATABASE_URL`` / ``RATEXP_DB_AUTH``). See
write_to_postgres.py for the shared write logic.
"""

from __future__ import annotations

from modules.write.adapters.write_to_postgres import PostgresWriteAdapter


class AppBePostgresWriteAdapter(PostgresWriteAdapter):
    def __init__(self) -> None:
        from modules.write.connect_to_postgres import DATABASE_URL, DB_AUTH

        super().__init__("app_be_psql", dsn=DATABASE_URL, auth=DB_AUTH)
