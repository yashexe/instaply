"""Pydantic models for alert history."""

from pydantic import BaseModel, Field


class AlertResponse(BaseModel):
    """API response for a notification alert."""

    id: str
    user_id: str
    match_result_id: str
    channel: str
    status: str
    idempotency_key: str
    sent_at: str | None = None
    failure_message: str | None = None
    created_at: str | None = None
    match_summary: str | None = None
    score: int | None = None
    job_title: str | None = None
    company_name: str | None = None
    job_url: str | None = None
    matching_reasons: list[str] = Field(default_factory=list)
    missing_requirements: list[str] = Field(default_factory=list)

