"""custom_psql - an adopter's own PostgreSQL.

The connection string is read from the env var named in config (``dsn_env``), so
the secret never lives in config.yaml. See write_to_postgres.py for the shared write logic.
"""

from __future__ import annotations

import os

from modules.write.adapters.write_to_postgres import PostgresWriteAdapter


class CustomPostgresWriteAdapter(PostgresWriteAdapter):
    def __init__(self, dsn_env: str) -> None:
        dsn = os.environ.get(dsn_env, "").strip()
        if not dsn:
            raise RuntimeError(f"custom_psql is enabled but {dsn_env} is unset")
        super().__init__("custom_psql", dsn=dsn, auth="password")
