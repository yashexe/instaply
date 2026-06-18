"""
Match results — database operations.

All queries use aiosqlite with raw SQL.  JSON fields are serialized
via json.dumps / json.loads.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import aiosqlite
import structlog

logger = structlog.get_logger()


def _serialize_json(value: Any) -> str | None:
    """Serialize a Python value to a JSON string for storage."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value)


def _deserialize_row(row: aiosqlite.Row) -> dict:
    """Convert an aiosqlite.Row to a plain dict with JSON fields decoded."""
    d = dict(row)
    json_fields = (
        "hard_filter_results",
        "score_breakdown",
        "matching_reasons",
        "missing_requirements",
        "uncertainties",
        "trace",
    )
    for field in json_fields:
        raw = d.get(field)
        if raw and isinstance(raw, str):
            try:
                d[field] = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                pass
    return d


async def create_match_result(db: aiosqlite.Connection, result: dict) -> str:
    """Insert a new match result and return its ID."""
    match_id = result.get("id") or uuid.uuid4().hex

    await db.execute(
        """
        INSERT INTO match_results (
            id, user_id, candidate_profile_id, job_posting_id,
            score, decision,
            hard_filter_results, score_breakdown,
            matching_reasons, missing_requirements, uncertainties,
            summary, trace, cover_letter
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            match_id,
            result["user_id"],
            result["candidate_profile_id"],
            result["job_posting_id"],
            result["score"],
            result["decision"],
            _serialize_json(result.get("hard_filter_results")),
            _serialize_json(result.get("score_breakdown")),
            _serialize_json(result.get("matching_reasons")),
            _serialize_json(result.get("missing_requirements")),
            _serialize_json(result.get("uncertainties")),
            result.get("summary"),
            _serialize_json(result.get("trace")),
            result.get("cover_letter"),
        ),
    )
    await db.commit()

    logger.info(
        "match.created",
        match_id=match_id,
        decision=result["decision"],
        score=result["score"],
    )
    return match_id


async def update_match_result(
    db: aiosqlite.Connection, match_id: str, result: dict,
) -> None:
    """Recompute an existing match result in place.

    Preserves the row id and created_at (and therefore alert and user-action
    history) while replacing the score, decision, and explanations.
    """
    await db.execute(
        """
        UPDATE match_results
        SET candidate_profile_id = ?,
            score = ?,
            decision = ?,
            hard_filter_results = ?,
            score_breakdown = ?,
            matching_reasons = ?,
            missing_requirements = ?,
            uncertainties = ?,
            summary = ?,
            trace = ?,
            cover_letter = ?
        WHERE id = ?
        """,
        (
            result["candidate_profile_id"],
            result["score"],
            result["decision"],
            _serialize_json(result.get("hard_filter_results")),
            _serialize_json(result.get("score_breakdown")),
            _serialize_json(result.get("matching_reasons")),
            _serialize_json(result.get("missing_requirements")),
            _serialize_json(result.get("uncertainties")),
            result.get("summary"),
            _serialize_json(result.get("trace")),
            result.get("cover_letter"),
            match_id,
        ),
    )
    await db.commit()

    logger.info(
        "match.updated",
        match_id=match_id,
        decision=result["decision"],
        score=result["score"],
    )


async def get_match_result(
    db: aiosqlite.Connection, match_id: str,
) -> dict | None:
    """Fetch a single match result by ID."""
    cursor = await db.execute(
        "SELECT * FROM match_results WHERE id = ?", (match_id,),
    )
    row = await cursor.fetchone()
    return _deserialize_row(row) if row else None


def _like_pattern(query: str) -> str:
    """Build a LIKE pattern with wildcards in the user input escaped."""
    escaped = (
        query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    )
    return f"%{escaped}%"


async def list_match_results(
    db: aiosqlite.Connection,
    user_id: str,
    decision: str | None = None,
    q: str | None = None,
    min_score: int | None = None,
    sort: str = "recent",
    limit: int = 50,
    offset: int = 0,
    exclude_rejected: bool = False,
) -> list[dict]:
    """List match results for a user, optionally filtered.

    q searches the matched job's title and company. sort is 'recent'
    (newest first, default) or 'score' (highest first).
    """
    conditions = ["mr.user_id = ?"]
    params: list = [user_id]

    if decision:
        conditions.append("mr.decision = ?")
        params.append(decision)
    if exclude_rejected:
        conditions.append("mr.decision != 'rejected'")
    if q:
        conditions.append(
            "(jp.title LIKE ? ESCAPE '\\' OR jp.company_name LIKE ? ESCAPE '\\')"
        )
        pattern = _like_pattern(q)
        params.extend([pattern, pattern])
    if min_score is not None:
        conditions.append("mr.score >= ?")
        params.append(min_score)

    order = (
        "mr.score DESC, mr.created_at DESC"
        if sort == "score"
        else "mr.created_at DESC"
    )
    cursor = await db.execute(
        f"""
        SELECT mr.*
        FROM match_results mr
        JOIN job_postings jp ON jp.id = mr.job_posting_id
        WHERE {' AND '.join(conditions)}
        ORDER BY {order}
        LIMIT ? OFFSET ?
        """,
        (*params, limit, offset),
    )
    rows = await cursor.fetchall()
    return [_deserialize_row(r) for r in rows]


async def match_exists(
    db: aiosqlite.Connection,
    user_id: str,
    profile_id: str,
    job_id: str,
) -> bool:
    """Check if a match already exists for this user/profile/job combo."""
    cursor = await db.execute(
        """
        SELECT 1 FROM match_results
        WHERE user_id = ?
          AND candidate_profile_id = ?
          AND job_posting_id = ?
        LIMIT 1
        """,
        (user_id, profile_id, job_id),
    )
    return (await cursor.fetchone()) is not None


async def list_active_job_ids(
    db: aiosqlite.Connection,
    limit: int | None = None,
) -> list[str]:
    """List all active job posting ids, newest first."""
    sql = "SELECT id FROM job_postings WHERE status = 'active' ORDER BY first_seen_at DESC"
    params: list = []
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)
    cursor = await db.execute(sql, params)
    rows = await cursor.fetchall()
    return [row[0] for row in rows]


async def list_unscored_job_ids(
    db: aiosqlite.Connection,
    user_id: str,
    profile_id: str,
    limit: int | None = None,
) -> list[str]:
    """List active job postings with no match result for this user/profile."""
    sql = """
        SELECT j.id FROM job_postings j
        WHERE j.status = 'active'
          AND NOT EXISTS (
            SELECT 1 FROM match_results m
            WHERE m.job_posting_id = j.id
              AND m.user_id = ?
              AND m.candidate_profile_id = ?
          )
        ORDER BY j.first_seen_at DESC
        """
    params: list = [user_id, profile_id]
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)
    cursor = await db.execute(sql, params)
    rows = await cursor.fetchall()
    return [row[0] for row in rows]


async def get_match_for_job(
    db: aiosqlite.Connection,
    user_id: str,
    job_id: str,
) -> dict | None:
    """Get the match result for a specific job posting."""
    cursor = await db.execute(
        """
        SELECT * FROM match_results
        WHERE user_id = ? AND job_posting_id = ?
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (user_id, job_id),
    )
    row = await cursor.fetchone()
    return _deserialize_row(row) if row else None
