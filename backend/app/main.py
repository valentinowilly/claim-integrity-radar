"""FastAPI application factory and ASGI application entry point."""

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
import logging
from pathlib import Path

from app import __version__
from app.api.errors import ApiError, api_error_handler, request_validation_error_handler
from app.api.routes.analytics import router as analytics_router
from app.api.routes.auth import router as auth_router
from app.api.routes.inbox import router as inbox_router
from app.api.routes.assignments import router as assignments_router
from app.api.routes.case_context import router as case_context_router
from app.api.routes.clinical_ai import router as clinical_ai_router
from app.services.inbox import start_scheduler as start_inbox_scheduler
from app.services.retention import start_maintenance as start_retention
from app.api.routes.batches import router as batches_router
from app.analytics.ml_model import model_status
from app.api.routes.health import router as health_router
from app.api.routes.notifications import router as notifications_router
from app.db import DatabaseConfigurationError, configured_database
from app.db_migrations import schema_status
from app.services.validation_jobs import mark_interrupted_jobs
from app.api.routes.reviews import router as reviews_router
from app.api.routes.runs import router as runs_router
from app.api.routes.run_reviews import router as run_reviews_router, summary_router as run_review_summary_router
from app.api.routes.sources import router as sources_router
from app.services.reviews import configured_review_db_path
from app.security.auth import configured_auth_db_path, configured_cookie_secure, configured_session_ttl
from app.security.rate_limit import RateLimiter, build_rate_limiter, configured_rules
from app.services.batches import configured_batch_db_path


def create_app(review_db_path: str | Path | None = None, auth_db_path: str | Path | None = None,
               session_ttl_seconds: int | None = None, cookie_secure: bool | None = None,
               batch_db_path: str | Path | None = None, rate_limiter: RateLimiter | None = None) -> FastAPI:
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
    # Per-process counters; see app.security.rate_limit for the deployment assumptions.
    application.state.rate_limiter = rate_limiter if rate_limiter is not None else build_rate_limiter(configured_rules())
    # The FKRTL ML artifact is optional for the rules but required for ML scores: report a clear,
    # path-free status at startup instead of failing later inside a run.
    # With CIR_DATABASE_URL every store uses that PostgreSQL database; its schema must already be
    # migrated (python -m scripts.db_migrate). Startup never creates, drops or imports anything.
    database = configured_database()
    if database is not None:
        try:
            status = schema_status(database)
        except Exception as exc:  # connection failure: type only, never the URL
            raise DatabaseConfigurationError(
                f"Database PostgreSQL tidak dapat dihubungi ({type(exc).__name__}).") from None
        if not status["ok"]:
            raise DatabaseConfigurationError(
                "Skema PostgreSQL belum sesuai versi aplikasi; jalankan python -m scripts.db_migrate.")
    application.state.database_backend = "postgresql" if database is not None else "sqlite"
    # Jobs whose worker stopped (heartbeat expired) are marked interrupted.
    mark_interrupted_jobs(application.state.run_db_path)
    application.state.ml_model_status = model_status()
    if not application.state.ml_model_status["available"]:
        logging.getLogger("cir.ml").warning(
            "ML model artifact %s unavailable (%s); FKRTL runs will report ml_anomaly as unavailable.",
            application.state.ml_model_status["model_version"], application.state.ml_model_status["error_code"])
    application.add_exception_handler(ApiError, api_error_handler)
    application.add_exception_handler(Exception, api_error_handler)
    application.add_exception_handler(RequestValidationError, request_validation_error_handler)
    application.include_router(health_router)
    application.include_router(auth_router)
    application.include_router(batches_router)
    application.include_router(runs_router)
    application.include_router(case_context_router)
    application.include_router(sources_router)
    application.include_router(analytics_router)
    application.include_router(reviews_router)
    application.include_router(run_reviews_router)
    application.include_router(run_review_summary_router)
    application.include_router(notifications_router)
    application.include_router(inbox_router)
    application.include_router(assignments_router)
    application.include_router(clinical_ai_router)
    # Daily intake from the drop folder (only when CIR_INBOX_DIR is set; once per process).
    start_inbox_scheduler(application.state.run_db_path)
    # Hourly: archive analyses older than the active window (nothing is deleted).
    start_retention(application.state.run_db_path)
    return application


app = create_app()
