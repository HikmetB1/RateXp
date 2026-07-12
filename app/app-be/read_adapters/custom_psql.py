"""custom_psql - read an adopter's own PostgreSQL (a DSN other than the dashboard's
own DATABASE_URL), with SQL. The connection string comes from the env var named in
config (``dsn_env``). See utils/postgres.py for the shared read logic.
"""

from __future__ import annotations

import os

from .utils.postgres import PostgresReadAdapter


class CustomPostgresReadAdapter(PostgresReadAdapter):
    def __init__(self, dsn_env: str) -> None:
        dsn = os.environ.get(dsn_env, "").strip()
        if not dsn:
            raise RuntimeError(f"custom_psql read is enabled but {dsn_env} is unset")
        super().__init__("custom_psql", dsn=dsn, auth="password")
