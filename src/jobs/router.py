"""Jobs API router."""

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, Query

from src.db.connection import get_db
from src.jobs import repository
from src.jobs.models import (
    JobPostingResponse,
    UserJobActionDetail,
    UserJobActionInput,
    UserJobActionResponse,
)

router = APIRouter(prefix="/api/jobs", tags=["jobs"])

DEFAULT_USER_ID = "default"


def _to_job_response(job: dict) -> JobPostingResponse:
    return JobPostingResponse(
        id=job["id"],
        source_id=job["source_id"],
        provider=job.get("provider"),
        provider_job_id=job.get("provider_job_id"),
        company_name=job["company_name"],
        title=job["title"],
        canonical_url=job.get("canonical_url"),
        locations=job.get("locations") or [],
        remote_policy=job.get("remote_policy") or "unknown",
        employment_type=job.get("employment_type") or "unknown",
        department=job.get("department"),
        description_text=job.get("description_text"),
        salary_min=job.get("salary_min"),
        salary_max=job.get("salary_max"),
        salary_currency=job.get("salary_currency"),
        visa_sponsorship=job.get("visa_sponsorship") or "unknown",
        posted_at=str(job["posted_at"]) if job.get("posted_at") else None,
        provider_updated_at=str(job["provider_updated_at"]) if job.get("provider_updated_at") else None,
        first_seen_at=str(job["first_seen_at"]) if job.get("first_seen_at") else None,
        last_seen_at=str(job["last_seen_at"]) if job.get("last_seen_at") else None,
        status=job.get("status") or "active",
        created_at=str(job["created_at"]) if job.get("created_at") else None,
        updated_at=str(job["updated_at"]) if job.get("updated_at") else None,
        match_score=job.get("match_score"),
        match_decision=job.get("match_decision"),
    )


@router.get("", response_model=list[JobPostingResponse])
async def list_jobs(
    source_id: str | None = Query(default=None),
    q: str | None = Query(default=None, max_length=200),
    remote_policy: str | None = Query(default=None),
    sort: str = Query(default="newest", pattern="^(newest|oldest|posted|title|company)$"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: aiosqlite.Connection = Depends(get_db),
) -> list[JobPostingResponse]:
    """List normalized job postings, with optional search and sort."""
    jobs = await repository.list_jobs(
        db,
        source_id=source_id,
        q=q.strip() if q else None,
        remote_policy=remote_policy,
        sort=sort,
        limit=limit,
        offset=offset,
    )
    return [_to_job_response(job) for job in jobs]


@router.get("/actions", response_model=list[UserJobActionDetail])
async def list_job_actions(
    db: aiosqlite.Connection = Depends(get_db),
) -> list[UserJobActionDetail]:
    """List each job's latest user action with job details."""
    actions = await repository.list_latest_user_actions(db, DEFAULT_USER_ID)
    return [
        UserJobActionDetail(
            id=action["id"],
            job_posting_id=action["job_posting_id"],
            action=action["action"],
            feedback=action.get("feedback"),
            created_at=str(action["created_at"]) if action.get("created_at") else None,
            job_title=action["job_title"],
            company_name=action["company_name"],
            canonical_url=action.get("canonical_url"),
            locations=action.get("locations") or [],
            remote_policy=action.get("remote_policy") or "unknown",
            salary_min=action.get("salary_min"),
            salary_max=action.get("salary_max"),
            salary_currency=action.get("salary_currency"),
        )
        for action in actions
    ]


@router.get("/{job_id}", response_model=JobPostingResponse)
async def get_job(
    job_id: str,
    db: aiosqlite.Connection = Depends(get_db),
) -> JobPostingResponse:
    """Get a single normalized job posting."""
    job = await repository.get_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return _to_job_response(job)


@router.post("/{job_id}/actions", response_model=UserJobActionResponse)
async def create_job_action(
    job_id: str,
    body: UserJobActionInput,
    db: aiosqlite.Connection = Depends(get_db),
) -> UserJobActionResponse:
    """Save user feedback for a job."""
    job = await repository.get_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    action = await repository.create_user_action(
        db,
        DEFAULT_USER_ID,
        job_id,
        body.action,
        body.feedback,
    )
    return UserJobActionResponse(
        id=action["id"],
        user_id=action["user_id"],
        job_posting_id=action["job_posting_id"],
        action=action["action"],
        feedback=action.get("feedback"),
        created_at=str(action["created_at"]) if action.get("created_at") else None,
    )

