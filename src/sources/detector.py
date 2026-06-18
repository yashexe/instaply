"""
ATS provider detection from job board URLs.

Identifies Greenhouse, Lever, and Ashby URLs and normalises them
to their canonical API endpoints.
"""

import re
from urllib.parse import urlparse

import httpx
import structlog

from src.sources.models import SourceTestResult

logger = structlog.get_logger()

# Pre-compiled patterns for provider detection
_GREENHOUSE_BOARDS = re.compile(
    r"^boards(?:-api)?\.greenhouse\.io$", re.IGNORECASE
)
_LEVER_BOARDS = re.compile(r"^(?:jobs|api)\.lever\.co$", re.IGNORECASE)
_ASHBY_BOARDS = re.compile(r"^jobs\.ashby(?:hq)?\.(?:com|io)$", re.IGNORECASE)


def detect_provider(url: str) -> tuple[str, str, str | None]:
    """Detect the ATS provider from a job board URL.

    Returns:
        (provider, normalized_url, company_name)
    """
    parsed = urlparse(url if "://" in url else f"https://{url}")
    host = parsed.hostname or ""
    path_parts = [p for p in parsed.path.strip("/").split("/") if p]

    # --- Greenhouse ---
    if _GREENHOUSE_BOARDS.match(host):
        # boards.greenhouse.io/{slug} or boards-api.greenhouse.io/v1/boards/{slug}
        slug: str | None = None
        if host.startswith("boards-api"):
            # boards-api.greenhouse.io/v1/boards/{slug}/...
            if len(path_parts) >= 3 and path_parts[0] == "v1" and path_parts[1] == "boards":
                slug = path_parts[2]
        else:
            # boards.greenhouse.io/{slug}
            if path_parts:
                slug = path_parts[0]

        if slug:
            normalized = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
            return "greenhouse", normalized, slug

    # --- Lever ---
    if _LEVER_BOARDS.match(host):
        company: str | None = None
        if host.lower().startswith("api."):
            # api.lever.co/v0/postings/{company} (normalized API URL)
            if len(path_parts) >= 3 and path_parts[0] == "v0" and path_parts[1] == "postings":
                company = path_parts[2]
        elif path_parts:
            # jobs.lever.co/{company}
            company = path_parts[0]
        if company:
            normalized = f"https://api.lever.co/v0/postings/{company}?mode=json"
            return "lever", normalized, company

    # --- Ashby ---
    if _ASHBY_BOARDS.match(host):
        if path_parts:
            company = path_parts[0]
            normalized = f"https://jobs.ashbyhq.com/{company}"
            return "ashby", normalized, company

    # --- Unknown / custom ---
    return "custom", url, None


async def test_source(url: str, provider: str) -> SourceTestResult:
    """Make a test HTTP request to validate the source returns data.

    Returns a SourceTestResult with success status, job count, and message.
    """
    try:
        async with httpx.AsyncClient(
            timeout=30.0,
            headers={"User-Agent": "Instaply/0.1"},
            follow_redirects=True,
        ) as client:
            if provider == "greenhouse":
                resp = await client.get(url)
                resp.raise_for_status()
                data = resp.json()
                jobs = data.get("jobs", [])
                return SourceTestResult(
                    success=True,
                    provider=provider,
                    job_count=len(jobs),
                    message=f"Found {len(jobs)} jobs from Greenhouse.",
                )

            elif provider == "lever":
                resp = await client.get(url)
                resp.raise_for_status()
                data = resp.json()
                if not isinstance(data, list):
                    data = []
                return SourceTestResult(
                    success=True,
                    provider=provider,
                    job_count=len(data),
                    message=f"Found {len(data)} jobs from Lever.",
                )

            elif provider == "ashby":
                # Ashby uses a GraphQL API
                # Extract slug from the normalized URL
                parsed = urlparse(url)
                path_parts = [p for p in parsed.path.strip("/").split("/") if p]
                slug = path_parts[0] if path_parts else ""
                payload = {
                    "operationName": "ApiJobBoardWithTeams",
                    "variables": {"organizationHostedJobsPageName": slug},
                    "query": (
                        "query ApiJobBoardWithTeams("
                        "$organizationHostedJobsPageName: String!) { "
                        "jobBoard: jobBoardWithTeams("
                        "organizationHostedJobsPageName: $organizationHostedJobsPageName"
                        ") { teams { id name parentTeamId } "
                        "jobPostings { id title } } }"
                    ),
                }
                resp = await client.post(
                    "https://jobs.ashbyhq.com/api/non-user-graphql",
                    json=payload,
                )
                resp.raise_for_status()
                data = resp.json()
                job_board = data.get("data", {}).get("jobBoard")
                if not job_board:
                    return SourceTestResult(
                        success=False,
                        provider=provider,
                        job_count=0,
                        message="Ashby job board was not found for this slug.",
                    )
                postings = job_board.get("jobPostings", [])
                return SourceTestResult(
                    success=True,
                    provider=provider,
                    job_count=len(postings),
                    message=f"Found {len(postings)} jobs from Ashby.",
                )

            else:
                # Custom provider — just test HTTP reachability
                resp = await client.get(url)
                resp.raise_for_status()
                return SourceTestResult(
                    success=True,
                    provider=provider,
                    job_count=0,
                    message="URL is reachable but job count unknown for custom provider.",
                )

    except httpx.HTTPStatusError as exc:
        logger.warning(
            "source.test_http_error",
            url=url,
            provider=provider,
            status=exc.response.status_code,
        )
        return SourceTestResult(
            success=False,
            provider=provider,
            job_count=0,
            message=f"HTTP {exc.response.status_code}: {exc.response.reason_phrase}",
        )
    except httpx.RequestError as exc:
        logger.warning("source.test_request_error", url=url, error=str(exc))
        return SourceTestResult(
            success=False,
            provider=provider,
            job_count=0,
            message=f"Request error: {exc}",
        )
    except Exception as exc:
        logger.error("source.test_unexpected_error", url=url, error=str(exc))
        return SourceTestResult(
            success=False,
            provider=provider,
            job_count=0,
            message=f"Unexpected error: {exc}",
        )
