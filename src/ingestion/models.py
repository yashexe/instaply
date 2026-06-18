"""
Pydantic models for the Ingestion module.
"""

from pydantic import BaseModel


class RawJob(BaseModel):
    """Normalized job data produced by an ATS adapter."""

    provider_job_id: str | None = None
    title: str
    company_name: str
    url: str | None = None
    locations: list[str] = []
    remote_policy: str = "unknown"
    employment_type: str = "unknown"
    department: str | None = None
    description_text: str | None = None
    description_html: str | None = None
    salary_min: int | None = None
    salary_max: int | None = None
    salary_currency: str | None = None
    visa_sponsorship: str = "unknown"
    posted_at: str | None = None
    provider_updated_at: str | None = None
    raw_data: dict | None = None
