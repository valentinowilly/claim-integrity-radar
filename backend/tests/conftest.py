"""Test-wide database selection.

By default every test uses its own temporary SQLite files (as before). With
``CIR_TEST_DATABASE_URL`` set to a PostgreSQL database whose name ends in ``_test``, every
test instead runs against that server in a fresh schema, migrated to the current version
and dropped afterwards, so the whole suite exercises the PostgreSQL path. The guard on the
database name keeps tests away from development and production databases. Tests that
inspect SQLite files directly are marked ``sqlite_storage`` and skipped in that mode;
``test_postgres_storage.py`` covers the same behaviour on PostgreSQL.
"""

from __future__ import annotations

import os
from urllib.parse import urlparse
from uuid import uuid4

import pytest

TEST_URL_VARIABLE = "CIR_TEST_DATABASE_URL"


def postgres_test_url() -> str | None:
    url = os.environ.get(TEST_URL_VARIABLE, "").strip()
    if not url:
        return None
    database = urlparse(url).path.lstrip("/")
    if not database.endswith("_test"):
        raise pytest.UsageError(f"{TEST_URL_VARIABLE} must name a database ending in _test (refusing to touch others).")
    return url


def pytest_configure(config):
    config.addinivalue_line("markers", "sqlite_storage: inspects SQLite files directly; skipped on PostgreSQL")
    config.addinivalue_line("markers", "postgres: needs a PostgreSQL test database (CIR_TEST_DATABASE_URL)")


def pytest_collection_modifyitems(config, items):
    url = postgres_test_url()
    for item in items:
        if url and "sqlite_storage" in item.keywords:
            item.add_marker(pytest.mark.skip(reason="inspects SQLite files; PostgreSQL run covers this elsewhere"))
        if not url and "postgres" in item.keywords:
            item.add_marker(pytest.mark.skip(reason=f"{TEST_URL_VARIABLE} not set: no PostgreSQL test database"))


@pytest.fixture(autouse=True)
def operational_database():
    """Fresh PostgreSQL schema per test when a PostgreSQL test database is configured.

    The environment is set directly (not through ``monkeypatch``) so a test calling
    ``monkeypatch.undo()`` cannot silently switch the application back to SQLite.
    """
    url = postgres_test_url()
    saved = {name: os.environ.get(name) for name in ("CIR_DATABASE_URL", "CIR_DATABASE_SCHEMA")}
    if url is None:
        os.environ.pop("CIR_DATABASE_URL", None)
        try:
            yield None
        finally:
            _restore(saved)
        return
    import psycopg

    from app import db
    from app.db_migrations import upgrade

    schema = f"t_{uuid4().hex[:20]}"
    with psycopg.connect(url, autocommit=True) as connection:
        connection.execute(f'CREATE SCHEMA "{schema}"')
    os.environ["CIR_DATABASE_URL"] = url
    os.environ["CIR_DATABASE_SCHEMA"] = schema
    try:
        upgrade(db.configured_database())
        yield schema
    finally:
        db.close_databases()
        _restore(saved)
        with psycopg.connect(url, autocommit=True) as connection:
            connection.execute(f'DROP SCHEMA "{schema}" CASCADE')


def _restore(saved: dict) -> None:
    for name, value in saved.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value
