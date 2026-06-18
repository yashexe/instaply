"""Tests for the discovery prober: hits, misses, budget, circuit breaker."""

import httpx
import pytest
import respx

import src.ingestion.http as ingestion_http
from src.discovery.prober import CIRCUIT_BREAKER_THRESHOLD, Prober

GH_URL = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
LEVER_URL = "https://api.lever.co/v0/postings/{slug}?mode=json"
ASHBY_ENDPOINT = "https://jobs.ashbyhq.com/api/non-user-graphql"


@pytest.fixture(autouse=True)
def no_backoff(monkeypatch):
    monkeypatch.setattr(ingestion_http, "BACKOFF_BASE_SECONDS", 0)


def prober() -> Prober:
    return Prober(max_probes=60, delay_seconds=0)


class TestProbeBoard:
    @respx.mock
    async def test_greenhouse_hit(self):
        respx.get(GH_URL.format(slug="acme")).mock(
            return_value=httpx.Response(
                200, json={"jobs": [{"id": 1, "title": "Software Engineer"}]}
            )
        )
        result = await prober().probe_board("greenhouse", "acme")
        assert result.found
        assert result.provider == "greenhouse"
        assert result.slug == "acme"
        assert result.job_count == 1
        assert result.titles == ["Software Engineer"]

    @respx.mock
    async def test_404_is_definitive_not_found(self):
        respx.get(GH_URL.format(slug="ghost")).mock(
            return_value=httpx.Response(404)
        )
        result = await prober().probe_board("greenhouse", "ghost")
        assert result is not None
        assert not result.found

    @respx.mock
    async def test_lever_hit(self):
        respx.get(LEVER_URL.format(slug="acme")).mock(
            return_value=httpx.Response(
                200, json=[{"id": "a", "text": "Backend Engineer"}]
            )
        )
        result = await prober().probe_board("lever", "acme")
        assert result.found
        assert result.titles == ["Backend Engineer"]

    @respx.mock
    async def test_ashby_null_board_is_not_found(self):
        respx.post(ASHBY_ENDPOINT).mock(
            return_value=httpx.Response(200, json={"data": {"jobBoard": None}})
        )
        result = await prober().probe_board("ashby", "ghost")
        assert result is not None
        assert not result.found

    @respx.mock
    async def test_ashby_hit(self):
        respx.post(ASHBY_ENDPOINT).mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": {
                        "jobBoard": {
                            "jobPostings": [{"id": "x", "title": "Data Engineer"}]
                        }
                    }
                },
            )
        )
        result = await prober().probe_board("ashby", "acme")
        assert result.found
        assert result.titles == ["Data Engineer"]

    @respx.mock
    async def test_server_error_is_inconclusive(self):
        respx.get(GH_URL.format(slug="acme")).mock(
            return_value=httpx.Response(500)
        )
        result = await prober().probe_board("greenhouse", "acme")
        assert result is None


class TestProbeCompany:
    @respx.mock
    async def test_stops_at_first_hit(self):
        gh = respx.get(GH_URL.format(slug="acme")).mock(
            return_value=httpx.Response(
                200, json={"jobs": [{"id": 1, "title": "Engineer"}]}
            )
        )
        lever = respx.get(LEVER_URL.format(slug="acme")).mock(
            return_value=httpx.Response(200, json=[])
        )
        result = await prober().probe_company(["acme"])
        assert result.found and result.provider == "greenhouse"
        assert gh.called
        assert not lever.called

    @respx.mock
    async def test_all_definitive_misses_is_not_found(self):
        for slug in ["acme", "acmehq"]:
            respx.get(GH_URL.format(slug=slug)).mock(
                return_value=httpx.Response(404)
            )
            respx.get(LEVER_URL.format(slug=slug)).mock(
                return_value=httpx.Response(404)
            )
        respx.post(ASHBY_ENDPOINT).mock(
            return_value=httpx.Response(200, json={"data": {"jobBoard": None}})
        )
        result = await prober().probe_company(["acme", "acmehq"])
        assert result is not None
        assert not result.found

    @respx.mock
    async def test_budget_exhaustion_returns_none(self):
        respx.get(GH_URL.format(slug="acme")).mock(
            return_value=httpx.Response(404)
        )
        p = Prober(max_probes=1, delay_seconds=0)
        result = await p.probe_company(["acme"])
        assert result is None
        assert p.exhausted

    @respx.mock
    async def test_transient_error_makes_result_inconclusive(self):
        respx.get(GH_URL.format(slug="acme")).mock(
            return_value=httpx.Response(500)
        )
        respx.get(LEVER_URL.format(slug="acme")).mock(
            return_value=httpx.Response(404)
        )
        respx.post(ASHBY_ENDPOINT).mock(
            return_value=httpx.Response(200, json={"data": {"jobBoard": None}})
        )
        result = await prober().probe_company(["acme"])
        assert result is None  # greenhouse outcome unknown -> inconclusive

    @respx.mock
    async def test_circuit_breaker_skips_failing_provider(self):
        gh = respx.get(url__regex=r"https://boards-api\.greenhouse\.io/.*").mock(
            return_value=httpx.Response(500)
        )
        respx.get(LEVER_URL.format(slug="acme")).mock(
            return_value=httpx.Response(404)
        )
        respx.post(ASHBY_ENDPOINT).mock(
            return_value=httpx.Response(200, json={"data": {"jobBoard": None}})
        )
        p = prober()
        # Trip the breaker with repeated greenhouse failures.
        for i in range(CIRCUIT_BREAKER_THRESHOLD):
            assert await p.probe_board("greenhouse", f"slug{i}") is None
        gh_calls_before = gh.call_count
        result = await p.probe_company(["acme"])
        # Greenhouse must not be probed again; outcome is inconclusive.
        assert gh.call_count == gh_calls_before
        assert result is None
