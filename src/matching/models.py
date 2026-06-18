"""Pydantic models for match results."""

from pydantic import BaseModel, Field


class MatchResultResponse(BaseModel):
    """API response for a scored job/profile match."""

    id: str
    user_id: str
    candidate_profile_id: str
    job_posting_id: str
    score: int
    decision: str
    hard_filter_results: dict = Field(default_factory=dict)
    score_breakdown: dict = Field(default_factory=dict)
    matching_reasons: list[str] = Field(default_factory=list)
    missing_requirements: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    summary: str | None = None
    cover_letter: str | None = None
    trace: dict = Field(default_factory=dict)
    created_at: str | None = None
    job_title: str | None = None
    company_name: str | None = None
    job_url: str | None = None
    posted_at: str | None = None
    provider_updated_at: str | None = None
    first_seen_at: str | None = None

