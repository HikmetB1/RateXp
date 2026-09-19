"""Applying the numbered .sql files that sit beside apply_migrations.py.

These run against every PostgreSQL core writes to, including an adopter's own,
on the first write of each process. Applying one twice, or out of order, is a
data problem rather than a crash, so it is worth pinning down here.
"""

from __future__ import annotations

from modules.write.schema import apply_migrations as migrations


class _FakeCursor:
    def __init__(self, log: list, already_applied: set[int]):
        self._log = log
        self._already_applied = already_applied
        self._rows: list[tuple[int]] = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, sql, params=None):
        self._log.append((sql, params))
        if "SELECT version FROM schema_version" in sql:
            self._rows = [(v,) for v in sorted(self._already_applied)]

    def fetchall(self):
        return self._rows


class _FakeConnection:
    def __init__(self, log: list, already_applied: set[int]):
        self._log = log
        self._already_applied = already_applied
        self.commits = 0

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def cursor(self):
        return _FakeCursor(self._log, self._already_applied)

    def commit(self):
        self.commits += 1


def _run(monkeypatch, tmp_path, files: dict[str, str], already_applied=()) -> list:
    """Apply `files` against a fake database and return the (sql, params) log."""
    for name, body in files.items():
        (tmp_path / name).write_text(body, encoding="utf-8")
    log: list = []
    monkeypatch.setattr(migrations, "_MIGRATIONS_DIR", tmp_path)
    monkeypatch.setattr(
        migrations, "connect", lambda *a, **kw: _FakeConnection(log, set(already_applied))
    )
    migrations.apply_migrations()
    return log


def _recorded_versions(log: list) -> list[int]:
    return [params[0] for sql, params in log if "INSERT INTO schema_version" in sql]


def _executed_bodies(log: list) -> list[str]:
    return [sql for sql, params in log if sql.startswith("-- ")]


def test_the_version_table_is_created_before_it_is_read():
    # Nothing has ever been applied on a fresh database, so the first SELECT
    # would fail without this.
    assert "CREATE TABLE IF NOT EXISTS schema_version" in migrations._SCHEMA_VERSION_DDL


def test_every_migration_runs_on_a_fresh_database(monkeypatch, tmp_path):
    log = _run(
        monkeypatch,
        tmp_path,
        {
            "001_create_feedback_table.sql": "-- one",
            "002_create_transcript_table.sql": "-- two",
        },
    )
    assert _executed_bodies(log) == ["-- one", "-- two"]
    assert _recorded_versions(log) == [1, 2]


def test_an_already_recorded_migration_is_not_run_again(monkeypatch, tmp_path):
    log = _run(
        monkeypatch,
        tmp_path,
        {
            "001_create_feedback_table.sql": "-- one",
            "002_create_transcript_table.sql": "-- two",
            "003_add_index.sql": "-- three",
        },
        already_applied={1, 2},
    )
    assert _executed_bodies(log) == ["-- three"]
    assert _recorded_versions(log) == [3]


def test_nothing_runs_when_the_database_is_already_current(monkeypatch, tmp_path):
    # This is the common case: every write after the first one in a process.
    log = _run(
        monkeypatch,
        tmp_path,
        {"001_create_feedback_table.sql": "-- one"},
        already_applied={1},
    )
    assert _executed_bodies(log) == []
    assert _recorded_versions(log) == []


def test_migrations_run_lowest_number_first(monkeypatch, tmp_path):
    # Written out of order on purpose: 002 may depend on the table 001 creates.
    log = _run(
        monkeypatch,
        tmp_path,
        {
            "003_add_index.sql": "-- three",
            "001_create_feedback_table.sql": "-- one",
            "002_create_transcript_table.sql": "-- two",
        },
    )
    assert _executed_bodies(log) == ["-- one", "-- two", "-- three"]


def test_a_sql_file_with_no_version_number_is_ignored(monkeypatch, tmp_path):
    # Scratch files and hand-written queries land in this folder. An unnumbered
    # one cannot be recorded as applied, so running it would repeat it forever.
    log = _run(
        monkeypatch,
        tmp_path,
        {"001_create_feedback_table.sql": "-- one", "scratch.sql": "-- scratch"},
    )
    assert _executed_bodies(log) == ["-- one"]
