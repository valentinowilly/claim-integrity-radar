"""SQLite-backed password, account, session, and security-event services.

This is a local synthetic-prototype implementation. Session tokens and CSRF
tokens are only stored as SHA-256 hashes; passwords use salted scrypt hashes.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator
from uuid import uuid4

from app.db import DatabaseError, connect_operational, is_postgres, sqlite_script


SESSION_COOKIE = "cir_session"
CSRF_COOKIE = "cir_csrf"
SESSION_TTL_SECONDS = 8 * 60 * 60
PASSWORD_MIN_LENGTH = 12
PASSWORD_MAX_LENGTH = 1024
USERNAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._@+-]{2,79}$")
ROLES = ("platform_admin", "data_operator", "verifikator", "audit_lead", "demo_tester")

ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    # The local synthetic-demo administrator is intentionally the sole full-workflow
    # role. This does not expand access to real BPJS data or add any route bypass.
    "platform_admin": frozenset({
        "dashboard:read", "analytics:read", "cases:read",
        "batches:read", "batches:write",
        "runs:read", "runs:write", "runs:results:read",
        "review:read", "review:write", "review:manage",
        "users:manage", "security_audit:read",
    }),
    "data_operator": frozenset({"dashboard:read", "analytics:read", "batches:read", "batches:write", "runs:read", "runs:write"}),
    # One shared account for judges and testers of the public demo: every workflow of the administrator, but no
    # account management and no security log, so one tester cannot lock the others out.
    "demo_tester": frozenset({
        "dashboard:read", "analytics:read", "cases:read",
        "batches:read", "batches:write",
        "runs:read", "runs:write", "runs:results:read",
        "review:read", "review:write", "review:manage",
    }),
    # One reviewer role fills every review step (status, outcome, authorized audit result) for the prototype.
    "verifikator": frozenset({"dashboard:read", "analytics:read", "cases:read", "review:read", "review:write", "review:manage", "batches:read", "runs:read", "runs:results:read"}),
    "audit_lead": frozenset({"dashboard:read", "analytics:read", "cases:read", "review:read", "review:write", "review:manage", "batches:read", "runs:read", "runs:results:read"}),
}


class AuthenticationStorageError(Exception):
    """Raised when authentication metadata cannot be safely accessed."""


class AuthenticationError(Exception):
    """Raised for invalid credentials, session, or bootstrap operation."""


@dataclass(frozen=True)
class Principal:
    user_id: str
    username: str
    role: str
    session_id: str
    csrf_hash: str
    expires_at: str

    @property
    def permissions(self) -> frozenset[str]:
        return ROLE_PERMISSIONS[self.role]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def validate_username(username: str) -> str:
    if not isinstance(username, str) or not USERNAME_RE.fullmatch(username):
        raise ValueError("Username harus 3-80 karakter dan hanya berisi karakter yang diizinkan.")
    return username.lower()


def validate_password(password: str) -> None:
    if not isinstance(password, str) or not PASSWORD_MIN_LENGTH <= len(password) <= PASSWORD_MAX_LENGTH:
        raise ValueError(f"Password harus sepanjang {PASSWORD_MIN_LENGTH}-{PASSWORD_MAX_LENGTH} karakter.")
    if "\x00" in password:
        raise ValueError("Password mengandung karakter yang tidak valid.")


def hash_password(password: str, *, allow_local_demo: bool = False) -> str:
    if allow_local_demo:
        if os.environ.get("CIR_ENV", "").strip().lower() != "development":
            raise ValueError("Password demo hanya dapat digunakan pada CIR_ENV=development.")
        if password != "admin123":
            raise ValueError("Password demo lokal tidak sesuai konfigurasi.")
    else:
        validate_password(password)
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return "scrypt$16384$8$1${}${}".format(salt.hex(), digest.hex())


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, n_text, r_text, p_text, salt_text, digest_text = encoded.split("$")
        if algorithm != "scrypt":
            return False
        salt = bytes.fromhex(salt_text)
        expected = bytes.fromhex(digest_text)
        actual = hashlib.scrypt(
            password.encode("utf-8"), salt=salt,
            n=int(n_text), r=int(r_text), p=int(p_text), dklen=len(expected),
        )
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError, MemoryError):
        return False


class AuthStore:
    """Additive SQLite storage; opening it never deletes existing tables."""

    def __init__(self, path: str | Path, session_ttl_seconds: int = SESSION_TTL_SECONDS):
        if session_ttl_seconds < 60:
            raise ValueError("Session TTL minimal 60 detik.")
        self.path = Path(path).expanduser()
        self.session_ttl_seconds = session_ttl_seconds

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection: sqlite3.Connection | None = None
        try:
            connection = connect_operational(self.path, timeout=5)
            sqlite_script(connection, 
                """
                CREATE TABLE IF NOT EXISTS auth_users (
                    user_id TEXT PRIMARY KEY,
                    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS auth_sessions (
                    session_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES auth_users(user_id),
                    token_hash TEXT NOT NULL UNIQUE,
                    csrf_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    revoked_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_auth_sessions_user ON auth_sessions(user_id);
                CREATE TABLE IF NOT EXISTS security_audit_events (
                    event_id TEXT PRIMARY KEY,
                    occurred_at TEXT NOT NULL,
                    actor_user_id TEXT,
                    event_type TEXT NOT NULL,
                    target_type TEXT,
                    target_id TEXT,
                    metadata_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS auth_metadata (
                    metadata_key TEXT PRIMARY KEY,
                    metadata_value TEXT NOT NULL
                );
                """
            )
            yield connection
            connection.commit()
        except (OSError, *DatabaseError) as exc:
            if connection is not None:
                connection.rollback()
            raise AuthenticationStorageError("Penyimpanan autentikasi lokal tidak tersedia.") from exc
        finally:
            if connection is not None:
                connection.close()

    @staticmethod
    def _event(connection: sqlite3.Connection, event_type: str, actor_user_id: str | None = None,
               target_type: str | None = None, target_id: str | None = None,
               metadata: dict | None = None) -> None:
        connection.execute(
            "INSERT INTO security_audit_events VALUES (?, ?, ?, ?, ?, ?, ?)",
            (f"evt_{uuid4().hex}", utc_now().isoformat(), actor_user_id, event_type,
             target_type, target_id, json.dumps(metadata or {}, sort_keys=True)),
        )

    def create_bootstrap_admin(self, username: str, password: str, supplied_secret: str,
                               configured_secret: str | None, *, allow_local_demo_password: bool = False) -> dict:
        if not configured_secret or not supplied_secret or not hmac.compare_digest(supplied_secret, configured_secret):
            raise AuthenticationError("Bootstrap tidak diizinkan.")
        normalized = validate_username(username)
        password_hash = hash_password(password, allow_local_demo=allow_local_demo_password)
        now = utc_now().isoformat()
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            used = connection.execute(
                "SELECT metadata_value FROM auth_metadata WHERE metadata_key = 'admin_bootstrap_used'"
            ).fetchone()
            if used or connection.execute(
                "SELECT 1 FROM auth_users WHERE role = 'platform_admin' LIMIT 1"
            ).fetchone():
                raise AuthenticationError("Bootstrap administrator hanya dapat dilakukan satu kali.")
            user_id = f"usr_{uuid4().hex}"
            connection.execute(
                "INSERT INTO auth_users VALUES (?, ?, ?, 'platform_admin', 1, ?, ?)",
                (user_id, normalized, password_hash, now, now),
            )
            connection.execute(
                "INSERT INTO auth_metadata VALUES ('admin_bootstrap_used', ?)", (now,)
            )
            self._event(connection, "admin_bootstrap_completed", user_id, "user", user_id)
        return {"user_id": user_id, "username": normalized, "role": "platform_admin", "is_active": True}

    def create_user(self, username: str, password: str, role: str, actor_user_id: str) -> dict:
        normalized = validate_username(username)
        validate_password(password)
        if role not in ROLES:
            raise ValueError("Role tidak dikenal.")
        now = utc_now().isoformat()
        user_id = f"usr_{uuid4().hex}"
        password_hash = hash_password(password)
        with self._connection() as connection:
            if connection.execute("SELECT 1 FROM auth_users WHERE username = ?", (normalized,)).fetchone():
                raise AuthenticationError("Username sudah digunakan.")
            connection.execute(
                "INSERT INTO auth_users VALUES (?, ?, ?, ?, 1, ?, ?)",
                (user_id, normalized, password_hash, role, now, now),
            )
            self._event(connection, "user_created", actor_user_id, "user", user_id, {"role": role})
        return {"user_id": user_id, "username": normalized, "role": role, "is_active": True}

    def update_user(self, user_id: str, actor_user_id: str, role: str | None = None,
                    is_active: bool | None = None) -> dict | None:
        if role is not None and role not in ROLES:
            raise ValueError("Role tidak dikenal.")
        if role is None and is_active is None:
            raise ValueError("Perubahan akun kosong.")
        with self._connection() as connection:
            row = connection.execute("SELECT * FROM auth_users WHERE user_id = ?", (user_id,)).fetchone()
            if row is None:
                return None
            next_role = role or row["role"]
            next_active = int(is_active if is_active is not None else row["is_active"])
            if row["role"] == "platform_admin" and row["is_active"] and (
                next_role != "platform_admin" or not next_active
            ):
                remaining_admins = connection.execute(
                    "SELECT COUNT(*) FROM auth_users WHERE role = 'platform_admin' AND is_active = 1 AND user_id != ?",
                    (user_id,),
                ).fetchone()[0]
                if not remaining_admins:
                    raise AuthenticationError("Tidak dapat menonaktifkan administrator aktif terakhir.")
            now = utc_now().isoformat()
            connection.execute(
                "UPDATE auth_users SET role = ?, is_active = ?, updated_at = ? WHERE user_id = ?",
                (next_role, next_active, now, user_id),
            )
            if not next_active:
                active_sessions = connection.execute(
                    "SELECT session_id FROM auth_sessions WHERE user_id = ? AND revoked_at IS NULL",
                    (user_id,),
                ).fetchall()
                connection.execute(
                    "UPDATE auth_sessions SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL",
                    (now, user_id),
                )
                for session in active_sessions:
                    self._event(connection, "session_revoked_inactive_account", actor_user_id,
                                "session", session["session_id"])
            self._event(connection, "user_updated", actor_user_id, "user", user_id,
                        {"role_changed": role is not None, "active_changed": is_active is not None})
            return {"user_id": user_id, "username": row["username"], "role": next_role, "is_active": bool(next_active)}

    def authenticate(self, username: str, password: str) -> tuple[dict | None, str | None]:
        try:
            normalized = validate_username(username)
        except ValueError:
            normalized = ""
        with self._connection() as connection:
            row = connection.execute("SELECT * FROM auth_users WHERE username = ?", (normalized,)).fetchone()
            valid_password = verify_password(password, row["password_hash"]) if row else verify_password(
                password if isinstance(password, str) else "", "scrypt$16384$8$1$" + ("00" * 16) + ("00" * 32)
            )
            if row is None or not valid_password or not row["is_active"]:
                self._event(connection, "login_failed")
                return None, None
            session_id = f"ses_{uuid4().hex}"
            token = secrets.token_urlsafe(32)
            csrf = secrets.token_urlsafe(32)
            now = utc_now()
            expires = now + timedelta(seconds=self.session_ttl_seconds)
            connection.execute(
                "INSERT INTO auth_sessions VALUES (?, ?, ?, ?, ?, ?, NULL)",
                (session_id, row["user_id"], _token_hash(token), _token_hash(csrf),
                 now.isoformat(), expires.isoformat()),
            )
            self._event(connection, "login_succeeded", row["user_id"], "session", session_id)
            return {
                "user_id": row["user_id"], "username": row["username"], "role": row["role"],
                "is_active": True, "session_id": session_id, "expires_at": expires.isoformat(),
                "csrf_token": csrf,
            }, token

    def resolve_session(self, token: str | None) -> tuple[Principal | None, str | None]:
        if not token:
            return None, None
        with self._connection() as connection:
            row = connection.execute(
                "SELECT s.*, u.username, u.role, u.is_active FROM auth_sessions s "
                "JOIN auth_users u ON u.user_id = s.user_id WHERE s.token_hash = ?",
                (_token_hash(token),),
            ).fetchone()
            if row is None or row["revoked_at"] is not None:
                return None, None
            now = utc_now()
            if datetime.fromisoformat(row["expires_at"]) <= now or not row["is_active"]:
                revoked_at = now.isoformat()
                connection.execute("UPDATE auth_sessions SET revoked_at = ? WHERE session_id = ?", (revoked_at, row["session_id"]))
                event = "session_expired" if row["is_active"] else "session_revoked_inactive_account"
                self._event(connection, event, row["user_id"], "session", row["session_id"])
                return None, None
            return Principal(
                user_id=row["user_id"], username=row["username"], role=row["role"],
                session_id=row["session_id"], csrf_hash=row["csrf_hash"], expires_at=row["expires_at"],
            ), row["csrf_hash"]

    def verify_csrf(self, principal: Principal, cookie_token: str | None, header_token: str | None) -> bool:
        if not cookie_token or not header_token or not hmac.compare_digest(cookie_token, header_token):
            return False
        return hmac.compare_digest(_token_hash(cookie_token), principal.csrf_hash)

    def rotate_csrf(self, principal: Principal) -> str:
        token = secrets.token_urlsafe(32)
        with self._connection() as connection:
            connection.execute(
                "UPDATE auth_sessions SET csrf_hash = ? WHERE session_id = ? AND revoked_at IS NULL",
                (_token_hash(token), principal.session_id),
            )
        return token

    def revoke_session(self, principal: Principal) -> None:
        now = utc_now().isoformat()
        with self._connection() as connection:
            connection.execute(
                "UPDATE auth_sessions SET revoked_at = ? WHERE session_id = ? AND revoked_at IS NULL",
                (now, principal.session_id),
            )
            self._event(connection, "logout_session_revoked", principal.user_id, "session", principal.session_id)

    def audit_review_event(self, actor_user_id: str, case_id: str, status: str) -> None:
        with self._connection() as connection:
            self._event(connection, "review_updated", actor_user_id, "case", case_id, {"status": status})

    def usernames(self, user_ids: set[str]) -> dict[str, str]:
        """Display names of the given accounts (unknown ids are left out)."""
        ids = sorted(user_ids)
        if not ids:
            return {}
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT user_id, username FROM auth_users WHERE user_id IN (" + ",".join("?" * len(ids)) + ")", ids,
            ).fetchall()
        return {row["user_id"]: row["username"] for row in rows}

    def list_audit_events(self, limit: int = 100) -> list[dict]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT event_id, occurred_at, actor_user_id, event_type, target_type, target_id, metadata_json "
                "FROM security_audit_events ORDER BY occurred_at DESC, event_id DESC LIMIT ?", (limit,),
            ).fetchall()
        return [{**dict(row), "metadata": json.loads(row["metadata_json"])} for row in rows]


def configured_auth_db_path(default_path: str | Path) -> Path:
    configured = os.environ.get("CIR_AUTH_DB_PATH")
    return Path(configured).expanduser() if configured else Path(default_path)


def configured_session_ttl() -> int:
    raw = os.environ.get("CIR_SESSION_TTL_SECONDS", str(SESSION_TTL_SECONDS))
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError("CIR_SESSION_TTL_SECONDS harus berupa bilangan bulat.") from exc
    if value < 60 or value > 7 * 24 * 60 * 60:
        raise ValueError("CIR_SESSION_TTL_SECONDS harus berada antara 60 dan 604800 detik.")
    return value


def configured_cookie_secure() -> bool:
    raw = os.environ.get("CIR_COOKIE_SECURE", "true").strip().lower()
    if raw not in {"true", "false"}:
        raise ValueError("CIR_COOKIE_SECURE harus true atau false.")
    return raw == "true"
