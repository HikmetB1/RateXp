"""app_be_psql - read RateXp's own database (the dashboard's DATABASE_URL), with SQL.

See read_from_postgres.py for the shared read logic.
"""

from __future__ import annotations

from modules.read.adapters.read_from_postgres import PostgresReadAdapter
from modules.read.connect_to_postgres import DATABASE_URL, DB_AUTH


class AppBePostgresReadAdapter(PostgresReadAdapter):
    def __init__(self) -> None:
        super().__init__("app_be_psql", dsn=DATABASE_URL, auth=DB_AUTH)
