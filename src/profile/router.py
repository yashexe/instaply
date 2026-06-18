"""
Profile API router.

Endpoints for resume upload/parsing, active profile retrieval,
and version listing.
"""

import json

import structlog
from fastapi import APIRouter, Depends, HTTPException

import aiosqlite

from src.db.connection import get_db
from src.profile.models import ProfileResponse, ResumeInput, StructuredProfile
from src.profile.parser import parse_resume
from src.profile import repository

logger = structlog.get_logger()

router = APIRouter(prefix="/api/profile", tags=["profile"])

DEFAULT_USER_ID = "default"


@router.post("/resume", response_model=ProfileResponse)
async def upload_resume(
    body: ResumeInput,
    db: aiosqlite.Connection = Depends(get_db),
) -> ProfileResponse:
    """Upload and parse a resume.

    Parses the resume text with the configured LLM, stores a new
    versioned profile, and returns the result.
    """
    logger.info("profile.upload_resume", text_len=len(body.resume_text))

    # Parse resume with LLM
    structured = await parse_resume(body.resume_text)

    # Determine next version
    version = await repository.get_next_version(db, DEFAULT_USER_ID)

    # Persist
    structured_json = structured.model_dump_json()
    profile_id = await repository.create_profile(
        db=db,
        user_id=DEFAULT_USER_ID,
        resume_text=body.resume_text,
        structured_profile_json=structured_json,
        version=version,
    )

    # Fetch the newly created profile
    profile = await repository.get_active_profile(db, DEFAULT_USER_ID)
    if profile is None:
        raise HTTPException(status_code=500, detail="Failed to create profile")

    return ProfileResponse(
        id=profile["id"],
        user_id=profile["user_id"],
        version=profile["version"],
        structured_profile=StructuredProfile.model_validate(profile["structured_profile"])
        if profile["structured_profile"]
        else None,
        is_active=profile["is_active"],
        created_at=str(profile["created_at"]),
    )


@router.get("", response_model=ProfileResponse)
async def get_profile(
    db: aiosqlite.Connection = Depends(get_db),
) -> ProfileResponse:
    """Get the currently active profile."""
    profile = await repository.get_active_profile(db, DEFAULT_USER_ID)
    if profile is None:
        raise HTTPException(status_code=404, detail="No active profile found")

    return ProfileResponse(
        id=profile["id"],
        user_id=profile["user_id"],
        version=profile["version"],
        structured_profile=StructuredProfile.model_validate(profile["structured_profile"])
        if profile["structured_profile"]
        else None,
        is_active=profile["is_active"],
        created_at=str(profile["created_at"]),
    )


@router.get("/versions", response_model=list[ProfileResponse])
async def list_profile_versions(
    db: aiosqlite.Connection = Depends(get_db),
) -> list[ProfileResponse]:
    """List all profile versions for the current user."""
    profiles = await repository.get_profile_versions(db, DEFAULT_USER_ID)

    return [
        ProfileResponse(
            id=p["id"],
            user_id=p["user_id"],
            version=p["version"],
            structured_profile=StructuredProfile.model_validate(p["structured_profile"])
            if p["structured_profile"]
            else None,
            is_active=p["is_active"],
            created_at=str(p["created_at"]),
        )
        for p in profiles
    ]
