"""Job preferences API router."""

import aiosqlite
from fastapi import APIRouter, Depends

from src.db.connection import get_db
from src.preferences.models import JobPreferencesInput, JobPreferencesResponse
from src.preferences import repository

router = APIRouter(prefix="/api/preferences", tags=["preferences"])

DEFAULT_USER_ID = "default"


def _to_response(data: dict) -> JobPreferencesResponse:
    return JobPreferencesResponse(
        id=data["id"],
        user_id=data["user_id"],
        target_roles=data.get("target_roles") or [],
        seniority_levels=data.get("seniority_levels") or [],
        locations=data.get("locations") or [],
        remote_policy=data.get("remote_policy") or "any",
        min_salary=data.get("min_salary"),
        salary_currency=data.get("salary_currency"),
        needs_visa_sponsorship=bool(data.get("needs_visa_sponsorship")),
        must_have_skills=data.get("must_have_skills") or [],
        nice_to_have_skills=data.get("nice_to_have_skills") or [],
        excluded_keywords=data.get("excluded_keywords") or [],
        alert_threshold=data.get("alert_threshold"),
        created_at=str(data["created_at"]) if data.get("created_at") else None,
        updated_at=str(data["updated_at"]) if data.get("updated_at") else None,
    )


@router.get("", response_model=JobPreferencesResponse)
async def get_preferences(
    db: aiosqlite.Connection = Depends(get_db),
) -> JobPreferencesResponse:
    """Get current job preferences, returning defaults if none are saved."""
    prefs = await repository.get_preferences(db, DEFAULT_USER_ID)
    return _to_response(prefs or repository.default_preferences(DEFAULT_USER_ID))


@router.put("", response_model=JobPreferencesResponse)
async def save_preferences(
    body: JobPreferencesInput,
    db: aiosqlite.Connection = Depends(get_db),
) -> JobPreferencesResponse:
    """Create or update job preferences."""
    saved = await repository.upsert_preferences(
        db,
        DEFAULT_USER_ID,
        body.model_dump(),
    )
    return _to_response(saved)

