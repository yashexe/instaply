"""Source repository and health utilities."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

import aiosqlite
import structlog

from src.config import settings
from src.db.connection import get_db

logger = structlog.get_logger()


def _json_loads(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


def _row_to_source(row: aiosqlite.Row) -> dict:
    data = dict(row)
    data["adapter_config"] = _json_loads(data.get("adapter_config"), {})
    return data


def default_interval_for_priority(priority: str) -> int:
    """Map source priority to a polling interval."""
    if priority == "high":
        return settings.high_priority_poll_interval
    if priority == "low":
        return max(settings.normal_poll_interval * 2, settings.normal_poll_interval)
    return settings.normal_poll_interval


async def create_source(
    db: aiosqlite.Connection,
    user_id: str,
    *,
    company_name: str,
    provider: str,
    source_url: str,
    normalized_url: str,
    priority: str,
    adapter_config: dict | None = None,
) -> str:
    """Create a monitored source."""
    source_id = uuid.uuid4().hex
    await db.execute(
        """
        INSERT INTO sources (
            id, user_id, company_name, provider, source_url, normalized_url,
            priority, status, fetch_interval_seconds, adapter_config
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)
        """,
        (
            source_id,
            user_id,
            company_name,
            provider,
            source_url,
            normalized_url,
            priority,
            default_interval_for_priority(priority),
            json.dumps(adapter_config or {}),
        ),
    )
    await db.commit()
    logger.info("source.created", source_id=source_id, provider=provider)
    return source_id


async def get_source(
    db: aiosqlite.Connection,
    source_id: str,
    user_id: str | None = None,
) -> dict | None:
    """Fetch one source by ID."""
    if user_id:
        cursor = await db.execute(
            "SELECT * FROM sources WHERE id = ? AND user_id = ?",
            (source_id, user_id),
        )
    else:
        cursor = await db.execute("SELECT * FROM sources WHERE id = ?", (source_id,))
    row = await cursor.fetchone()
    return _row_to_source(row) if row else None


async def list_sources(
    db: aiosqlite.Connection,
    user_id: str,
    status: str | None = None,
) -> list[dict]:
    """List sources for a user."""
    if status:
        cursor = await db.execute(
            """
            SELECT *
            FROM sources
            WHERE user_id = ? AND status = ?
            ORDER BY priority, company_name
            """,
            (user_id, status),
        )
    else:
        cursor = await db.execute(
            """
            SELECT *
            FROM sources
            WHERE user_id = ?
            ORDER BY status, priority, company_name
            """,
            (user_id,),
        )
    rows = await cursor.fetchall()
    return [_row_to_source(row) for row in rows]


DEGRADED_RETRY_MULTIPLIER = 4


async def list_due_sources(db: aiosqlite.Connection) -> list[dict]:
    """List sources whose polling interval has elapsed.

    Degraded sources are retried at a slowed cadence (since their last
    attempt) so a transient outage longer than the escalation threshold
    does not silence a source forever.
    """
    cursor = await db.execute(
        """
        SELECT *
        FROM sources
        WHERE (
            status = 'active'
            AND (
              last_success_at IS NULL
              OR datetime(last_success_at, '+' || fetch_interval_seconds || ' seconds') <= CURRENT_TIMESTAMP
            )
          )
          OR (
            status = 'degraded'
            AND datetime(
              COALESCE(last_error_at, last_success_at, created_at),
              '+' || (fetch_interval_seconds * ?) || ' seconds'
            ) <= CURRENT_TIMESTAMP
          )
        ORDER BY last_success_at IS NULL DESC, last_success_at ASC
        """,
        (DEGRADED_RETRY_MULTIPLIER,),
    )
    rows = await cursor.fetchall()
    return [_row_to_source(row) for row in rows]


async def update_source(
    db: aiosqlite.Connection,
    source_id: str,
    user_id: str,
    updates: dict,
) -> dict | None:
    """Update mutable source fields."""
    existing = await get_source(db, source_id, user_id)
    if existing is None:
        return None

    company_name = updates.get("company_name") or existing["company_name"]
    priority = updates.get("priority") or existing["priority"]
    status = updates.get("status") or existing["status"]
    interval = default_interval_for_priority(priority)

    await db.execute(
        """
        UPDATE sources
        SET company_name = ?,
            priority = ?,
            status = ?,
            fetch_interval_seconds = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ? AND user_id = ?
        """,
        (company_name, priority, status, interval, source_id, user_id),
    )
    await db.commit()
    return await get_source(db, source_id, user_id)


async def delete_source(
    db: aiosqlite.Connection,
    source_id: str,
    user_id: str,
) -> bool:
    """Delete a source and cascading jobs."""
    cursor = await db.execute(
        "DELETE FROM sources WHERE id = ? AND user_id = ?",
        (source_id, user_id),
    )
    await db.commit()
    return cursor.rowcount > 0


async def mark_source_success(
    db: aiosqlite.Connection,
    source_id: str,
) -> None:
    """Mark a source fetch as successful."""
    await db.execute(
        """
        UPDATE sources
        SET last_success_at = CURRENT_TIMESTAMP,
            last_error_at = NULL,
            last_error_message = NULL,
            consecutive_error_count = 0,
            status = CASE WHEN status = 'degraded' THEN 'active' ELSE status END,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (source_id,),
    )
    await db.commit()


async def mark_source_failure(
    db: aiosqlite.Connection,
    source_id: str,
    message: str,
) -> bool:
    """Mark a source fetch as failed.

    Returns True when this failure pushed the source over the escalation
    threshold into 'degraded' (i.e. it was not degraded before), so the
    caller can notify the user exactly once per outage.
    """
    threshold = settings.source_failure_escalation_threshold
    existing = await get_source(db, source_id)
    if existing is None:
        return False

    await db.execute(
        """
        UPDATE sources
        SET last_error_at = CURRENT_TIMESTAMP,
            last_error_message = ?,
            consecutive_error_count = consecutive_error_count + 1,
            status = CASE
                WHEN consecutive_error_count + 1 >= ? THEN 'degraded'
                ELSE status
            END,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (message[:1000], threshold, source_id),
    )
    await db.commit()

    just_degraded = (
        existing["status"] != "degraded"
        and existing["consecutive_error_count"] + 1 >= threshold
    )
    return just_degraded


async def check_source_health() -> None:
    """Mark stale failing sources as degraded."""
    db = await get_db()
    cursor = await db.execute(
        """
        UPDATE sources
        SET status = 'degraded',
            updated_at = CURRENT_TIMESTAMP
        WHERE status = 'active'
          AND consecutive_error_count >= ?
        """,
        (settings.source_failure_escalation_threshold,),
    )
    await db.commit()
    if cursor.rowcount:
        logger.warning("source.health_degraded", count=cursor.rowcount)


def utc_now_iso() -> str:
    """Return current UTC time as an ISO string."""
    return datetime.now(timezone.utc).isoformat()

