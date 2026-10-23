"""FastAPI authentication, permission, and CSRF dependencies."""

from collections.abc import Callable

from fastapi import Depends, Request

from app.api.errors import ApiError
from app.security.auth import (
    CSRF_COOKIE, SESSION_COOKIE, AuthStore, AuthenticationStorageError, Principal,
)


def auth_store(request: Request) -> AuthStore:
    return AuthStore(request.app.state.auth_db_path, request.app.state.session_ttl_seconds)


def current_principal(request: Request) -> Principal:
    token = request.cookies.get(SESSION_COOKIE)
    try:
        principal, _ = auth_store(request).resolve_session(token)
    except AuthenticationStorageError as exc:
        raise ApiError(503, "AUTH_STORAGE_UNAVAILABLE", "Layanan autentikasi sementara tidak tersedia.", {}) from exc
    if principal is None:
        raise ApiError(401, "AUTHENTICATION_REQUIRED", "Sesi tidak tersedia atau telah berakhir.", {})
    return principal


def require_permission(permission: str) -> Callable:
    def guard(principal: Principal = Depends(current_principal)) -> Principal:
        if permission not in principal.permissions:
            raise ApiError(403, "PERMISSION_DENIED", "Aksi ini tidak diizinkan untuk role akun.", {})
        return principal
    return guard


def require_csrf(request: Request, principal: Principal = Depends(current_principal)) -> Principal:
    header_token = request.headers.get("x-csrf-token")
    cookie_token = request.cookies.get(CSRF_COOKIE)
    try:
        valid = auth_store(request).verify_csrf(principal, cookie_token, header_token)
    except AuthenticationStorageError as exc:
        raise ApiError(503, "AUTH_STORAGE_UNAVAILABLE", "Layanan autentikasi sementara tidak tersedia.", {}) from exc
    if not valid:
        raise ApiError(403, "CSRF_VALIDATION_FAILED", "Token perlindungan permintaan tidak valid.", {})
    return principal
