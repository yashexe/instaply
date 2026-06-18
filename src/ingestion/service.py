"""Source polling and ingestion orchestration."""

from __future__ import annotations

import aiosqlite
import structlog

from src.db.connection import get_db
from src.config import settings
from src.ingestion.adapter import SourceAdapter
from src.ingestion.adapters.ashby import AshbyAdapter
from src.ingestion.adapters.greenhouse import GreenhouseAdapter
from src.ingestion.adapters.lever import LeverAdapter
from src.ingestion.http import AdapterFetchError
from src.alerts import service as alerts_service
from src.jobs import repository as jobs_repository
from src.matching.service import score_job_for_user
from src.sources import repository as sources_repository

logger = structlog.get_logger()

DEFAULT_USER_ID = "default"


ADAPTERS: dict[str, SourceAdapter] = {
    "greenhouse": GreenhouseAdapter(),
    "lever": LeverAdapter(),
    "ashby": AshbyAdapter(),
}


def get_adapter(provider: str) -> SourceAdapter | None:
    """Return the adapter for a provider."""
    return ADAPTERS.get(provider)


async def poll_source(
    db: aiosqlite.Connection,
    source: dict,
    *,
    score_matches: bool = True,
    alert_sink: list | None = None,
) -> dict:
    """Poll one source, persist jobs, and score new/changed postings.

    Alert-worthy matches are collected and delivered as a single combined email
    rather than one email per match. Pass a shared alert_sink to batch alerts
    across several sources (one email for the whole poll run); when omitted this
    source flushes its own combined email before returning.
    """
    owns_sink = alert_sink is None
    sink: list = alert_sink if alert_sink is not None else []
    source_id = source["id"]
    is_initial_poll = source.get("last_success_at") is None
    adapter = get_adapter(source.get("provider") or "")
    if adapter is None:
        message = f"Unsupported source provider: {source.get('provider')}"
        just_degraded = await sources_repository.mark_source_failure(
            db, source_id, message
        )
        if just_degraded:
            await alerts_service.send_source_failure_alert(source, message)
        logger.warning("ingestion.unsupported_provider", source_id=source_id)
        return {
            "source_id": source_id,
            "job_count": 0,
            "new_count": 0,
            "changed_count": 0,
            "baseline_count": 0,
            "matched_count": 0,
            "error": message,
        }

    try:
        raw_jobs = await adapter.fetch_jobs(source)
    except Exception as exc:
        message = str(exc)
        just_degraded = await sources_repository.mark_source_failure(
            db, source_id, message
        )
        if just_degraded:
            await alerts_service.send_source_failure_alert(source, message)
        # AdapterFetchError is an expected, handled outcome (board not found,
        # 4xx, etc.) — log it cleanly. A traceback is only useful for an
        # unexpected crash inside the adapter.
        if isinstance(exc, AdapterFetchError):
            logger.warning(
                "ingestion.fetch_failed",
                source_id=source_id,
                provider=source.get("provider"),
                error=message,
            )
        else:
            logger.exception("ingestion.fetch_failed", source_id=source_id)
        return {
            "source_id": source_id,
            "job_count": 0,
            "new_count": 0,
            "changed_count": 0,
            "baseline_count": 0,
            "matched_count": 0,
            "error": message,
        }

    new_count = 0
    changed_count = 0
    baseline_count = 0
    matched_count = 0
    for raw_job in raw_jobs:
        job_id, is_new, content_changed = await jobs_repository.upsert_raw_job(
            db,
            source,
            raw_job,
        )
        if is_new:
            new_count += 1
        elif content_changed:
            changed_count += 1

        should_baseline = (
            settings.baseline_first_poll
            and is_initial_poll
            and is_new
        )
        if should_baseline:
            baseline_count += 1

        if score_matches and (is_new or content_changed) and not should_baseline:
            match = await score_job_for_user(
                db,
                job_id,
                source.get("user_id") or DEFAULT_USER_ID,
                send_alerts=True,
                alert_sink=sink,
            )
            if match is not None:
                matched_count += 1

    if owns_sink:
        await alerts_service.send_combined_alert(db, sink)

    await sources_repository.mark_source_success(db, source_id)
    logger.info(
        "ingestion.poll_complete",
        source_id=source_id,
        provider=source.get("provider"),
        job_count=len(raw_jobs),
        new_count=new_count,
        changed_count=changed_count,
        baseline_count=baseline_count,
        matched_count=matched_count,
    )
    return {
        "source_id": source_id,
        "job_count": len(raw_jobs),
        "new_count": new_count,
        "changed_count": changed_count,
        "baseline_count": baseline_count,
        "matched_count": matched_count,
        "error": None,
    }


async def poll_source_by_id(
    db: aiosqlite.Connection,
    source_id: str,
    *,
    score_matches: bool = True,
) -> dict | None:
    """Poll one source by ID."""
    source = await sources_repository.get_source(db, source_id)
    if source is None:
        return None
    return await poll_source(db, source, score_matches=score_matches)


async def poll_due_sources() -> list[dict]:
    """Poll every due active source. Used by the scheduler."""
    db = await get_db()
    due_sources = await sources_repository.list_due_sources(db)
    results: list[dict] = []
    # One shared sink across every source so the whole run emits a single
    # combined email instead of one per source (and one per match).
    alert_sink: list = []
    for source in due_sources:
        results.append(
            await poll_source(db, source, score_matches=True, alert_sink=alert_sink)
        )
    if due_sources:
        await alerts_service.send_combined_alert(db, alert_sink)
        logger.info("ingestion.due_sources_polled", count=len(due_sources))
    return results
