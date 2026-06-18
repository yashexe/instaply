"""
Pydantic models for the Discovery module.
"""

from pydantic import BaseModel


class Candidate(BaseModel):
    """A company name proposed by a candidate provider, before probing."""

    company_name: str
    origin: str  # "seed_list" | "llm"
    reason: str | None = None
    # Known board coordinates, when the provider already knows them
    # (skips slug guessing).
    known_provider: str | None = None
    known_slug: str | None = None


class ProbeResult(BaseModel):
    """Outcome of probing one ATS board for a slug."""

    found: bool
    provider: str | None = None
    slug: str | None = None
    job_count: int = 0
    titles: list[str] = []


class SuggestionResponse(BaseModel):
    """A discovered company as surfaced to the API/UI."""

    id: str
    company_name: str
    provider: str | None = None
    slug: str | None = None
    board_url: str | None = None
    status: str
    origin: str
    reason: str | None = None
    job_count: int = 0
    matching_titles: list[str] = []
    source_id: str | None = None
    discovered_at: str | None = None
    decided_at: str | None = None


class DiscoveryRunStats(BaseModel):
    """Summary of one discovery run."""

    candidates: int = 0
    skipped_known: int = 0
    probed: int = 0
    boards_found: int = 0
    suggested: int = 0
    not_found: int = 0
    irrelevant: int = 0
    llm_used: bool = False
