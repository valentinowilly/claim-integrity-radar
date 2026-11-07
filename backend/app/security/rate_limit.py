"""Sliding-window rate limits for authentication and sensitive writes.

With SQLite (one API process) the counters live in memory (``RateLimiter``). With PostgreSQL they live in
the ``rate_limit_hits`` table (``DatabaseRateLimiter``), so every API process and host shares one limit.
Keys are stored as SHA-256 digests (no client address, username or user id in the table).
"""

from __future__ import annotations

import hashlib
import math
import os
import threading
import time
from collections import OrderedDict, deque
from collections.abc import Callable
from dataclasses import dataclass

from fastapi import Depends, Request

from app.api.errors import ApiError
from app.security.auth import Principal
from app.security.dependencies import current_principal


@dataclass(frozen=True)
class Rule:
    limit: int
    window_seconds: int


# Defaults; each rule can be overridden with CIR_RATE_LIMIT_<NAME>="<limit>/<seconds>".
DEFAULT_RULES: dict[str, Rule] = {
    # Every login attempt from one client address.
    "login_ip": Rule(30, 300),
    # Failed logins for one username (counted before the password check runs).
    "login_failures": Rule(5, 900),
    # Authorized audit results recorded by one user.
    "audit_confirmation": Rule(10, 60),
    # Review status and outcome changes by one user.
    "review_write": Rule(60, 60),
    # Clinical-note analyses sent to Claude by one user (cost guard).
    "clinical_ai": Rule(20, 300),
}
MAX_KEYS = 10_000


def _parse_rule(name: str, raw: str) -> Rule:
    try:
        limit_text, window_text = raw.split("/")
        rule = Rule(int(limit_text), int(window_text))
    except ValueError as exc:
        raise ValueError(f"CIR_RATE_LIMIT_{name.upper()} harus berformat <jumlah>/<detik>.") from exc
    if rule.limit < 1 or not 1 <= rule.window_seconds <= 86_400:
        raise ValueError(f"CIR_RATE_LIMIT_{name.upper()} di luar rentang yang diizinkan.")
    return rule


def configured_rules() -> dict[str, Rule] | None:
    """Rules from the environment; None when CIR_RATE_LIMIT_ENABLED=false."""
    enabled = os.environ.get("CIR_RATE_LIMIT_ENABLED", "true").strip().lower()
    if enabled not in {"true", "false"}:
        raise ValueError("CIR_RATE_LIMIT_ENABLED harus true atau false.")
    if enabled == "false":
        return None
    rules = dict(DEFAULT_RULES)
    for name in rules:
        raw = os.environ.get(f"CIR_RATE_LIMIT_{name.upper()}")
        if raw:
            rules[name] = _parse_rule(name, raw)
    return rules


class RateLimiter:
    """Thread-safe sliding-window counters with a bounded number of keys."""

    def __init__(self, rules: dict[str, Rule] | None, clock: Callable[[], float] = time.monotonic,
                 max_keys: int = MAX_KEYS):
        self.rules = rules
        self._clock = clock
        self._max_keys = max_keys
        self._hits: OrderedDict[str, deque[float]] = OrderedDict()
        self._lock = threading.Lock()

    def _window(self, rule_name: str, key: str, now: float) -> tuple[Rule, deque[float]]:
        rule = self.rules[rule_name]
        hits = self._hits.setdefault(f"{rule_name}:{key}", deque())
        while hits and hits[0] <= now - rule.window_seconds:
            hits.popleft()
        return rule, hits

    def retry_after(self, rule_name: str, key: str) -> int | None:
        """Seconds until one more request is allowed, or None when it is allowed now."""
        if self.rules is None:
            return None
        with self._lock:
            now = self._clock()
            rule, hits = self._window(rule_name, key, now)
            if len(hits) < rule.limit:
                return None
            return max(1, math.ceil(hits[0] + rule.window_seconds - now))

    def record(self, rule_name: str, key: str) -> None:
        if self.rules is None:
            return
        with self._lock:
            now = self._clock()
            _, hits = self._window(rule_name, key, now)
            hits.append(now)
            self._hits.move_to_end(f"{rule_name}:{key}")
            while len(self._hits) > self._max_keys:
                self._hits.popitem(last=False)

    def hit(self, rule_name: str, key: str) -> int | None:
        """Record one request unless the limit is reached; return the retry delay when rejected."""
        delay = self.retry_after(rule_name, key)
        if delay is None:
            self.record(rule_name, key)
        return delay

    def reset(self, rule_name: str, key: str) -> None:
        with self._lock:
            self._hits.pop(f"{rule_name}:{key}", None)


def rate_limited_error(retry_after: int) -> ApiError:
    return ApiError(429, "RATE_LIMITED", "Terlalu banyak permintaan. Coba lagi nanti.",
                    {"retry_after_seconds": retry_after}, headers={"Retry-After": str(retry_after)})


def client_key(request: Request) -> str:
    # The direct peer address; behind a trusted proxy, run uvicorn with --proxy-headers.
    return request.client.host if request.client else "unknown"


def username_key(username: str) -> str:
    # Usernames are kept as digests so the counters never hold submitted names.
    return hashlib.sha256(username.strip().lower().encode("utf-8")).hexdigest()


def limiter(request: Request) -> RateLimiter:
    return request.app.state.rate_limiter


def user_rate_limit(rule_name: str) -> Callable:
    """Dependency that limits one authenticated user's requests on a sensitive write route."""
    def guard(request: Request, principal: Principal = Depends(current_principal)) -> None:
        delay = limiter(request).hit(rule_name, principal.user_id)
        if delay is not None:
            raise rate_limited_error(delay)
    return guard


class DatabaseRateLimiter:
    """The same sliding windows, kept in PostgreSQL so all API processes share them."""

    PRUNE_EVERY = 200  # delete hits older than a day every N recorded hits (per process)

    def __init__(self, rules: dict[str, Rule] | None, database, clock: Callable[[], float] = time.time):
        self.rules = rules
        self._database = database
        self._clock = clock
        self._recorded = 0

    @staticmethod
    def _digest(rule_name: str, key: str) -> str:
        return hashlib.sha256(f"{rule_name}:{key}".encode("utf-8")).hexdigest()

    def _delay(self, connection, rule: Rule, digest: str, now: float) -> int | None:
        row = connection.execute(
            "SELECT count(*), min(hit_at) FROM rate_limit_hits WHERE key_digest = ? AND hit_at > ?",
            (digest, now - rule.window_seconds)).fetchone()
        if row[0] < rule.limit:
            return None
        return max(1, math.ceil(row[1] + rule.window_seconds - now))

    def retry_after(self, rule_name: str, key: str) -> int | None:
        if self.rules is None:
            return None
        connection = self._database.connect()
        try:
            return self._delay(connection, self.rules[rule_name], self._digest(rule_name, key), self._clock())
        finally:
            connection.close()

    def _insert(self, connection, digest: str, now: float) -> None:
        connection.execute("INSERT INTO rate_limit_hits(key_digest, hit_at) VALUES (?, ?)", (digest, now))
        self._recorded += 1
        if self._recorded % self.PRUNE_EVERY == 0:
            connection.execute("DELETE FROM rate_limit_hits WHERE hit_at < ?", (now - 86_400,))

    def record(self, rule_name: str, key: str) -> None:
        if self.rules is None:
            return
        connection = self._database.connect()
        try:
            self._insert(connection, self._digest(rule_name, key), self._clock())
            connection.commit()
        finally:
            connection.close()

    def hit(self, rule_name: str, key: str) -> int | None:
        """Check and record in one transaction, serialised per key across processes."""
        if self.rules is None:
            return None
        digest, now = self._digest(rule_name, key), self._clock()
        connection = self._database.connect()
        try:
            connection.lock(int(digest[:15], 16))  # transaction-scoped lock for this key
            delay = self._delay(connection, self.rules[rule_name], digest, now)
            if delay is None:
                self._insert(connection, digest, now)
            connection.commit()
            return delay
        finally:
            connection.close()

    def reset(self, rule_name: str, key: str) -> None:
        connection = self._database.connect()
        try:
            connection.execute("DELETE FROM rate_limit_hits WHERE key_digest = ?", (self._digest(rule_name, key),))
            connection.commit()
        finally:
            connection.close()


def build_rate_limiter(rules: dict[str, Rule] | None):
    """Shared limits on PostgreSQL, in-memory limits on SQLite."""
    from app.db import configured_database

    database = configured_database()
    return DatabaseRateLimiter(rules, database) if database is not None else RateLimiter(rules)

