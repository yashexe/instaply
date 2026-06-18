"""Matching API router."""

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, Query

from src.db.connection import get_db
from src.jobs import repository as jobs_repository
from src.matching import repository, service
from src.matching.models import MatchResultResponse

router = APIRouter(prefix="/api/matches", tags=["matching"])

DEFAULT_USER_ID = "default"


def _to_response(match: dict, job: dict | None = None) -> MatchResultResponse:
    return MatchResultResponse(
        id=match["id"],
        user_id=match["user_id"],
        candidate_profile_id=match["candidate_profile_id"],
        job_posting_id=match["job_posting_id"],
        score=match["score"],
        decision=match["decision"],
        hard_filter_results=match.get("hard_filter_results") or {},
        score_breakdown=match.get("score_breakdown") or {},
        matching_reasons=match.get("matching_reasons") or [],
        missing_requirements=match.get("missing_requirements") or [],
        uncertainties=match.get("uncertainties") or [],
        summary=match.get("summary"),
        cover_letter=match.get("cover_letter"),
        trace=match.get("trace") or {},
        created_at=str(match["created_at"]) if match.get("created_at") else None,
        job_title=job.get("title") if job else None,
        company_name=job.get("company_name") if job else None,
        job_url=job.get("canonical_url") if job else None,
        posted_at=str(job["posted_at"]) if job and job.get("posted_at") else None,
        provider_updated_at=str(job["provider_updated_at"]) if job and job.get("provider_updated_at") else None,
        first_seen_at=str(job["first_seen_at"]) if job and job.get("first_seen_at") else None,
    )


@router.post("/jobs/{job_id}", response_model=MatchResultResponse)
async def score_job(
    job_id: str,
    send_alerts: bool = Query(default=True),
    db: aiosqlite.Connection = Depends(get_db),
) -> MatchResultResponse:
    """Score a job against the active profile."""
    match = await service.score_job_for_user(
        db,
        job_id,
        DEFAULT_USER_ID,
        send_alerts=send_alerts,
    )
    if match is None:
        raise HTTPException(
            status_code=404,
            detail="Job or active profile not found",
        )
    job = await jobs_repository.get_job(db, job_id)
    return _to_response(match, job)


@router.get("", response_model=list[MatchResultResponse])
async def list_matches(
    decision: str | None = Query(default=None),
    q: str | None = Query(default=None, max_length=200),
    min_score: int | None = Query(default=None, ge=0, le=100),
    sort: str = Query(default="recent", pattern="^(recent|score)$"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    exclude_rejected: bool = Query(default=False),
    db: aiosqlite.Connection = Depends(get_db),
) -> list[MatchResultResponse]:
    """List match results, with optional search, score floor, and sort."""
    matches = await repository.list_match_results(
        db,
        DEFAULT_USER_ID,
        decision=decision,
        q=q.strip() if q else None,
        min_score=min_score,
        sort=sort,
        limit=limit,
        offset=offset,
        exclude_rejected=exclude_rejected,
    )
    responses: list[MatchResultResponse] = []
    for match in matches:
        job = await jobs_repository.get_job(db, match["job_posting_id"])
        responses.append(_to_response(match, job))
    return responses


@router.get("/{match_id}", response_model=MatchResultResponse)
async def get_match(
    match_id: str,
    db: aiosqlite.Connection = Depends(get_db),
) -> MatchResultResponse:
    """Get one match result."""
    match = await repository.get_match_result(db, match_id)
    if match is None or match["user_id"] != DEFAULT_USER_ID:
        raise HTTPException(status_code=404, detail="Match not found")
    job = await jobs_repository.get_job(db, match["job_posting_id"])
    return _to_response(match, job)

