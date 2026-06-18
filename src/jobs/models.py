"""Pydantic models for job postings and user actions."""

from pydantic import BaseModel, Field


class JobPostingResponse(BaseModel):
    """API response for a normalized job posting."""

    id: str
    source_id: str
    provider: str | None = None
    provider_job_id: str | None = None
    company_name: str
    title: str
    canonical_url: str | None = None
    locations: list[str] = Field(default_factory=list)
    remote_policy: str = "unknown"
    employment_type: str = "unknown"
    department: str | None = None
    description_text: str | None = None
    salary_min: int | None = None
    salary_max: int | None = None
    salary_currency: str | None = None
    visa_sponsorship: str = "unknown"
    posted_at: str | None = None
    provider_updated_at: str | None = None
    first_seen_at: str | None = None
    last_seen_at: str | None = None
    status: str = "active"
    created_at: str | None = None
    updated_at: str | None = None
    # Latest match result for this job, when one exists
    match_score: int | None = None
    match_decision: str | None = None


class UserJobActionInput(BaseModel):
    """Request body for saving feedback on a job."""

    action: str
    feedback: str | None = None


class UserJobActionResponse(BaseModel):
    """Response for a saved user job action."""

    id: str
    user_id: str
    job_posting_id: str
    action: str
    feedback: str | None = None
    created_at: str | None = None


class UserJobActionDetail(BaseModel):
    """A job's latest user action, joined with job details."""

    id: str
    job_posting_id: str
    action: str
    feedback: str | None = None
    created_at: str | None = None
    job_title: str
    company_name: str
    canonical_url: str | None = None
    locations: list[str] = Field(default_factory=list)
    remote_policy: str = "unknown"
    salary_min: int | None = None
    salary_max: int | None = None
    salary_currency: str | None = None

