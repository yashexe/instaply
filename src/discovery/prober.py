"""Polite ATS board probing for guessed company slugs.

A Prober instance holds per-run state: a hard cap on total HTTP probes,
a fixed delay between requests, and a per-provider circuit breaker so a
provider that starts erroring is not hammered for the rest of the run.
"""

from __future__ import annotations

import asyncio

import httpx
import structlog

from src.config import settings
from src.discovery.models import ProbeResult
from src.ingestion.http import AdapterFetchError, fetch_json

logger = structlog.get_logger()

PROVIDER_ORDER = ("greenhouse", "lever", "ashby")
CIRCUIT_BREAKER_THRESHOLD = 5

_ASHBY_ENDPOINT = "https://jobs.ashbyhq.com/api/non-user-graphql"
_ASHBY_QUERY = (
    "query ApiJobBoardWithTeams("
    "$organizationHostedJobsPageName: String!) { "
    "jobBoard: jobBoardWithTeams("
    "organizationHostedJobsPageName: $organizationHostedJobsPageName"
    ") { jobPostings { id title } } }"
)


def board_url(provider: str, slug: str) -> str:
    """Human-viewable board page, linked from the suggestion UI."""
    return {
        "greenhouse": f"https://boards.greenhouse.io/{slug}",
        "lever": f"https://jobs.lever.co/{slug}",
        "ashby": f"https://jobs.ashbyhq.com/{slug}",
    }[provider]


def normalized_url(provider: str, slug: str) -> str:
    """Canonical API endpoint, matching detect_provider normalization."""
    return {
        "greenhouse": f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true",
        "lever": f"https://api.lever.co/v0/postings/{slug}?mode=json",
        "ashby": f"https://jobs.ashbyhq.com/{slug}",
    }[provider]


class Prober:
    """Stateful per-run prober. Not safe for concurrent use (by design:
    probes run serially for politeness)."""

    def __init__(
        self,
        *,
        max_probes: int | None = None,
        delay_seconds: float | None = None,
    ) -> None:
        self.max_probes = (
            max_probes
            if max_probes is not None
            else settings.discovery_max_probes_per_run
        )
        self.delay_seconds = (
            delay_seconds
            if delay_seconds is not None
            else settings.discovery_probe_delay_seconds
        )
        self.probes_used = 0
        self._provider_errors: dict[str, int] = {p: 0 for p in PROVIDER_ORDER}

    @property
    def exhausted(self) -> bool:
        return self.probes_used >= self.max_probes

    def _provider_open(self, provider: str) -> bool:
        return self._provider_errors[provider] < CIRCUIT_BREAKER_THRESHOLD

    async def probe_board(self, provider: str, slug: str) -> ProbeResult | None:
        """Probe one provider for one slug.

        Returns a ProbeResult (found or definitively absent), or None when
        the outcome is unknown (network/server error) — None must not be
        recorded as not_found.
        """
        self.probes_used += 1
        try:
            if provider == "greenhouse":
                data = await fetch_json(
                    "GET", normalized_url(provider, slug),
                    provider="discovery", max_attempts=1, quiet_4xx=True,
                )
                jobs = data.get("jobs", []) if isinstance(data, dict) else []
                titles = [j.get("title", "") for j in jobs]
            elif provider == "lever":
                data = await fetch_json(
                    "GET", normalized_url(provider, slug),
                    provider="discovery", max_attempts=1, quiet_4xx=True,
                )
                if not isinstance(data, list):
                    return ProbeResult(found=False)
                titles = [p.get("text", "") for p in data]
            elif provider == "ashby":
                payload = {
                    "operationName": "ApiJobBoardWithTeams",
                    "variables": {"organizationHostedJobsPageName": slug},
                    "query": _ASHBY_QUERY,
                }
                data = await fetch_json(
                    "POST", _ASHBY_ENDPOINT, json_body=payload,
                    provider="discovery", max_attempts=1, quiet_4xx=True,
                )
                job_board = (data or {}).get("data", {}).get("jobBoard")
                if not job_board:
                    return ProbeResult(found=False)
                titles = [p.get("title", "") for p in job_board.get("jobPostings", [])]
            else:
                return ProbeResult(found=False)
        except AdapterFetchError as exc:
            cause = exc.__cause__
            if (
                isinstance(cause, httpx.HTTPStatusError)
                and 400 <= cause.response.status_code < 500
            ):
                # Definitive: this slug has no board on this provider.
                self._provider_errors[provider] = 0
                return ProbeResult(found=False)
            self._provider_errors[provider] += 1
            if not self._provider_open(provider):
                logger.warning(
                    "discovery.provider_circuit_open", provider=provider
                )
            return None

        self._provider_errors[provider] = 0
        return ProbeResult(
            found=True,
            provider=provider,
            slug=slug,
            job_count=len(titles),
            titles=[t for t in titles if t],
        )

    async def probe_company(self, slugs: list[str]) -> ProbeResult | None:
        """Try each slug against each provider, stopping at the first hit.

        Returns the hit, ProbeResult(found=False) when every probe came
        back definitively absent, or None when the search was cut short
        (probe budget, circuit breakers, or transient errors) and the
        company should NOT be recorded as not_found.
        """
        inconclusive = False
        for slug in slugs:
            for provider in PROVIDER_ORDER:
                if self.exhausted:
                    return None
                if not self._provider_open(provider):
                    inconclusive = True
                    continue
                result = await self.probe_board(provider, slug)
                if self.delay_seconds > 0:
                    await asyncio.sleep(self.delay_seconds)
                if result is None:
                    inconclusive = True
                elif result.found:
                    return result
        return None if inconclusive else ProbeResult(found=False)
