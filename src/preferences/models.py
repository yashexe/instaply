"""Pydantic models for job preferences."""

from pydantic import BaseModel, Field


class JobPreferencesInput(BaseModel):
    """Request body for creating or updating job preferences."""

    target_roles: list[str] = Field(default_factory=list)
    seniority_levels: list[str] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=list)
    remote_policy: str = "any"
    min_salary: int | None = None
    salary_currency: str | None = None
    needs_visa_sponsorship: bool = False
    must_have_skills: list[str] = Field(default_factory=list)
    nice_to_have_skills: list[str] = Field(default_factory=list)
    excluded_keywords: list[str] = Field(default_factory=list)
    alert_threshold: int | None = Field(default=None, ge=0, le=100)


class JobPreferencesResponse(JobPreferencesInput):
    """API response for persisted job preferences."""

    id: str
    user_id: str
    created_at: str | None = None
    updated_at: str | None = None

