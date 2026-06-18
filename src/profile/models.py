"""
Pydantic models for the profile module.

Covers structured profile data (skills, roles, education),
resume input, and API responses.
"""

from pydantic import BaseModel, Field


class Skill(BaseModel):
    """A single skill extracted from a resume."""

    name: str
    category: str | None = None
    confidence: float = Field(default=0.9, ge=0.0, le=1.0)


class RoleEntry(BaseModel):
    """A work experience entry."""

    title: str
    company: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    summary: str | None = None


class Education(BaseModel):
    """An education entry."""

    institution: str
    degree: str | None = None
    field: str | None = None
    graduation_year: int | None = None


class StructuredProfile(BaseModel):
    """Structured data extracted from a resume by the LLM."""

    skills: list[Skill] = Field(default_factory=list)
    roles: list[RoleEntry] = Field(default_factory=list)
    education: list[Education] = Field(default_factory=list)
    domains: list[str] = Field(default_factory=list)
    years_of_experience: float | None = None
    seniority_level: str | None = None
    summary: str | None = None


class ResumeInput(BaseModel):
    """Request body for resume upload."""

    resume_text: str


class ProfileResponse(BaseModel):
    """API response for a candidate profile."""

    id: str
    user_id: str
    version: int
    structured_profile: StructuredProfile | None = None
    is_active: bool
    created_at: str
