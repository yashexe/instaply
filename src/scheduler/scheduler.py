"""
APScheduler setup — in-process async job scheduler.

Manages recurring jobs for source polling and health checks.
Integrates with FastAPI lifespan for clean startup/shutdown.
"""

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from src.config import settings

logger = structlog.get_logger()

scheduler = AsyncIOScheduler()


def start_scheduler() -> None:
    """Start the scheduler and register recurring jobs."""
    if scheduler.running:
        return

    # Source polling job — checks which sources are due and triggers ingestion
    scheduler.add_job(
        poll_sources_job,
        trigger=IntervalTrigger(seconds=60),  # Check every minute which sources need polling
        id="poll_sources",
        name="Poll due sources",
        replace_existing=True,
    )

    # Source health check — marks degraded sources
    scheduler.add_job(
        source_health_check_job,
        trigger=IntervalTrigger(seconds=settings.health_check_interval),
        id="source_health_check",
        name="Source health check",
        replace_existing=True,
    )

    # LLM judge — evaluates the top pending matches against the resume,
    # within the daily LLM budget slice
    scheduler.add_job(
        judge_matches_job,
        trigger=IntervalTrigger(seconds=settings.judge_interval),
        id="judge_matches",
        name="Judge pending matches",
        replace_existing=True,
    )

    # Digest delivery — batches digest-decision matches into one notification
    scheduler.add_job(
        send_digest_job,
        trigger=IntervalTrigger(seconds=settings.digest_interval),
        id="send_digest",
        name="Send match digest",
        replace_existing=True,
    )

    # Source discovery — probes ATS boards for companies matching the
    # profile and stages suggestions for the user to review
    if settings.discovery_enabled:
        scheduler.add_job(
            discovery_job,
            trigger=IntervalTrigger(seconds=settings.discovery_interval),
            id="discovery",
            name="Discover new sources",
            replace_existing=True,
        )

    scheduler.start()
    logger.info("scheduler.started")


def shutdown_scheduler() -> None:
    """Gracefully shut down the scheduler."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("scheduler.shutdown")


async def poll_sources_job() -> None:
    """
    Scheduled job: find sources that are due for polling and trigger ingestion.

    This is the main scheduler loop. It checks each active source's last fetch
    time against its configured interval and dispatches fetch tasks.
    """
    from src.ingestion.service import poll_due_sources

    try:
        await poll_due_sources()
    except Exception as e:
        logger.error("scheduler.poll_sources_failed", error=str(e))


async def source_health_check_job() -> None:
    """
    Scheduled job: check source health and mark degraded sources.
    """
    from src.sources.repository import check_source_health

    try:
        await check_source_health()
    except Exception as e:
        logger.error("scheduler.health_check_failed", error=str(e))


async def judge_matches_job() -> None:
    """
    Scheduled job: LLM-judge the top pending matches. Budget, cooldown,
    and attempt caps inside the judge keep this within the daily quota.
    """
    from src.db.connection import get_db
    from src.matching.judge import judge_pending_matches

    try:
        db = await get_db()
        summary = await judge_pending_matches(db, "default")
        if summary["judged"] or summary["stopped_reason"]:
            logger.info("scheduler.judge_complete", **summary)
    except Exception as e:
        logger.error("scheduler.judge_failed", error=str(e))


async def discovery_job() -> None:
    """
    Scheduled job: discover new company job boards worth monitoring.
    The service skips itself when there are no target roles yet or too
    many suggestions already await review.
    """
    from src.db.connection import get_db
    from src.discovery.service import run_discovery

    try:
        db = await get_db()
        stats = await run_discovery(db, "default")
        if stats.candidates:
            logger.info(
                "scheduler.discovery_complete",
                suggested=stats.suggested,
                probed=stats.probed,
                not_found=stats.not_found,
            )
    except Exception as e:
        logger.error("scheduler.discovery_failed", error=str(e))


async def send_digest_job() -> None:
    """
    Scheduled job: deliver a digest of accumulated digest-decision matches.
    """
    from src.alerts.service import send_digest
    from src.db.connection import get_db

    try:
        db = await get_db()
        await send_digest(db, "default")
    except Exception as e:
        logger.error("scheduler.send_digest_failed", error=str(e))
