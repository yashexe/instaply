"""Repository for discovered companies (discovery staging table)."""

from __future__ import annotations

import json
import uuid
from typing import Any

import aiosqlite
import structlog

logger = structlog.get_logger()

TERMINAL_STATUSES = {"accepted", "rejected"}
RECHECKABLE_STATUSES = {"not_found", "irrelevant"}


def _row_to_suggestion(row: aiosqlite.Row) -> dict:
    data = dict(row)
    try:
        data["matching_titles"] = json.loads(data.get("matching_titles") or "[]")
    except (TypeError, json.JSONDecodeError):
        data["matching_titles"] = []
    return data


async def insert_discovered(
    db: aiosqlite.Connection,
    user_id: str,
    *,
    company_name: str,
    name_key: str,
    status: str,
    origin: str,
    provider: str | None = None,
    slug: str | None = None,
    board_url: str | None = None,
    normalized_url: str | None = None,
    reason: str | None = None,
    job_count: int = 0,
    matching_titles: list[str] | None = None,
) -> str | None:
    """Insert a discovered company; returns its id, or None if the
    name_key already exists for this user (dedupe backstop)."""
    discovered_id = uuid.uuid4().hex
    cursor = await db.execute(
        """
        INSERT INTO discovered_companies (
            id, user_id, company_name, name_key, provider, slug,
            board_url, normalized_url, status, origin, reason,
            job_count, matching_titles, last_probed_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(user_id, name_key) DO NOTHING
        """,
        (
            discovered_id,
            user_id,
            company_name,
            name_key,
            provider,
            slug,
            board_url,
            normalized_url,
            status,
            origin,
            reason,
            job_count,
            json.dumps(matching_titles or []),
        ),
    )
    await db.commit()
    if cursor.rowcount == 0:
        return None
    return discovered_id


async def get_suggestion(
    db: aiosqlite.Connection,
    discovered_id: str,
    user_id: str,
) -> dict | None:
    cursor = await db.execute(
        "SELECT * FROM discovered_companies WHERE id = ? AND user_id = ?",
        (discovered_id, user_id),
    )
    row = await cursor.fetchone()
    return _row_to_suggestion(row) if row else None


async def list_by_status(
    db: aiosqlite.Connection,
    user_id: str,
    status: str,
) -> list[dict]:
    cursor = await db.execute(
        """
        SELECT *
        FROM discovered_companies
        WHERE user_id = ? AND status = ?
        ORDER BY job_count DESC, discovered_at DESC
        """,
        (user_id, status),
    )
    rows = await cursor.fetchall()
    return [_row_to_suggestion(row) for row in rows]


async def count_by_status(
    db: aiosqlite.Connection,
    user_id: str,
    status: str,
) -> int:
    cursor = await db.execute(
        "SELECT COUNT(*) FROM discovered_companies WHERE user_id = ? AND status = ?",
        (user_id, status),
    )
    row = await cursor.fetchone()
    return row[0] if row else 0


async def known_name_keys(db: aiosqlite.Connection, user_id: str) -> set[str]:
    """All name_keys this user has any record for, EXCEPT rows whose
    recheck window has lapsed (not_found/irrelevant older than the
    recheck cutoff), which become probeable again."""
    from src.config import settings

    cursor = await db.execute(
        """
        SELECT name_key
        FROM discovered_companies
        WHERE user_id = ?
          AND (
            status IN ('suggested', 'accepted', 'rejected')
            OR datetime(COALESCE(last_probed_at, discovered_at), '+' || ? || ' days')
               > CURRENT_TIMESTAMP
          )
        """,
        (user_id, settings.discovery_recheck_days),
    )
    rows = await cursor.fetchall()
    return {row[0] for row in rows}


async def set_status(
    db: aiosqlite.Connection,
    discovered_id: str,
    user_id: str,
    status: str,
    *,
    source_id: str | None = None,
) -> dict | None:
    """Transition a suggestion to a decision status."""
    await db.execute(
        """
        UPDATE discovered_companies
        SET status = ?,
            source_id = COALESCE(?, source_id),
            decided_at = CURRENT_TIMESTAMP
        WHERE id = ? AND user_id = ?
        """,
        (status, source_id, discovered_id, user_id),
    )
    await db.commit()
    return await get_suggestion(db, discovered_id, user_id)


async def reprobe_update(
    db: aiosqlite.Connection,
    user_id: str,
    name_key: str,
    *,
    status: str,
    provider: str | None,
    slug: str | None,
    board_url: str | None,
    normalized_url: str | None,
    job_count: int,
    matching_titles: list[str],
) -> None:
    """Refresh an existing recheckable row after a new probe."""
    await db.execute(
        """
        UPDATE discovered_companies
        SET status = ?,
            provider = ?,
            slug = ?,
            board_url = ?,
            normalized_url = ?,
            job_count = ?,
            matching_titles = ?,
            last_probed_at = CURRENT_TIMESTAMP
        WHERE user_id = ? AND name_key = ?
          AND status IN ('not_found', 'irrelevant')
        """,
        (
            status,
            provider,
            slug,
            board_url,
            normalized_url,
            job_count,
            json.dumps(matching_titles),
            user_id,
            name_key,
        ),
    )
    await db.commit()


def to_response_dict(suggestion: dict) -> dict[str, Any]:
    """Trim a row dict to the SuggestionResponse fields."""
    return {
        "id": suggestion["id"],
        "company_name": suggestion["company_name"],
        "provider": suggestion.get("provider"),
        "slug": suggestion.get("slug"),
        "board_url": suggestion.get("board_url"),
        "status": suggestion["status"],
        "origin": suggestion["origin"],
        "reason": suggestion.get("reason"),
        "job_count": suggestion.get("job_count") or 0,
        "matching_titles": suggestion.get("matching_titles") or [],
        "source_id": suggestion.get("source_id"),
        "discovered_at": suggestion.get("discovered_at"),
        "decided_at": suggestion.get("decided_at"),
    }
