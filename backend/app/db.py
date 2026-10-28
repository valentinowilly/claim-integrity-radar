"""Operational database selection and a small connection layer for SQLite and PostgreSQL.

One setting decides where all operational state lives. When ``CIR_DATABASE_URL`` is set,
every store (auth, reviews, batches, runs, run reviews, source validations and jobs) uses
that single PostgreSQL database and the per-store SQLite paths are ignored, so there are
never two operational databases receiving writes. When it is unset, the stores keep their
SQLite files (local development, tests, and the source side of a migration).

The stores are written against the ``sqlite3`` connection API. ``PostgresConnection``
offers the same small surface (``execute``/``executemany``/``commit``/``rollback``/``close``,
rows readable by index and by column name) and translates the few SQLite-specific
statements the stores use:

* ``?`` placeholders become ``%s`` (literal ``%`` is escaped);
* ``INSERT OR IGNORE INTO`` becomes ``INSERT INTO ... ON CONFLICT DO NOTHING``;
* ``instr(a, b)`` becomes ``strpos(a, b)``;
* ``BEGIN IMMEDIATE`` (SQLite's database write lock for a read-then-write section) becomes
  ``pg_advisory_xact_lock`` on one application key, which serialises the same sections
  across every worker and is released at commit or rollback.

The PostgreSQL schema is created only by the versioned migrations in ``app/db_migrations``
(``python -m scripts.db_migrate``); the application never creates, drops or resets tables
there. The URL (which may hold a password) is never logged or returned.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from functools import lru_cache
from contextlib import contextmanager
import hashlib
import os
import re
import sqlite3
import threading
from typing import Any, Iterator

DATABASE_URL_VARIABLE = "CIR_DATABASE_URL"
SCHEMA_VARIABLE = "CIR_DATABASE_SCHEMA"
POOL_MAX_VARIABLE = "CIR_DATABASE_POOL_MAX"
POOL_TIMEOUT_VARIABLE = "CIR_DATABASE_POOL_TIMEOUT_SECONDS"
# One advisory lock key for every "BEGIN IMMEDIATE" section (SQLite locked the whole file).
APPLICATION_WRITE_LOCK = 0x43_49_52_57  # "CIRW"
VALIDATION_JOB_LOCK = 0x43_49_52_56     # "CIRV"
_SCHEMA_NAME = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")

try:  # psycopg is only needed when PostgreSQL is configured.
    import psycopg
    from psycopg import errors as _pg_errors
    DatabaseError: tuple[type[BaseException], ...] = (sqlite3.Error, psycopg.Error)
    UndefinedTable: tuple[type[BaseException], ...] = (sqlite3.OperationalError, _pg_errors.UndefinedTable)
except ImportError:  # pragma: no cover - SQLite-only installations
    psycopg = None  # type: ignore[assignment]
    DatabaseError = (sqlite3.Error,)
    UndefinedTable = (sqlite3.OperationalError,)


class DatabaseConfigurationError(Exception):
    """The configured database cannot be used (message never contains the URL)."""


def is_missing_table(error: BaseException) -> bool:
    """True for "table does not exist" on either backend."""
    if isinstance(error, sqlite3.OperationalError):
        return "no such table" in str(error).lower()
    return psycopg is not None and isinstance(error, _pg_errors.UndefinedTable)


class Row(tuple):
    """Result row readable by position and by column name, like ``sqlite3.Row``."""

    def __new__(cls, values: Sequence[Any], index: dict[str, int]):
        row = super().__new__(cls, values)
        row._index = index
        return row

    def __getitem__(self, key):  # type: ignore[override]
        if isinstance(key, str):
            return tuple.__getitem__(self, self._index[key])
        return tuple.__getitem__(self, key)

    def keys(self) -> list[str]:
        return list(self._index)


def _row_factory(cursor):
    description = cursor.description or []
    index = {column.name: position for position, column in enumerate(description)}
    return lambda values: Row(values, index)


@lru_cache(maxsize=512)
def translate(sql: str) -> str:
    """SQLite-dialect statement used by the stores -> PostgreSQL statement."""
    text = sql.strip()
    ignore = bool(re.match(r"(?is)^INSERT\s+OR\s+IGNORE\s+INTO\b", text))
    if ignore:
        text = re.sub(r"(?is)^INSERT\s+OR\s+IGNORE\s+INTO\b", "INSERT INTO", text)
    out, quoted = [], False
    for char in text:
        if char == "'":
            quoted = not quoted
            out.append(char)
        elif quoted:
            out.append("%%" if char == "%" else char)
        elif char == "?":
            out.append("%s")
        elif char == "%":
            out.append("%%")
        else:
            out.append(char)
    text = "".join(out)
    text = re.sub(r"(?i)\binstr\(", "strpos(", text)
    if ignore:
        text += " ON CONFLICT DO NOTHING"
    return text


class PostgresConnection:
    """sqlite3-like connection over a pooled psycopg connection (one transaction until commit)."""

    backend = "postgresql"

    def __init__(self, database: "PostgresDatabase", connection):
        self._database = database
        self._connection = connection
        self.cache_key = database.cache_key

    def execute(self, sql: str, params: Sequence[Any] | None = None):
        if re.match(r"(?i)^\s*BEGIN\s+IMMEDIATE\s*$", sql):
            return self.lock(APPLICATION_WRITE_LOCK)
        cursor = self._connection.cursor()
        cursor.execute(translate(sql), tuple(params or ()))
        return cursor

    def executemany(self, sql: str, seq_of_params: Iterable[Sequence[Any]]):
        cursor = self._connection.cursor()
        cursor.executemany(translate(sql), [tuple(params) for params in seq_of_params])
        return cursor

    def lock(self, key: int):
        """Transaction-scoped exclusive lock shared by every worker on this database."""
        cursor = self._connection.cursor()
        cursor.execute("SELECT pg_advisory_xact_lock(%s)", (key,))
        return cursor

    def table_exists(self, name: str) -> bool:
        return self._connection.execute("SELECT to_regclass(%s) IS NOT NULL", (name,)).fetchone()[0]

    # ``with connection:`` commits or rolls back without closing, like sqlite3.Connection.
    def __enter__(self) -> "PostgresConnection":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        if exc_type is None:
            self.commit()
        else:
            self.rollback()

    def commit(self) -> None:
        self._connection.commit()

    def rollback(self) -> None:
        self._connection.rollback()

    def close(self) -> None:
        connection, self._connection = self._connection, None
        if connection is not None:
            self._database.release(connection)


@dataclass(frozen=True)
class _PoolKey:
    url: str
    schema: str | None


class PostgresDatabase:
    """Connection pool for the configured database; the URL is kept private."""

    backend = "postgresql"

    def __init__(self, url: str, schema: str | None = None):
        if psycopg is None:
            raise DatabaseConfigurationError("PostgreSQL dikonfigurasi tetapi driver psycopg tidak terpasang.")
        if schema is not None and not _SCHEMA_NAME.fullmatch(schema):
            raise DatabaseConfigurationError(f"{SCHEMA_VARIABLE} tidak valid.")
        from psycopg_pool import ConnectionPool

        self.schema = schema
        # Identifies the database for caches without exposing credentials.
        self.cache_key = "pg:" + hashlib.sha256(f"{url}|{schema}".encode()).hexdigest()[:16]
        max_size = int(os.environ.get(POOL_MAX_VARIABLE, "10"))
        self._timeout = float(os.environ.get(POOL_TIMEOUT_VARIABLE, "10"))

        def configure(connection) -> None:
            connection.row_factory = _row_factory
            if schema:
                connection.execute(f'SET search_path TO "{schema}"')
                connection.commit()

        self._pool = ConnectionPool(url, min_size=1, max_size=max(1, max_size), configure=configure,
                                    open=False, timeout=self._timeout, name="cir")
        self._pool.open(wait=False)

    def connect(self) -> PostgresConnection:
        """A connection from the pool; raises psycopg errors (e.g. PoolTimeout) when unavailable."""
        return PostgresConnection(self, self._pool.getconn(timeout=self._timeout))

    def release(self, connection) -> None:
        if connection.info.transaction_status != psycopg.pq.TransactionStatus.IDLE:
            connection.rollback()
        self._pool.putconn(connection)

    def close(self) -> None:
        self._pool.close()


_databases: dict[_PoolKey, PostgresDatabase] = {}
_databases_lock = threading.Lock()


def configured_database() -> PostgresDatabase | None:
    """The PostgreSQL database named by ``CIR_DATABASE_URL`` (shared pool), or None for SQLite."""
    url = os.environ.get(DATABASE_URL_VARIABLE, "").strip()
    if not url:
        return None
    if not url.startswith(("postgresql://", "postgres://")):
        raise DatabaseConfigurationError(f"{DATABASE_URL_VARIABLE} harus berupa URL postgresql://.")
    key = _PoolKey(url, os.environ.get(SCHEMA_VARIABLE, "").strip() or None)
    with _databases_lock:
        if key not in _databases:
            _databases[key] = PostgresDatabase(key.url, key.schema)
        return _databases[key]


def close_databases() -> None:
    with _databases_lock:
        for database in _databases.values():
            database.close()
        _databases.clear()


def sqlite_cache_key(connection: sqlite3.Connection) -> str:
    return "sqlite:" + str(connection.execute("PRAGMA database_list").fetchone()[2])


def cache_key(connection: Any) -> str:
    return getattr(connection, "cache_key", None) or sqlite_cache_key(connection)


def table_exists(connection: Any, name: str) -> bool:
    if isinstance(connection, PostgresConnection):
        return connection.table_exists(name)
    return connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def write_lock(connection: Any, key: int = APPLICATION_WRITE_LOCK) -> None:
    """Exclusive section until commit: BEGIN IMMEDIATE on SQLite, an advisory lock on PostgreSQL."""
    if isinstance(connection, PostgresConnection):
        connection.lock(key)
    else:
        connection.execute("BEGIN IMMEDIATE")


def is_postgres(connection: Any) -> bool:
    return isinstance(connection, PostgresConnection)


def connect_operational(path: str | os.PathLike, timeout: float):
    """Connection for a store: the configured PostgreSQL database, else the store's SQLite file.

    A SQLite connection gets ``sqlite3.Row`` rows and foreign keys on, as the stores expect;
    its schema is still created by the store. PostgreSQL needs the migrated schema.
    """
    database = configured_database()
    if database is not None:
        return database.connect()
    from pathlib import Path

    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(target, timeout=timeout)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def sqlite_script(connection: Any, script: str) -> None:
    """Run a store's SQLite schema script; PostgreSQL gets its schema from the migrations."""
    if not is_postgres(connection):
        connection.executescript(script)


@contextmanager
def cluster_lock(name: str) -> Iterator[bool]:
    """Hold a named lock shared by every API process on the configured PostgreSQL database.

    Yields True when this caller holds it and False when another process does (the caller then skips its
    turn). Without PostgreSQL there is one process per SQLite file, so the lock is always granted.
    """
    database = configured_database()
    if database is None:
        yield True
        return
    key = int.from_bytes(hashlib.sha256(f"cir-cluster:{name}".encode()).digest()[:8], "big", signed=True)
    connection = database.connect()
    held = False
    try:
        held = bool(connection.execute("SELECT pg_try_advisory_lock(?)", (key,)).fetchone()[0])
        connection.commit()  # a session lock outlives the transaction
        yield held
    finally:
        try:
            if held:
                connection.execute("SELECT pg_advisory_unlock(?)", (key,))
                connection.commit()
        finally:
            connection.close()

