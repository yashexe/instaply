"""Job preference repository."""

from __future__ import annotations

import json
import uuid
from typing import Any

import aiosqlite
import structlog

from src.config import settings

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


def _json_dumps(value: Any) -> str:
    return json.dumps(value or [])


def _row_to_preferences(row: aiosqlite.Row) -> dict:
    data = dict(row)
    for field in (
        "target_roles",
        "seniority_levels",
        "locations",
        "must_have_skills",
        "nice_to_have_skills",
        "excluded_keywords",
    ):
        data[field] = _json_loads(data.get(field), [])
    data["needs_visa_sponsorship"] = bool(data.get("needs_visa_sponsorship"))
    return data


def default_preferences(user_id: str = "default") -> dict:
    """Return an unsaved default preferences object."""
    return {
        "id": "",
        "user_id": user_id,
        "target_roles": [],
        "seniority_levels": [],
        "locations": [],
        "remote_policy": "any",
        "min_salary": None,
        "salary_currency": None,
        "needs_visa_sponsorship": False,
        "must_have_skills": [],
        "nice_to_have_skills": [],
        "excluded_keywords": [],
        "alert_threshold": settings.default_alert_threshold,
        "created_at": None,
        "updated_at": None,
    }


async def get_preferences(
    db: aiosqlite.Connection,
    user_id: str,
) -> dict | None:
    """Fetch the latest preferences for a user."""
    cursor = await db.execute(
        """
        SELECT *
        FROM job_preferences
        WHERE user_id = ?
        ORDER BY updated_at DESC, created_at DESC
        LIMIT 1
        """,
        (user_id,),
    )
    row = await cursor.fetchone()
    return _row_to_preferences(row) if row else None


async def upsert_preferences(
    db: aiosqlite.Connection,
    user_id: str,
    preferences: dict,
) -> dict:
    """Create or update the user's single preference record."""
    existing = await get_preferences(db, user_id)
    pref_id = existing["id"] if existing else uuid.uuid4().hex
    alert_threshold = (
        preferences.get("alert_threshold")
        if preferences.get("alert_threshold") is not None
        else settings.default_alert_threshold
    )

    values = (
        pref_id,
        user_id,
        _json_dumps(preferences.get("target_roles")),
        _json_dumps(preferences.get("seniority_levels")),
        _json_dumps(preferences.get("locations")),
        preferences.get("remote_policy") or "any",
        preferences.get("min_salary"),
        preferences.get("salary_currency"),
        1 if preferences.get("needs_visa_sponsorship") else 0,
        _json_dumps(preferences.get("must_have_skills")),
        _json_dumps(preferences.get("nice_to_have_skills")),
        _json_dumps(preferences.get("excluded_keywords")),
        alert_threshold,
    )

    if existing:
        await db.execute(
            """
            UPDATE job_preferences
            SET target_roles = ?,
                seniority_levels = ?,
                locations = ?,
                remote_policy = ?,
                min_salary = ?,
                salary_currency = ?,
                needs_visa_sponsorship = ?,
                must_have_skills = ?,
                nice_to_have_skills = ?,
                excluded_keywords = ?,
                alert_threshold = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            values[2:] + (pref_id,),
        )
    else:
        await db.execute(
            """
            INSERT INTO job_preferences (
                id, user_id, target_roles, seniority_levels, locations,
                remote_policy, min_salary, salary_currency,
                needs_visa_sponsorship, must_have_skills, nice_to_have_skills,
                excluded_keywords, alert_threshold
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            values,
        )

    await db.commit()
    logger.info("preferences.saved", user_id=user_id, preferences_id=pref_id)
    saved = await get_preferences(db, user_id)
    if saved is None:
        raise RuntimeError("Failed to save preferences")
    return saved

