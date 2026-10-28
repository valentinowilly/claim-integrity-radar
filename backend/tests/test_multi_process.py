"""Several API processes on one database: one holder of the scheduler locks, one shared rate limit."""

import pytest

from app import db
from app.security.rate_limit import DatabaseRateLimiter, RateLimiter, Rule, build_rate_limiter
from tests.db_helpers import on_postgres

RULES = {"login_failures": Rule(3, 900)}


def test_without_postgres_the_cluster_lock_is_always_granted(monkeypatch):
    monkeypatch.delenv("CIR_DATABASE_URL", raising=False)
    with db.cluster_lock("inbox-pull") as first, db.cluster_lock("inbox-pull") as second:
        assert first and second  # one process per SQLite file: nothing to coordinate
    assert isinstance(build_rate_limiter(RULES), RateLimiter)


@pytest.mark.postgres
def test_the_cluster_lock_has_one_holder_at_a_time():
    assert on_postgres()
    with db.cluster_lock("inbox-pull") as first:
        assert first
        with db.cluster_lock("inbox-pull") as second:  # another process asking now
            assert not second
        with db.cluster_lock("retention-sweep") as other:  # a different lock is free
            assert other
    with db.cluster_lock("inbox-pull") as again:  # released on exit
        assert again


@pytest.mark.postgres
def test_rate_limits_are_shared_between_processes_on_postgres():
    database = db.configured_database()
    clock = [1_000_000.0]
    first = DatabaseRateLimiter(RULES, database, clock=lambda: clock[0])   # API process 1
    second = DatabaseRateLimiter(RULES, database, clock=lambda: clock[0])  # API process 2
    assert isinstance(build_rate_limiter(RULES), DatabaseRateLimiter)
    assert first.hit("login_failures", "user-a") is None
    assert second.hit("login_failures", "user-a") is None
    assert first.hit("login_failures", "user-a") is None
    delay = second.hit("login_failures", "user-a")  # the fourth attempt, wherever it arrives
    assert delay is not None and 1 <= delay <= 900
    assert first.hit("login_failures", "user-b") is None  # other keys are unaffected
    clock[0] += 901  # the window passes
    assert second.hit("login_failures", "user-a") is None
    first.reset("login_failures", "user-a")
    assert first.retry_after("login_failures", "user-a") is None
    connection = database.connect()
    try:  # only digests are stored
        stored = [row[0] for row in connection.execute("SELECT key_digest FROM rate_limit_hits").fetchall()]
    finally:
        connection.close()
    assert stored and all(len(item) == 64 and "user" not in item for item in stored)
