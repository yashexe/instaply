"""
Greenhouse ATS adapter.

Fetches jobs from the Greenhouse public job board API and normalizes
them into RawJob instances.
"""

import structlog
from bs4 import BeautifulSoup

from src.ingestion.adapter import SourceAdapter
from src.ingestion.http import AdapterFetchError, fetch_json
from src.ingestion.models import RawJob

logger = structlog.get_logger()


def _strip_html(html: str | None) -> str | None:
    """Convert HTML to plain text using BeautifulSoup."""
    if not html:
        return None
    soup = BeautifulSoup(html, "html.parser")
    return soup.get_text(separator="\n", strip=True)


def _extract_remote_policy(location_name: str, content: str | None) -> str:
    """Infer remote policy from location name or job content."""
    text = (location_name + " " + (content or "")).lower()
    if "remote" in text and "hybrid" in text:
        return "hybrid"
    if "remote" in text:
        return "remote"
    if "on-site" in text or "onsite" in text or "in-office" in text:
        return "onsite"
    return "unknown"


class GreenhouseAdapter(SourceAdapter):
    """Adapter for Greenhouse job board API."""

    provider = "greenhouse"

    async def fetch_jobs(self, source: dict) -> list[RawJob]:
        """Fetch all jobs from a Greenhouse board.

        API: GET https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true
        """
        url = source.get("normalized_url") or source.get("source_url", "")
        company_name = source.get("company_name", "Unknown")

        data = await fetch_json("GET", url, provider=self.provider)

        if not isinstance(data, dict):
            raise AdapterFetchError(
                f"Unexpected Greenhouse response type: {type(data).__name__}"
            )

        jobs_data = data.get("jobs", [])
        if not jobs_data:
            logger.info("greenhouse.no_jobs", url=url)
            return []

        raw_jobs: list[RawJob] = []

        for job in jobs_data:
            try:
                job_id = str(job.get("id", ""))
                title = job.get("title", "")
                location = job.get("location", {})
                location_name = location.get("name", "") if isinstance(location, dict) else ""
                locations = [location_name] if location_name else []

                departments = job.get("departments", [])
                department = departments[0].get("name", "") if departments else None

                content_html = job.get("content", "")
                content_text = _strip_html(content_html)
                absolute_url = job.get("absolute_url")
                updated_at = job.get("updated_at")
                # first_published is the original publish date; updated_at
                # bumps on any edit and would make old postings look new.
                first_published = job.get("first_published")

                remote_policy = _extract_remote_policy(location_name, content_html)

                raw_jobs.append(
                    RawJob(
                        provider_job_id=job_id,
                        title=title,
                        company_name=company_name,
                        url=absolute_url,
                        locations=locations,
                        remote_policy=remote_policy,
                        department=department,
                        description_html=content_html,
                        description_text=content_text,
                        posted_at=first_published or updated_at,
                        provider_updated_at=updated_at,
                        raw_data=job,
                    )
                )
            except Exception as exc:
                logger.warning(
                    "greenhouse.parse_error",
                    job_id=job.get("id"),
                    error=str(exc),
                )
                continue

        logger.info(
            "greenhouse.fetched",
            company=company_name,
            job_count=len(raw_jobs),
        )
        return raw_jobs
