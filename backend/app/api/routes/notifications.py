"""In-app notifications for the signed-in user (read-only; derived from stored history)."""

from datetime import datetime

from fastapi import APIRouter, Depends, Request

from app.api.errors import ApiError
from app.security.auth import Principal
from app.security.dependencies import current_principal
from app.services.notifications import NotificationStorageError, notifications_for

router = APIRouter(prefix="/api/v1/notifications", tags=["notifications"])


@router.get("")
def list_notifications(request: Request, since: str | None = None, limit: int = 20,
                       principal: Principal = Depends(current_principal)):
    """Events after ``since`` (ISO 8601) that this user may see; pass ``next_since`` on the next poll."""
    if not 1 <= limit <= 50:
        raise ApiError(400, "INVALID_FILTER", "limit harus 1-50.", {})
    if since is not None:
        try:
            datetime.fromisoformat(since)
        except ValueError:
            raise ApiError(400, "INVALID_FILTER", "since harus berformat ISO 8601.", {}) from None
    try:
        data = notifications_for(request.app.state.run_db_path, user_id=principal.user_id,
                                 permissions=principal.permissions, since=since, limit=limit)
    except NotificationStorageError as exc:
        raise ApiError(503, "NOTIFICATIONS_UNAVAILABLE", str(exc), {}) from exc
    return {"availability": "available", **data}
