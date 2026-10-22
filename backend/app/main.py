"""FastAPI application factory and ASGI application entry point."""

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from pathlib import Path

from app import __version__
from app.api.errors import ApiError, api_error_handler, request_validation_error_handler
from app.api.routes.analytics import router as analytics_router
from app.api.routes.health import router as health_router
from app.api.routes.reviews import router as reviews_router
from app.services.reviews import configured_review_db_path


def create_app(review_db_path: str | Path | None = None) -> FastAPI:
    """Create the API application without initializing data sources."""
    application = FastAPI(
        title="Claim Integrity Radar API",
        version=__version__,
    )
    application.state.review_db_path = Path(review_db_path) if review_db_path is not None else configured_review_db_path()
    application.add_exception_handler(ApiError, api_error_handler)
    application.add_exception_handler(Exception, api_error_handler)
    application.add_exception_handler(RequestValidationError, request_validation_error_handler)
    application.include_router(health_router)
    application.include_router(analytics_router)
    application.include_router(reviews_router)
    return application


app = create_app()
