"""ATS adapter tests — normalization, retries, and failure surfacing."""

import httpx
import pytest
import respx

import src.ingestion.http as ingestion_http
from src.ingestion.adapters.ashby import AshbyAdapter
from src.ingestion.adapters.greenhouse import GreenhouseAdapter
from src.ingestion.adapters.lever import LeverAdapter
from src.ingestion.http import AdapterFetchError

GREENHOUSE_URL = "https://boards-api.greenhouse.io/v1/boards/acme/jobs?content=true"
LEVER_URL = "https://api.lever.co/v0/postings/acme?mode=json"


@pytest.fixture(autouse=True)
def no_backoff(monkeypatch):
    """Make retries instant so failure tests stay fast."""
    monkeypatch.setattr(ingestion_http, "BACKOFF_BASE_SECONDS", 0)


def greenhouse_source() -> dict:
    return {
        "id": "src1",
        "provider": "greenhouse",
        "company_name": "Acme",
        "normalized_url": GREENHOUSE_URL,
        "source_url": GREENHOUSE_URL,
    }


GREENHOUSE_PAYLOAD = {
    "jobs": [
        {
            "id": 12345,
            "title": "Senior Backend Engineer",
            "location": {"name": "Remote - Canada"},
            "departments": [{"name": "Engineering"}],
            "content": "<p>Build <b>APIs</b> in Python.</p>",
            "absolute_url": "https://boards.greenhouse.io/acme/jobs/12345",
            "updated_at": "2026-06-01T12:00:00Z",
            "first_published": "2025-11-15T09:00:00Z",
        },
        {
            "id": 12346,
            "title": "Office Manager",
            "location": {"name": "Toronto (on-site)"},
            "departments": [],
            "content": "<p>Keep the office running.</p>",
            "absolute_url": "https://boards.greenhouse.io/acme/jobs/12346",
            "updated_at": "2026-06-02T12:00:00Z",
        },
    ]
}


class TestGreenhouseAdapter:
    @respx.mock
    async def test_normalizes_jobs(self):
        respx.get(GREENHOUSE_URL).mock(
            return_value=httpx.Response(200, json=GREENHOUSE_PAYLOAD)
        )
        jobs = await GreenhouseAdapter().fetch_jobs(greenhouse_source())

        assert len(jobs) == 2
        first = jobs[0]
        assert first.provider_job_id == "12345"
        assert first.title == "Senior Backend Engineer"
        assert first.company_name == "Acme"
        assert first.locations == ["Remote - Canada"]
        assert first.remote_policy == "remote"
        assert first.department == "Engineering"
        assert "APIs" in first.description_text
        assert "<b>" not in first.description_text
        assert first.posted_at == "2025-11-15T09:00:00Z"
        assert first.provider_updated_at == "2026-06-01T12:00:00Z"
        # No first_published: fall back to updated_at rather than no date.
        assert jobs[1].posted_at == "2026-06-02T12:00:00Z"
        assert jobs[1].remote_policy == "onsite"

    @respx.mock
    async def test_retries_transient_errors_then_succeeds(self):
        route = respx.get(GREENHOUSE_URL).mock(
            side_effect=[
                httpx.Response(500),
                httpx.Response(503),
                httpx.Response(200, json=GREENHOUSE_PAYLOAD),
            ]
        )
        jobs = await GreenhouseAdapter().fetch_jobs(greenhouse_source())
        assert len(jobs) == 2
        assert route.call_count == 3

    @respx.mock
    async def test_persistent_server_error_raises(self):
        route = respx.get(GREENHOUSE_URL).mock(return_value=httpx.Response(500))
        with pytest.raises(AdapterFetchError):
            await GreenhouseAdapter().fetch_jobs(greenhouse_source())
        assert route.call_count == ingestion_http.MAX_ATTEMPTS

    @respx.mock
    async def test_client_error_fails_without_retry(self):
        route = respx.get(GREENHOUSE_URL).mock(return_value=httpx.Response(404))
        with pytest.raises(AdapterFetchError):
            await GreenhouseAdapter().fetch_jobs(greenhouse_source())
        assert route.call_count == 1

    @respx.mock
    async def test_network_error_retries_then_raises(self):
        route = respx.get(GREENHOUSE_URL).mock(
            side_effect=httpx.ConnectError("connection refused")
        )
        with pytest.raises(AdapterFetchError):
            await GreenhouseAdapter().fetch_jobs(greenhouse_source())
        assert route.call_count == ingestion_http.MAX_ATTEMPTS


LEVER_PAYLOAD = [
    {
        "id": "abc-123",
        "text": "Data Engineer",
        "categories": {
            "location": "Toronto, Ontario",
            "team": "Data",
            "commitment": "Full-time",
        },
        "descriptionPlain": "Build pipelines.",
        "hostedUrl": "https://jobs.lever.co/acme/abc-123",
        "createdAt": 1717200000000,
        "updatedAt": 1718000000000,
        "workplaceType": "hybrid",
    }
]


class TestLeverAdapter:
    @respx.mock
    async def test_normalizes_postings(self):
        respx.get(LEVER_URL).mock(return_value=httpx.Response(200, json=LEVER_PAYLOAD))
        source = {
            "id": "src2",
            "provider": "lever",
            "company_name": "Acme",
            "normalized_url": LEVER_URL,
            "source_url": LEVER_URL,
        }
        jobs = await LeverAdapter().fetch_jobs(source)

        assert len(jobs) == 1
        posting = jobs[0]
        assert posting.provider_job_id == "abc-123"
        assert posting.title == "Data Engineer"
        assert posting.locations == ["Toronto, Ontario"]
        assert posting.department == "Data"
        assert posting.employment_type == "full_time"
        assert posting.remote_policy == "hybrid"
        assert posting.posted_at.startswith("2024-")
        assert posting.provider_updated_at.startswith("2024-")

    @respx.mock
    async def test_non_list_response_raises(self):
        respx.get(LEVER_URL).mock(
            return_value=httpx.Response(200, json={"error": "unexpected"})
        )
        source = {
            "id": "src2",
            "provider": "lever",
            "company_name": "Acme",
            "normalized_url": LEVER_URL,
            "source_url": LEVER_URL,
        }
        with pytest.raises(AdapterFetchError):
            await LeverAdapter().fetch_jobs(source)


ASHBY_POSTING_URL = "https://api.ashbyhq.com/posting-api/job-board/acme"
ASHBY_GRAPHQL_URL = "https://jobs.ashbyhq.com/api/non-user-graphql"


def mock_ashby_org(custom_jobs_page_url=None, status=200):
    """Mock the org-lookup GraphQL call the adapter makes for canonical URLs."""
    if status != 200:
        return respx.post(ASHBY_GRAPHQL_URL).mock(return_value=httpx.Response(status))
    return respx.post(ASHBY_GRAPHQL_URL).mock(
        return_value=httpx.Response(
            200,
            json={"data": {"organization": {"customJobsPageUrl": custom_jobs_page_url}}},
        )
    )

ASHBY_PAYLOAD = {
    "jobs": [
        {
            "id": "xyz-789",
            "title": "ML Engineer",
            "location": "San Francisco",
            "secondaryLocations": [{"location": "Remote - US"}],
            "department": "AI",
            "team": "Research",
            "descriptionHtml": "<p>Train models.</p>",
            "descriptionPlain": "Train models.",
            "publishedAt": "2026-06-01T00:00:00.000+00:00",
            "employmentType": "FullTime",
            "isRemote": True,
            "workplaceType": "Remote",
            "isListed": True,
            "jobUrl": "https://jobs.ashbyhq.com/acme/xyz-789",
            "applyUrl": "https://jobs.ashbyhq.com/acme/xyz-789/application",
        }
    ]
}


def ashby_source() -> dict:
    return {
        "id": "src3",
        "provider": "ashby",
        "company_name": "Acme",
        "normalized_url": "https://jobs.ashbyhq.com/acme",
        "source_url": "https://jobs.ashbyhq.com/acme",
    }


class TestAshbyAdapter:
    @respx.mock
    async def test_normalizes_postings(self):
        respx.get(ASHBY_POSTING_URL).mock(
            return_value=httpx.Response(200, json=ASHBY_PAYLOAD)
        )
        mock_ashby_org(custom_jobs_page_url=None)
        jobs = await AshbyAdapter().fetch_jobs(ashby_source())

        assert len(jobs) == 1
        posting = jobs[0]
        assert posting.provider_job_id == "xyz-789"
        assert posting.remote_policy == "remote"
        assert posting.employment_type == "full_time"
        assert posting.url == "https://jobs.ashbyhq.com/acme/xyz-789"
        assert posting.description_text == "Train models."
        assert posting.locations == ["San Francisco", "Remote - US"]
        assert posting.department == "AI"

    @respx.mock
    async def test_custom_jobs_page_url_builds_embed_deeplink(self):
        # Orgs like Cursor disable the hosted page; the hosted jobUrl 404s, so
        # the canonical URL must deep-link into the org's own careers embed.
        respx.get(ASHBY_POSTING_URL).mock(
            return_value=httpx.Response(200, json=ASHBY_PAYLOAD)
        )
        mock_ashby_org(custom_jobs_page_url="https://acme.com/careers")
        jobs = await AshbyAdapter().fetch_jobs(ashby_source())

        assert jobs[0].url == "https://acme.com/careers?ashby_jid=xyz-789"

    @respx.mock
    async def test_graphql_failure_falls_back_to_hosted_url(self):
        # If the (brittle) org lookup fails, ingestion must still succeed using
        # the hosted jobUrl — never break polling over a URL nicety.
        respx.get(ASHBY_POSTING_URL).mock(
            return_value=httpx.Response(200, json=ASHBY_PAYLOAD)
        )
        mock_ashby_org(status=404)
        jobs = await AshbyAdapter().fetch_jobs(ashby_source())

        assert jobs[0].url == "https://jobs.ashbyhq.com/acme/xyz-789"

    @respx.mock
    async def test_unknown_board_404_raises(self):
        respx.get(ASHBY_POSTING_URL).mock(return_value=httpx.Response(404))
        with pytest.raises(AdapterFetchError):
            await AshbyAdapter().fetch_jobs(ashby_source())

    @respx.mock
    async def test_unexpected_response_raises(self):
        respx.get(ASHBY_POSTING_URL).mock(
            return_value=httpx.Response(200, json={"unexpected": "shape"})
        )
        with pytest.raises(AdapterFetchError):
            await AshbyAdapter().fetch_jobs(ashby_source())

    async def test_missing_slug_raises(self):
        source = ashby_source()
        source["normalized_url"] = "https://jobs.ashbyhq.com/"
        source["source_url"] = "https://jobs.ashbyhq.com/"
        with pytest.raises(AdapterFetchError):
            await AshbyAdapter().fetch_jobs(source)
