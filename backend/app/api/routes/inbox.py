"""Automatic intake folder: status and a manual "pull now" next to the daily schedule."""

from fastapi import APIRouter, Depends, Request, Response

from app.api.errors import ApiError
from app.security.auth import Principal
from app.security.dependencies import require_csrf, require_permission
from app.services.inbox import InboxBusy, InboxStorageError, inbox_directory, inbox_status, start_pull_in_background

router = APIRouter(prefix="/api/v1/inbox", tags=["automatic intake"])


@router.get("")
def get_inbox(request: Request, _principal: Principal = Depends(require_permission("runs:read"))):
    try:
        return inbox_status(request.app.state.run_db_path)
    except InboxStorageError as exc:
        raise ApiError(503, "INBOX_STORAGE_UNAVAILABLE", str(exc), {}) from exc


@router.post("/pull", status_code=202)
def pull_now(request: Request, principal: Principal = Depends(require_permission("runs:write")),
             _csrf: Principal = Depends(require_csrf)):
    directory = inbox_directory()
    if directory is None or not directory.is_dir():
        raise ApiError(409, "INBOX_NOT_CONFIGURED", "Folder kiriman belum diatur di server.", {})
    try:
        start_pull_in_background(request.app.state.run_db_path, principal.user_id)
    except InboxBusy as exc:
        raise ApiError(409, "INBOX_BUSY", "Pengambilan file sedang berjalan.", {}) from exc
    return Response(status_code=202)
