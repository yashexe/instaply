"""
Lever ATS adapter.

Fetches jobs from the Lever public postings API and normalizes
them into RawJob instances.
"""

from datetime import datetime, timezone

import structlog

from src.ingestion.adapter import SourceAdapter
from src.ingestion.http import AdapterFetchError, fetch_json
from src.ingestion.models import RawJob

logger = structlog.get_logger()

_WORKPLACE_MAP: dict[str, str] = {
    "onsite": "onsite",
    "remote": "remote",
    "hybrid": "hybrid",
    "unspecified": "unknown",
}


def _epoch_ms_to_iso(epoch_ms: int | None) -> str | None:
    """Convert a millisecond epoch timestamp to ISO 8601 string."""
    if epoch_ms is None:
        return None
    try:
        dt = datetime.fromtimestamp(epoch_ms / 1000, tz=timezone.utc)
        return dt.isoformat()
    except (OSError, ValueError):
        return None


class LeverAdapter(SourceAdapter):
    """Adapter for Lever job postings API."""

    provider = "lever"

    async def fetch_jobs(self, source: dict) -> list[RawJob]:
        """Fetch all jobs from a Lever company page.

        API: GET https://api.lever.co/v0/postings/{company}?mode=json
        """
        url = source.get("normalized_url") or source.get("source_url", "")
        company_name = source.get("company_name", "Unknown")

        data = await fetch_json("GET", url, provider=self.provider)

        if not isinstance(data, list):
            raise AdapterFetchError(
                f"Unexpected Lever response type: {type(data).__name__}"
            )

        if not data:
            logger.info("lever.no_jobs", url=url)
            return []

        raw_jobs: list[RawJob] = []

        for posting in data:
            try:
                posting_id = posting.get("id", "")
                title = posting.get("text", "")
                categories = posting.get("categories", {})
                if not isinstance(categories, dict):
                    categories = {}

                location_str = categories.get("location", "")
                locations = [location_str] if location_str else []

                team = categories.get("team", "")
                department = categories.get("department", "")
                dept_name = team or department or None

                commitment = categories.get("commitment", "")
                employment_type = "unknown"
                if commitment:
                    commitment_lower = commitment.lower()
                    if "full" in commitment_lower:
                        employment_type = "full_time"
                    elif "contract" in commitment_lower or "freelance" in commitment_lower:
                        employment_type = "contract"
                    elif "intern" in commitment_lower:
                        employment_type = "internship"
                    elif "part" in commitment_lower:
                        employment_type = "part_time"

                description_text = posting.get("descriptionPlain", "")
                hosted_url = posting.get("hostedUrl")
                created_at_ms = posting.get("createdAt")
                posted_at = _epoch_ms_to_iso(created_at_ms)
                provider_updated_at = _epoch_ms_to_iso(posting.get("updatedAt"))

                workplace_type = posting.get("workplaceType", "unspecified")
                remote_policy = _WORKPLACE_MAP.get(
                    workplace_type.lower() if workplace_type else "",
                    "unknown",
                )

                raw_jobs.append(
                    RawJob(
                        provider_job_id=posting_id,
                        title=title,
                        company_name=company_name,
                        url=hosted_url,
                        locations=locations,
                        remote_policy=remote_policy,
                        employment_type=employment_type,
                        department=dept_name,
                        description_text=description_text,
                        posted_at=posted_at,
                        provider_updated_at=provider_updated_at,
                        raw_data=posting,
                    )
                )
            except Exception as exc:
                logger.warning(
                    "lever.parse_error",
                    posting_id=posting.get("id"),
                    error=str(exc),
                )
                continue

        logger.info("lever.fetched", company=company_name, job_count=len(raw_jobs))
        return raw_jobs
