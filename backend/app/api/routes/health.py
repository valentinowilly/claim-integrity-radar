"""Process-only health check route."""

from fastapi import APIRouter

from app import SERVICE_NAME, __version__
from app.schemas.health import HealthResponse

router = APIRouter()


@router.get("/health", response_model=HealthResponse, tags=["health"])
def health_check() -> HealthResponse:
    """Report that the API process can respond; does not check data sources."""
    return HealthResponse(
        status="ok",
        service=SERVICE_NAME,
        version=__version__,
    )
