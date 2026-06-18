"""Alert decision and delivery service."""

from __future__ import annotations

import aiosmtplib
import aiosqlite
import structlog
from email.message import EmailMessage

from src.alerts import repository
from src.config import settings

logger = structlog.get_logger()


def choose_alert_channel() -> str:
    """Choose the default notification channel for this local MVP."""
    return "email" if settings.smtp_configured else "in_app"


def build_idempotency_key(
    *,
    user_id: str,
    match_result_id: str,
    channel: str,
) -> str:
    """Build an alert idempotency key."""
    return f"{user_id}:{match_result_id}:{channel}"


def _format_email_subject(match_result: dict, job: dict) -> str:
    return f"Instaply match {match_result['score']}/100: {job['title']} at {job['company_name']}"


def _format_email_body(match_result: dict, job: dict) -> str:
    reasons = "\n".join(f"- {item}" for item in match_result.get("matching_reasons", []))
    missing = "\n".join(
        f"- {item}" for item in match_result.get("missing_requirements", [])
    )
    uncertainties = "\n".join(
        f"- {item}" for item in match_result.get("uncertainties", [])
    )
    return "\n".join(
        [
            f"{job['title']} at {job['company_name']}",
            f"Score: {match_result['score']}/100",
            f"Link: {job.get('canonical_url') or 'N/A'}",
            "",
            match_result.get("summary") or "",
            "",
            "Matching reasons:",
            reasons or "- No reasons recorded",
            "",
            "Missing requirements:",
            missing or "- None recorded",
            "",
            "Uncertainties:",
            uncertainties or "- None recorded",
        ]
    )


async def _send_email(match_result: dict, job: dict) -> None:
    """Send an email notification using configured SMTP settings."""
    message = EmailMessage()
    message["From"] = settings.smtp_from_email or settings.smtp_username
    message["To"] = settings.alert_to_email
    message["Subject"] = _format_email_subject(match_result, job)
    message.set_content(_format_email_body(match_result, job))

    await aiosmtplib.send(
        message,
        hostname=settings.smtp_host,
        port=settings.smtp_port,
        username=settings.smtp_username,
        password=settings.smtp_password,
        start_tls=True,
    )


def _format_digest_subject(matches: list[dict]) -> str:
    count = len(matches)
    plural = "match" if count == 1 else "matches"
    return f"Instaply digest: {count} new {plural} (top score {matches[0]['score']}/100)"


def _format_digest_body(matches: list[dict], max_items: int) -> str:
    lines = [
        f"You have {len(matches)} new job "
        f"{'match' if len(matches) == 1 else 'matches'} worth a look.",
        "",
    ]
    for index, match in enumerate(matches[:max_items], start=1):
        lines.append(
            f"{index}. [{match['score']}/100] {match['job_title']} "
            f"at {match['company_name']}"
        )
        if match.get("job_url"):
            lines.append(f"   {match['job_url']}")
        if match.get("summary"):
            lines.append(f"   {match['summary']}")
        lines.append("")
    remainder = len(matches) - max_items
    if remainder > 0:
        lines.append(f"...and {remainder} more in the app.")
        lines.append("")
    lines.append(f"Open Instaply: http://127.0.0.1:{settings.port}/app#matches")
    return "\n".join(lines)


async def _send_digest_email(matches: list[dict]) -> None:
    """Send one digest email covering multiple matches."""
    message = EmailMessage()
    message["From"] = settings.smtp_from_email or settings.smtp_username
    message["To"] = settings.alert_to_email
    message["Subject"] = _format_digest_subject(matches)
    message.set_content(_format_digest_body(matches, settings.digest_max_items))

    await aiosmtplib.send(
        message,
        hostname=settings.smtp_host,
        port=settings.smtp_port,
        username=settings.smtp_username,
        password=settings.smtp_password,
        start_tls=True,
    )


async def send_digest(
    db: aiosqlite.Connection,
    user_id: str,
    *,
    lookback_days: int | None = None,
) -> dict:
    """Deliver a digest of undelivered digest-decision matches.

    Sends one combined email (or records in-app alerts when SMTP is not
    configured), then marks every included match with an alert row so it is
    never digested twice.
    """
    lookback = lookback_days if lookback_days is not None else settings.digest_lookback_days
    matches = await repository.list_undigested_matches(db, user_id, lookback)
    if not matches:
        logger.info("digest.empty", lookback_days=lookback)
        return {"sent": 0, "channel": None, "error": None}

    channel = choose_alert_channel()

    if channel == "email":
        try:
            await _send_digest_email(matches)
        except Exception as exc:
            # Leave matches unmarked so the next digest run retries them.
            logger.error("digest.email_failed", error=str(exc), count=len(matches))
            return {"sent": 0, "channel": channel, "error": str(exc)}

    for match in matches:
        key = f"{user_id}:{match['id']}:digest"
        alert_id = await repository.create_alert(
            db,
            user_id=user_id,
            match_result_id=match["id"],
            channel=channel,
            idempotency_key=key,
        )
        await repository.update_alert_status(db, alert_id, "sent")

    logger.info("digest.sent", channel=channel, count=len(matches))
    return {"sent": len(matches), "channel": channel, "error": None}


def _alert_digest_rows(alerts: list[tuple[dict, dict]]) -> list[dict]:
    """Normalize (match_result, job) pairs into digest-body rows, best first."""
    rows = [
        {
            "score": match_result["score"],
            "job_title": job["title"],
            "company_name": job["company_name"],
            "job_url": job.get("canonical_url"),
            "summary": match_result.get("summary"),
        }
        for match_result, job in alerts
    ]
    rows.sort(key=lambda row: row["score"], reverse=True)
    return rows


def _format_combined_alert_subject(rows: list[dict]) -> str:
    count = len(rows)
    plural = "match" if count == 1 else "matches"
    return f"Instaply: {count} new {plural} (top score {rows[0]['score']}/100)"


async def _send_combined_alert_email(rows: list[dict]) -> None:
    """Send one email covering a batch of alert-worthy matches."""
    message = EmailMessage()
    message["From"] = settings.smtp_from_email or settings.smtp_username
    message["To"] = settings.alert_to_email
    message["Subject"] = _format_combined_alert_subject(rows)
    message.set_content(_format_digest_body(rows, settings.digest_max_items))

    await aiosmtplib.send(
        message,
        hostname=settings.smtp_host,
        port=settings.smtp_port,
        username=settings.smtp_username,
        password=settings.smtp_password,
        start_tls=True,
    )


async def send_combined_alert(
    db: aiosqlite.Connection,
    alerts: list[tuple[dict, dict]],
    *,
    force_channel: str | None = None,
) -> dict:
    """Deliver a batch of alert-worthy matches in a single combined email.

    This replaces one-email-per-match during a poll or judge run: it creates an
    idempotent alert row per match (skipping any already delivered) and sends
    exactly one email covering all of them. Falls back to per-match in-app alert
    rows when SMTP is not configured. Each tuple is (match_result, job).
    """
    if not alerts:
        return {"sent": 0, "channel": None, "error": None}

    channel = force_channel or choose_alert_channel()

    # Reserve an idempotent alert row per match first; skip any match that was
    # already alerted so a re-poll never re-notifies for the same posting.
    pending: list[tuple[str, dict, dict]] = []
    for match_result, job in alerts:
        key = build_idempotency_key(
            user_id=match_result["user_id"],
            match_result_id=match_result["id"],
            channel=channel,
        )
        if await repository.get_alert_by_idempotency_key(db, key) is not None:
            continue
        alert_id = await repository.create_alert(
            db,
            user_id=match_result["user_id"],
            match_result_id=match_result["id"],
            channel=channel,
            idempotency_key=key,
        )
        pending.append((alert_id, match_result, job))

    if not pending:
        return {"sent": 0, "channel": channel, "error": None}

    if channel == "in_app":
        for alert_id, _, _ in pending:
            await repository.update_alert_status(db, alert_id, "sent")
        logger.info("alert.in_app_batch_recorded", count=len(pending))
        return {"sent": len(pending), "channel": channel, "error": None}

    rows = _alert_digest_rows([(m, j) for _, m, j in pending])
    try:
        await _send_combined_alert_email(rows)
    except Exception as exc:
        # Mark every reserved row failed; the matches keep their alert rows so
        # they are not silently retried into a second email next run.
        for alert_id, _, _ in pending:
            await repository.update_alert_status(db, alert_id, "failed", str(exc))
        logger.error("alert.combined_email_failed", count=len(pending), error=str(exc))
        return {"sent": 0, "channel": channel, "error": str(exc)}

    for alert_id, _, _ in pending:
        await repository.update_alert_status(db, alert_id, "sent")
    logger.info("alert.combined_email_sent", count=len(pending))
    return {"sent": len(pending), "channel": channel, "error": None}


def _format_source_failure_body(source: dict, error_message: str) -> str:
    return "\n".join(
        [
            f"Instaply has stopped receiving jobs from {source.get('company_name')}.",
            "",
            f"Source URL: {source.get('source_url')}",
            f"Provider: {source.get('provider')}",
            f"Consecutive failures: {source.get('consecutive_error_count', 0) + 1}",
            f"Last error: {error_message}",
            "",
            "The source is now marked degraded and will be retried at a slower",
            "cadence. New postings from this company will NOT be detected until",
            "it recovers. Check the Sources tab to test or fix it:",
            f"http://127.0.0.1:{settings.port}/app#sources",
        ]
    )


async def send_source_failure_alert(source: dict, error_message: str) -> None:
    """Notify the user that a source has degraded and polling is unreliable.

    Sent once per outage (on the transition into 'degraded'). Falls back to
    a log warning when SMTP is not configured — the Sources tab still shows
    the degraded status in-app.
    """
    if not settings.smtp_configured:
        logger.warning(
            "alert.source_degraded",
            source_id=source.get("id"),
            company=source.get("company_name"),
            error=error_message,
        )
        return

    message = EmailMessage()
    message["From"] = settings.smtp_from_email or settings.smtp_username
    message["To"] = settings.alert_to_email
    message["Subject"] = (
        f"Instaply source degraded: {source.get('company_name')} is failing"
    )
    message.set_content(_format_source_failure_body(source, error_message))

    try:
        await aiosmtplib.send(
            message,
            hostname=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_username,
            password=settings.smtp_password,
            start_tls=True,
        )
        logger.info("alert.source_degraded_email_sent", source_id=source.get("id"))
    except Exception as exc:
        logger.error(
            "alert.source_degraded_email_failed",
            source_id=source.get("id"),
            error=str(exc),
        )


async def create_and_send_alert(
    db: aiosqlite.Connection,
    *,
    match_result: dict,
    job: dict,
    force_channel: str | None = None,
) -> str:
    """Create an idempotent alert and deliver it if possible."""
    channel = force_channel or choose_alert_channel()
    key = build_idempotency_key(
        user_id=match_result["user_id"],
        match_result_id=match_result["id"],
        channel=channel,
    )
    alert_id = await repository.create_alert(
        db,
        user_id=match_result["user_id"],
        match_result_id=match_result["id"],
        channel=channel,
        idempotency_key=key,
    )

    if channel == "in_app":
        await repository.update_alert_status(db, alert_id, "sent")
        logger.info(
            "alert.in_app_recorded",
            alert_id=alert_id,
            score=match_result["score"],
            title=job["title"],
        )
        return alert_id

    try:
        await _send_email(match_result, job)
        await repository.update_alert_status(db, alert_id, "sent")
        logger.info("alert.email_sent", alert_id=alert_id)
    except Exception as exc:
        await repository.update_alert_status(db, alert_id, "failed", str(exc))
        logger.error("alert.email_failed", alert_id=alert_id, error=str(exc))

    return alert_id

