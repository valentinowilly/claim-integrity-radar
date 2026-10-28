"""Session-cookie authentication and restricted account provisioning."""

from fastapi import APIRouter, Depends, Request, Response

from app.api.errors import ApiError
from app.schemas.auth import LoginRequest, SessionResponse, UserCreateRequest, UserResponse, UserUpdateRequest
from app.security.auth import (
    CSRF_COOKIE, SESSION_COOKIE, AuthStore, AuthenticationError,
    AuthenticationStorageError, Principal, ROLE_PERMISSIONS,
)
from app.security.dependencies import auth_store, current_principal, require_csrf, require_permission
from app.security.rate_limit import client_key, limiter, rate_limited_error, username_key


router = APIRouter(prefix="/api/v1/auth", tags=["authentication"])


def _cookie_options(request: Request) -> dict:
    return {
        "secure": request.app.state.cookie_secure,
        "httponly": True,
        "samesite": "lax",
        "path": "/api/v1",
    }


def _session_payload(user: dict) -> dict:
    return {
        "user": {key: user[key] for key in ("user_id", "username", "role", "is_active")},
        "permissions": sorted(ROLE_PERMISSIONS[user["role"]]),
        "expires_at": user["expires_at"],
        "csrf_token": user["csrf_token"],
    }


@router.post("/login", response_model=SessionResponse)
def login(payload: LoginRequest, request: Request, response: Response,
          store: AuthStore = Depends(auth_store)):
    limits = limiter(request)
    account = username_key(payload.username)
    # Both limits are checked before the password is verified, so a blocked request costs no scrypt work.
    delay = limits.hit("login_ip", client_key(request)) or limits.retry_after("login_failures", account)
    if delay is not None:
        raise rate_limited_error(delay)
    try:
        user, session_token = store.authenticate(payload.username, payload.password)
    except AuthenticationStorageError as exc:
        raise ApiError(503, "AUTH_STORAGE_UNAVAILABLE", "Layanan autentikasi sementara tidak tersedia.", {}) from exc
    if user is None or session_token is None:
        limits.record("login_failures", account)
        raise ApiError(401, "INVALID_CREDENTIALS", "Username atau password tidak valid.", {})
    limits.reset("login_failures", account)
    options = _cookie_options(request)
    response.set_cookie(SESSION_COOKIE, session_token, max_age=request.app.state.session_ttl_seconds, **options)
    response.set_cookie(CSRF_COOKIE, user["csrf_token"], max_age=request.app.state.session_ttl_seconds,
                        httponly=False, **{key: value for key, value in options.items() if key != "httponly"})
    return _session_payload(user)


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response,
           principal: Principal = Depends(require_csrf),
           store: AuthStore = Depends(auth_store)):
    try:
        store.revoke_session(principal)
    except AuthenticationStorageError as exc:
        raise ApiError(503, "AUTH_STORAGE_UNAVAILABLE", "Layanan autentikasi sementara tidak tersedia.", {}) from exc
    response.delete_cookie(SESSION_COOKIE, path="/api/v1", secure=request.app.state.cookie_secure,
                           httponly=True, samesite="lax")
    response.delete_cookie(CSRF_COOKIE, path="/api/v1", secure=request.app.state.cookie_secure,
                           httponly=False, samesite="lax")


@router.get("/me", response_model=SessionResponse)
def current_user(request: Request, response: Response, principal: Principal = Depends(current_principal),
                 store: AuthStore = Depends(auth_store)):
    csrf = request.cookies.get(CSRF_COOKIE)
    try:
        if not csrf or not store.verify_csrf(principal, csrf, csrf):
            csrf = store.rotate_csrf(principal)
    except AuthenticationStorageError as exc:
        raise ApiError(503, "AUTH_STORAGE_UNAVAILABLE", "Layanan autentikasi sementara tidak tersedia.", {}) from exc
    user = {
        "user_id": principal.user_id, "username": principal.username, "role": principal.role,
        "is_active": True, "expires_at": principal.expires_at, "csrf_token": csrf,
    }
    # Refreshing /me re-issues the readable anti-CSRF cookie, never the session token.
    response.set_cookie(
        CSRF_COOKIE, csrf, max_age=request.app.state.session_ttl_seconds,
        httponly=False, secure=request.app.state.cookie_secure, samesite="lax", path="/api/v1",
    )
    return _session_payload(user)


@router.post("/users", response_model=UserResponse, status_code=201)
def create_user(payload: UserCreateRequest, request: Request,
               principal: Principal = Depends(require_permission("users:manage")),
               _csrf: Principal = Depends(require_csrf),
               store: AuthStore = Depends(auth_store)):
    try:
        user = store.create_user(payload.username, payload.password, payload.role, principal.user_id)
    except ValueError as exc:
        raise ApiError(422, "INVALID_PAYLOAD", str(exc), {}) from exc
    except AuthenticationError as exc:
        raise ApiError(409, "USERNAME_CONFLICT", str(exc), {}) from exc
    except AuthenticationStorageError as exc:
        raise ApiError(503, "AUTH_STORAGE_UNAVAILABLE", "Layanan autentikasi sementara tidak tersedia.", {}) from exc
    return {"user": user}


@router.patch("/users/{user_id}", response_model=UserResponse)
def update_user(user_id: str, payload: UserUpdateRequest,
                principal: Principal = Depends(require_permission("users:manage")),
                _csrf: Principal = Depends(require_csrf),
                store: AuthStore = Depends(auth_store)):
    try:
        user = store.update_user(user_id, principal.user_id, payload.role, payload.is_active)
    except ValueError as exc:
        raise ApiError(422, "INVALID_PAYLOAD", str(exc), {}) from exc
    except AuthenticationError as exc:
        raise ApiError(409, "ADMIN_INVARIANT", str(exc), {}) from exc
    except AuthenticationStorageError as exc:
        raise ApiError(503, "AUTH_STORAGE_UNAVAILABLE", "Layanan autentikasi sementara tidak tersedia.", {}) from exc
    if user is None:
        raise ApiError(404, "USER_NOT_FOUND", "Akun tidak ditemukan.", {})
    return {"user": user}
