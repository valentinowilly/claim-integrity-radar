"""Versioned PostgreSQL schema migrations (``NNNN_name.sql`` in this package).

Applied only by ``python -m scripts.db_migrate``; the application checks the version at
startup but never changes the schema itself. Each migration runs in its own transaction
and is recorded with its SHA-256 in ``schema_migrations``; an applied migration whose file
changed afterwards is refused instead of being re-run. Migrations are additive: none
drops tables or data.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from pathlib import Path

from app.db import DatabaseConfigurationError, PostgresDatabase

MIGRATIONS_DIRECTORY = Path(__file__).resolve().parent
_LOCK_KEY = 0x43_49_52_4D  # "CIRM": one migrator at a time


def migration_files() -> list[tuple[str, str, str]]:
    """(version, sql, sha256) in order."""
    files = sorted(MIGRATIONS_DIRECTORY.glob("[0-9][0-9][0-9][0-9]_*.sql"))
    return [(path.stem, path.read_text(encoding="utf-8"), hashlib.sha256(path.read_bytes()).hexdigest())
            for path in files]


def latest_version() -> str:
    return migration_files()[-1][0]


def _ensure_table(connection) -> None:
    connection.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations (version TEXT PRIMARY KEY, sha256 TEXT NOT NULL, "
        "applied_at TEXT NOT NULL)")


def applied_versions(database: PostgresDatabase) -> dict[str, str]:
    connection = database.connect()
    try:
        if not connection.table_exists("schema_migrations"):
            return {}
        return {row[0]: row[1] for row in connection.execute("SELECT version, sha256 FROM schema_migrations")}
    finally:
        connection.close()


def schema_status(database: PostgresDatabase) -> dict:
    """Current and expected version; ``ok`` only when every migration is applied unchanged."""
    applied = applied_versions(database)
    files = migration_files()
    pending = [version for version, _sql, _sha in files if version not in applied]
    changed = [version for version, _sql, sha in files if version in applied and applied[version] != sha]
    return {"ok": not pending and not changed, "expected": files[-1][0], "pending": pending, "changed": changed,
            "applied": sorted(applied)}


def upgrade(database: PostgresDatabase) -> list[str]:
    """Apply pending migrations in order; returns the versions applied now."""
    applied_now: list[str] = []
    connection = database.connect()
    try:
        connection.lock(_LOCK_KEY)
        _ensure_table(connection)
        applied = {row[0]: row[1] for row in connection.execute("SELECT version, sha256 FROM schema_migrations")}
        connection.commit()
        for version, sql, sha in migration_files():
            if version in applied:
                if applied[version] != sha:
                    raise DatabaseConfigurationError(
                        f"Migrasi {version} sudah diterapkan dengan isi berbeda; jangan mengubah migrasi yang sudah dipakai.")
                continue
            connection.lock(_LOCK_KEY)
            # Whole file in one transaction: it applies completely or not at all.
            connection._connection.execute(sql)
            connection.execute("INSERT INTO schema_migrations(version, sha256, applied_at) VALUES (?,?,?)",
                               (version, sha, datetime.now(timezone.utc).isoformat()))
            connection.commit()
            applied_now.append(version)
        return applied_now
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()
