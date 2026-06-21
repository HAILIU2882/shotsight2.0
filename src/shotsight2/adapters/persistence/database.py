"""SQLite connection, migration, and transaction management."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


class MigrationError(RuntimeError):
    """Raised when migration files are missing or inconsistent."""


class SQLiteDatabase:
    """Create configured SQLite connections and own schema upgrades.

    Each operation receives a fresh connection. SQLite WAL mode and a busy
    timeout allow progress readers to coexist with short worker writes.
    """

    def __init__(
        self,
        path: Path,
        *,
        migrations_dir: Path | None = None,
        busy_timeout_ms: int = 5_000,
    ) -> None:
        """Configure a database path without opening it."""
        self.path = path
        self.migrations_dir = migrations_dir or Path(__file__).resolve().parents[2] / "migrations"
        self.busy_timeout_ms = busy_timeout_ms

    def connect(self) -> sqlite3.Connection:
        """Open one internal connection with ShotSight safety conventions."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, isolation_level=None, timeout=self.busy_timeout_ms / 1_000)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(f"PRAGMA busy_timeout = {self.busy_timeout_ms:d}")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
        return connection

    @contextmanager
    def read(self) -> Iterator[sqlite3.Connection]:
        """Yield a configured read connection and always close it."""
        connection = self.connect()
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Yield an immediate write transaction with automatic rollback."""
        connection = self.connect()
        connection.execute("BEGIN IMMEDIATE")
        try:
            yield connection
        except BaseException:
            connection.rollback()
            raise
        else:
            connection.commit()
        finally:
            connection.close()

    def migrate(self) -> int:
        """Apply ordered SQL migrations and return the resulting schema version."""
        migration_files = sorted(self.migrations_dir.glob("[0-9][0-9][0-9]_*.sql"))
        if not migration_files:
            raise MigrationError(f"No migrations found in {self.migrations_dir}")

        with self.connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    applied_at TEXT NOT NULL
                )
                """
            )
            applied = {
                int(row["version"]) for row in connection.execute("SELECT version FROM schema_migrations").fetchall()
            }
            for migration_file in migration_files:
                try:
                    version = int(migration_file.name.split("_", maxsplit=1)[0])
                except ValueError as error:
                    raise MigrationError(f"Invalid migration name: {migration_file.name}") from error
                if version in applied:
                    continue
                sql = migration_file.read_text(encoding="utf-8")
                name_literal = migration_file.name.replace("'", "''")
                connection.executescript(
                    "BEGIN IMMEDIATE;\n"
                    f"{sql}\n"
                    "INSERT INTO schema_migrations(version, name, applied_at) "
                    f"VALUES ({version:d}, '{name_literal}', CURRENT_TIMESTAMP);\n"
                    "COMMIT;"
                )
                applied.add(version)
            return max(applied, default=0)

    def schema_version(self) -> int:
        """Return the latest applied migration, or zero for an empty database."""
        with self.read() as connection:
            exists = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'schema_migrations'"
            ).fetchone()
            if exists is None:
                return 0
            row = connection.execute("SELECT COALESCE(MAX(version), 0) AS version FROM schema_migrations").fetchone()
            return 0 if row is None else int(row["version"])
