"""FastAPI application factory and ASGI application entry point."""

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from pathlib import Path

from app import __version__
from app.api.errors import ApiError, api_error_handler, request_validation_error_handler
from app.api.routes.analytics import router as analytics_router
from app.api.routes.auth import router as auth_router
from app.api.routes.batches import router as batches_router
from app.api.routes.health import router as health_router
from app.api.routes.reviews import router as reviews_router
from app.api.routes.runs import router as runs_router
from app.api.routes.run_reviews import router as run_reviews_router
from app.services.reviews import configured_review_db_path
from app.security.auth import configured_auth_db_path, configured_cookie_secure, configured_session_ttl
from app.services.batches import configured_batch_db_path


def create_app(review_db_path: str | Path | None = None, auth_db_path: str | Path | None = None,
               session_ttl_seconds: int | None = None, cookie_secure: bool | None = None,
               batch_db_path: str | Path | None = None) -> FastAPI:
    """Create the API application without initializing data sources."""
    application = FastAPI(
        title="Claim Integrity Radar API",
        version=__version__,
    )
    application.state.review_db_path = Path(review_db_path) if review_db_path is not None else configured_review_db_path()
    application.state.auth_db_path = (
        Path(auth_db_path) if auth_db_path is not None
        else configured_auth_db_path(application.state.review_db_path)
    )
    application.state.session_ttl_seconds = (
        configured_session_ttl() if session_ttl_seconds is None else session_ttl_seconds
    )
    application.state.cookie_secure = configured_cookie_secure() if cookie_secure is None else cookie_secure
    application.state.batch_db_path = Path(batch_db_path) if batch_db_path is not None else configured_batch_db_path()
    # Run manifests/results share the batch SQLite file so batch pinning and
    # result persistence use one transactional store; no second DB is opened.
    application.state.run_db_path = application.state.batch_db_path
    application.add_exception_handler(ApiError, api_error_handler)
    application.add_exception_handler(Exception, api_error_handler)
    application.add_exception_handler(RequestValidationError, request_validation_error_handler)
    application.include_router(health_router)
    application.include_router(auth_router)
    application.include_router(batches_router)
    application.include_router(runs_router)
    application.include_router(analytics_router)
    application.include_router(reviews_router)
    application.include_router(run_reviews_router)
    return application


app = create_app()
