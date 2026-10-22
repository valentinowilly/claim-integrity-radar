"""Consistent API errors for expected client mistakes."""

from uuid import uuid4

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class ApiError(Exception):
    def __init__(self, status_code: int, code: str, message: str, details: dict | None = None):
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details or {}


async def api_error_handler(request: Request, exc: Exception) -> JSONResponse:
    if isinstance(exc, ApiError):
        status_code, code, message, details = (
            exc.status_code, exc.code, exc.message, exc.details
        )
    else:
        status_code, code, message, details = (
            500, "INTERNAL_ERROR", "Permintaan tidak dapat diproses.", {}
        )
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "request_id": f"req_{uuid4().hex}",
                "details": details,
            }
        },
    )


async def request_validation_error_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Return contract-shaped validation errors without echoing submitted values."""
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "INVALID_PAYLOAD",
                "message": "Payload tidak sesuai kontrak API.",
                "request_id": f"req_{uuid4().hex}",
                "details": [
                    {
                        "location": [str(part) for part in item.get("loc", ())],
                        "message": item.get("msg", "Nilai tidak valid."),
                        "type": item.get("type", "validation_error"),
                    }
                    for item in exc.errors()
                ],
            }
        },
    )
