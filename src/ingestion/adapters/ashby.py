"""
Ashby ATS adapter.

Fetches jobs from Ashby's public REST posting API and normalizes them into
RawJob instances.

We use the documented posting API
(https://api.ashbyhq.com/posting-api/job-board/{slug}) rather than the
internal `non-user-graphql` endpoint the job board UI uses: the GraphQL
schema is unversioned and changes without notice (a field rename there
silently broke every Ashby source), whereas the posting API is the stable,
supported contract.
"""

from urllib.parse import parse_qsl, urlencode, urlparse, urlsplit, urlunsplit

import structlog
from bs4 import BeautifulSoup

from src.ingestion.adapter import SourceAdapter
from src.ingestion.http import AdapterFetchError, fetch_json
from src.ingestion.models import RawJob

logger = structlog.get_logger()

_POSTING_API = "https://api.ashbyhq.com/posting-api/job-board"
_GRAPHQL_ENDPOINT = "https://jobs.ashbyhq.com/api/non-user-graphql"

_ORG_QUERY = (
    "query ApiOrganizationFromHostedJobsPageName("
    "$organizationHostedJobsPageName: String!) { "
    "organization: organizationFromHostedJobsPageName("
    "organizationHostedJobsPageName: $organizationHostedJobsPageName"
    ") { customJobsPageUrl } }"
)


def _strip_html(html: str | None) -> str | None:
    """Convert HTML to plain text using BeautifulSoup."""
    if not html:
        return None
    soup = BeautifulSoup(html, "html.parser")
    return soup.get_text(separator="\n", strip=True)


def _extract_slug(source: dict) -> str:
    """Extract the company slug from the source URL.

    Ashby hosted-page names are case-sensitive and lowercase by convention
    (e.g. jobs.ashbyhq.com/openai), so a URL captured as '/OpenAI' would
    otherwise 404. Lowercase to match.
    """
    url = source.get("normalized_url") or source.get("source_url", "")
    parsed = urlparse(url)
    parts = [p for p in parsed.path.strip("/").split("/") if p]
    return parts[0].lower() if parts else ""


async def _fetch_custom_jobs_page_url(slug: str) -> str | None:
    """Return the org's external careers-page URL, or None.

    Some orgs embed Ashby on their own site (e.g. Cursor → cursor.com/careers)
    and disable the jobs.ashbyhq.com/{slug}/{id} hosted page. For those, the
    posting API's jobUrl still points at the disabled hosted page and 404s, so
    we must deep-link into the embed instead (see _embed_deeplink).

    This is the one place the adapter touches Ashby's internal GraphQL, which is
    unversioned and has broken before — so it is strictly best-effort: any
    failure returns None and the caller falls back to the hosted jobUrl.
    """
    try:
        data = await fetch_json(
            "POST",
            _GRAPHQL_ENDPOINT,
            json_body={
                "operationName": "ApiOrganizationFromHostedJobsPageName",
                "variables": {"organizationHostedJobsPageName": slug},
                "query": _ORG_QUERY,
            },
            provider="ashby",
            quiet_4xx=True,
        )
    except AdapterFetchError as exc:
        logger.info("ashby.org_lookup_failed", slug=slug, error=str(exc))
        return None

    org = (data or {}).get("data", {}).get("organization") or {}
    url = org.get("customJobsPageUrl")
    return url.strip() if isinstance(url, str) and url.strip() else None


def _embed_deeplink(page_url: str, job_id: str) -> str:
    """Build an Ashby embed deep link: <careers page>?ashby_jid=<job id>.

    The Ashby embed reads ashby_jid from the hosting page's query string to
    open a specific posting, so this is the canonical shareable URL for orgs
    that run the board on their own site.
    """
    parts = urlsplit(page_url)
    query = dict(parse_qsl(parts.query))
    query["ashby_jid"] = job_id
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment)
    )


def _map_remote_policy(posting: dict) -> str:
    """Map Ashby workplaceType (preferred) or isRemote to our vocabulary."""
    workplace = (posting.get("workplaceType") or "").strip().lower()
    if workplace in ("remote", "hybrid", "onsite"):
        return workplace
    if workplace in ("on-site", "on site", "in office", "in-office"):
        return "onsite"
    return "remote" if posting.get("isRemote") else "unknown"


def _map_employment_type(raw: str | None) -> str:
    """Map Ashby employmentType (e.g. 'FullTime') to our vocabulary."""
    if not raw:
        return "unknown"
    value = raw.lower().replace("-", "").replace("_", "").replace(" ", "")
    if "full" in value:
        return "full_time"
    if "contract" in value or "freelance" in value:
        return "contract"
    if "intern" in value:
        return "internship"
    if "part" in value:
        return "part_time"
    return "unknown"


def _collect_locations(posting: dict) -> list[str]:
    """Build a flat location list from the primary and secondary locations."""
    locations: list[str] = []
    primary = posting.get("location")
    if primary:
        locations.append(str(primary))
    for secondary in posting.get("secondaryLocations") or []:
        if isinstance(secondary, dict):
            name = secondary.get("location") or secondary.get("locationName")
            if name:
                locations.append(str(name))
        elif secondary:
            locations.append(str(secondary))
    return locations


class AshbyAdapter(SourceAdapter):
    """Adapter for the Ashby public posting API."""

    provider = "ashby"

    async def fetch_jobs(self, source: dict) -> list[RawJob]:
        """Fetch all jobs from an Ashby job board.

        API: GET https://api.ashbyhq.com/posting-api/job-board/{slug}
        A non-existent board returns HTTP 404, surfaced as AdapterFetchError.
        """
        slug = _extract_slug(source)
        company_name = source.get("company_name", slug or "Unknown")

        if not slug:
            raise AdapterFetchError("Could not extract Ashby company slug from source URL")

        data = await fetch_json(
            "GET",
            f"{_POSTING_API}/{slug}",
            provider=self.provider,
        )

        if not isinstance(data, dict) or not isinstance(data.get("jobs"), list):
            raise AdapterFetchError(
                f"Unexpected Ashby posting-API response for slug '{slug}'"
            )

        postings = data["jobs"]
        if not postings:
            logger.info("ashby.no_jobs", slug=slug)
            return []

        # Orgs with a custom careers page have dead hosted job URLs; deep-link
        # into their embed instead. Best-effort: None means use the hosted URL.
        custom_page_url = await _fetch_custom_jobs_page_url(slug)

        raw_jobs: list[RawJob] = []

        for posting in postings:
            # The posting API only lists public jobs, but honour the flag.
            if posting.get("isListed") is False:
                continue
            try:
                job_id = posting.get("id", "")
                description_html = posting.get("descriptionHtml", "")
                description_text = (
                    posting.get("descriptionPlain")
                    or _strip_html(description_html)
                )
                if custom_page_url and job_id:
                    canonical_url = _embed_deeplink(custom_page_url, job_id)
                else:
                    canonical_url = (
                        posting.get("jobUrl")
                        or posting.get("applyUrl")
                        or f"https://jobs.ashbyhq.com/{slug}/{job_id}"
                    )

                raw_jobs.append(
                    RawJob(
                        provider_job_id=job_id,
                        title=posting.get("title", ""),
                        company_name=company_name,
                        url=canonical_url,
                        locations=_collect_locations(posting),
                        remote_policy=_map_remote_policy(posting),
                        employment_type=_map_employment_type(
                            posting.get("employmentType")
                        ),
                        department=posting.get("department") or posting.get("team"),
                        description_html=description_html,
                        description_text=description_text,
                        posted_at=posting.get("publishedAt"),
                        raw_data=posting,
                    )
                )
            except Exception as exc:
                logger.warning(
                    "ashby.parse_error",
                    posting_id=posting.get("id"),
                    error=str(exc),
                )
                continue

        logger.info("ashby.fetched", company=company_name, job_count=len(raw_jobs))
        return raw_jobs
