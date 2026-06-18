"""Alert repository."""

from __future__ import annotations

import json
import uuid
from typing import Any

import aiosqlite
import structlog

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


def _row_to_alert(row: aiosqlite.Row) -> dict:
    data = dict(row)
    data["matching_reasons"] = _json_loads(data.get("matching_reasons"), [])
    data["missing_requirements"] = _json_loads(data.get("missing_requirements"), [])
    return data


async def get_alert_by_idempotency_key(
    db: aiosqlite.Connection,
    idempotency_key: str,
) -> dict | None:
    """Fetch an alert by idempotency key."""
    cursor = await db.execute(
        "SELECT * FROM alerts WHERE idempotency_key = ?",
        (idempotency_key,),
    )
    row = await cursor.fetchone()
    return dict(row) if row else None


async def create_alert(
    db: aiosqlite.Connection,
    *,
    user_id: str,
    match_result_id: str,
    channel: str,
    idempotency_key: str,
) -> str:
    """Create a pending alert unless one already exists."""
    alert_id = uuid.uuid4().hex
    # INSERT OR IGNORE leans on the UNIQUE idempotency_key constraint so a
    # concurrent caller can't slip between a lookup and the insert.
    cursor = await db.execute(
        """
        INSERT OR IGNORE INTO alerts (
            id, user_id, match_result_id, channel, status, idempotency_key
        ) VALUES (?, ?, ?, ?, 'pending', ?)
        """,
        (alert_id, user_id, match_result_id, channel, idempotency_key),
    )
    await db.commit()
    if cursor.rowcount == 0:
        existing = await get_alert_by_idempotency_key(db, idempotency_key)
        return existing["id"]
    logger.info("alert.created", alert_id=alert_id, channel=channel)
    return alert_id


async def update_alert_status(
    db: aiosqlite.Connection,
    alert_id: str,
    status: str,
    failure_message: str | None = None,
) -> None:
    """Update alert delivery status."""
    if status == "sent":
        await db.execute(
            """
            UPDATE alerts
            SET status = ?,
                sent_at = CURRENT_TIMESTAMP,
                failure_message = NULL
            WHERE id = ?
            """,
            (status, alert_id),
        )
    else:
        await db.execute(
            """
            UPDATE alerts
            SET status = ?,
                failure_message = ?
            WHERE id = ?
            """,
            (status, failure_message, alert_id),
        )
    await db.commit()


async def list_alerts(
    db: aiosqlite.Connection,
    user_id: str,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    """List alerts with joined match and job context."""
    base_sql = """
        SELECT
            a.*,
            mr.summary AS match_summary,
            mr.score AS score,
            mr.matching_reasons AS matching_reasons,
            mr.missing_requirements AS missing_requirements,
            jp.title AS job_title,
            jp.company_name AS company_name,
            jp.canonical_url AS job_url
        FROM alerts a
        JOIN match_results mr ON mr.id = a.match_result_id
        JOIN job_postings jp ON jp.id = mr.job_posting_id
        WHERE a.user_id = ?
    """
    params: list[Any] = [user_id]
    if status:
        base_sql += " AND a.status = ?"
        params.append(status)
    base_sql += " ORDER BY a.created_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    cursor = await db.execute(base_sql, params)
    rows = await cursor.fetchall()
    return [_row_to_alert(row) for row in rows]


async def list_undigested_matches(
    db: aiosqlite.Connection,
    user_id: str,
    lookback_days: int,
) -> list[dict]:
    """List digest-decision matches that have never been delivered in any alert."""
    cursor = await db.execute(
        """
        SELECT
            mr.id,
            mr.user_id,
            mr.score,
            mr.summary,
            jp.title AS job_title,
            jp.company_name AS company_name,
            jp.canonical_url AS job_url
        FROM match_results mr
        JOIN job_postings jp ON jp.id = mr.job_posting_id
        LEFT JOIN alerts a ON a.match_result_id = mr.id
        WHERE mr.user_id = ?
          AND mr.decision = 'digest'
          AND a.id IS NULL
          AND mr.created_at >= datetime('now', ?)
        ORDER BY mr.score DESC, mr.created_at DESC
        """,
        (user_id, f"-{int(lookback_days)} days"),
    )
    rows = await cursor.fetchall()
    return [dict(row) for row in rows]


async def get_alert(
    db: aiosqlite.Connection,
    alert_id: str,
    user_id: str,
) -> dict | None:
    """Fetch one alert with joined match and job context."""
    cursor = await db.execute(
        """
        SELECT
            a.*,
            mr.summary AS match_summary,
            mr.score AS score,
            mr.matching_reasons AS matching_reasons,
            mr.missing_requirements AS missing_requirements,
            jp.title AS job_title,
            jp.company_name AS company_name,
            jp.canonical_url AS job_url
        FROM alerts a
        JOIN match_results mr ON mr.id = a.match_result_id
        JOIN job_postings jp ON jp.id = mr.job_posting_id
        WHERE a.id = ? AND a.user_id = ?
        """,
        (alert_id, user_id),
    )
    row = await cursor.fetchone()
    return _row_to_alert(row) if row else None

