"""
Pydantic models for the Sources module.
"""

from pydantic import BaseModel


class SourceInput(BaseModel):
    """Input model for creating a new source."""

    url: str
    company_name: str | None = None
    priority: str = "normal"


class SourceUpdate(BaseModel):
    """Input model for updating an existing source."""

    status: str | None = None
    priority: str | None = None
    company_name: str | None = None


class SourceResponse(BaseModel):
    """Response model for a source record."""

    id: str
    user_id: str
    company_name: str
    provider: str
    source_url: str
    normalized_url: str | None = None
    priority: str
    status: str
    fetch_interval_seconds: int | None = None
    last_success_at: str | None = None
    last_error_at: str | None = None
    last_error_message: str | None = None
    consecutive_error_count: int = 0
    created_at: str | None = None
    updated_at: str | None = None


class SourceTestResult(BaseModel):
    """Result of testing a source feed."""

    success: bool
    provider: str | None = None
    job_count: int = 0
    message: str
