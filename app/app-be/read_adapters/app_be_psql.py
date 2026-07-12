"""app_be_psql - read RateXp's own database (the dashboard's DATABASE_URL), with SQL.

See utils/postgres.py for the shared read logic.
"""

from __future__ import annotations

from .utils.postgres import PostgresReadAdapter


class AppBePostgresReadAdapter(PostgresReadAdapter):
    def __init__(self) -> None:
        from db import DATABASE_URL, DB_AUTH

        super().__init__("app_be_psql", dsn=DATABASE_URL, auth=DB_AUTH)
