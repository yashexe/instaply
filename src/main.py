"""
Instaply — Fast job discovery and alerting.

FastAPI application entrypoint with lifespan management for database,
scheduler, and structured logging.
"""

from contextlib import asynccontextmanager
import logging

import structlog
import uvicorn
from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from src.config import settings
from src.db.connection import init_db, close_db
from src.db.migrations import run_migrations
from src.scheduler.scheduler import start_scheduler, shutdown_scheduler
from src.web.router import STATIC_DIR


def configure_logging() -> None:
    """Set up structlog with pretty console output."""
    log_level = logging.getLevelName(settings.log_level.upper())
    if not isinstance(log_level, int):
        log_level = logging.INFO

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.dev.set_exc_info,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            log_level
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan — startup and shutdown hooks."""
    logger = structlog.get_logger()

    # --- Startup ---
    configure_logging()
    logger.info("app.starting", version="0.1.0")

    # Initialize database
    db = await init_db()
    await run_migrations(db)
    logger.info("app.database_ready")

    # Start scheduler
    start_scheduler()
    logger.info("app.scheduler_ready")

    logger.info(
        "app.started",
        host=settings.host,
        port=settings.port,
        llm_provider=settings.llm_provider,
        llm_configured=settings.llm_configured,
        smtp_configured=settings.smtp_configured,
    )

    yield

    # --- Shutdown ---
    logger.info("app.shutting_down")
    shutdown_scheduler()
    await close_db()
    logger.info("app.stopped")


# Create FastAPI app
app = FastAPI(
    title="Instaply",
    description="Fast job discovery and alerting — monitor ATS feeds, score against your profile, get instant alerts.",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS — permissive for local dev
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# --- Browser Convenience ---
@app.get("/", include_in_schema=False)
async def root() -> RedirectResponse:
    """Redirect browser visits to the Instaply app."""
    return RedirectResponse(url="/app")


@app.get("/favicon.ico", include_in_schema=False)
async def favicon() -> Response:
    """Return an empty favicon response to avoid noisy browser 404s."""
    return Response(status_code=204)


# --- Health Check ---
@app.get("/health", tags=["system"])
async def health_check():
    """Health check endpoint."""
    return {
        "status": "ok",
        "version": "0.1.0",
        "llm_configured": settings.llm_configured,
        "smtp_configured": settings.smtp_configured,
    }


# --- Register routers ---
from src.profile.router import router as profile_router
from src.preferences.router import router as preferences_router
from src.sources.router import router as sources_router
from src.discovery.router import router as discovery_router
from src.jobs.router import router as jobs_router
from src.matching.router import router as matching_router
from src.alerts.router import router as alerts_router
from src.web.router import router as web_router

app.include_router(web_router)
app.include_router(profile_router)
app.include_router(preferences_router)
app.include_router(sources_router)
app.include_router(discovery_router)
app.include_router(jobs_router)
app.include_router(matching_router)
app.include_router(alerts_router)


if __name__ == "__main__":
    uvicorn.run(
        "src.main:app",
        host=settings.host,
        port=settings.port,
        reload=True,
    )
