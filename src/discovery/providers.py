"""Candidate providers: where discovery gets company names to probe.

Two implementations, both feeding the same validation pipeline:
- SeedListProvider: bundled seeds.json filtered by the user's domains.
  Works with no LLM key, mirroring the app's heuristic-fallback pattern.
- LLMCandidateProvider: asks the configured LLM for companies matching
  the profile/preferences, excluding ones we already know about.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

import structlog

from src.config import settings
from src.discovery.models import Candidate
from src.llm import budget

logger = structlog.get_logger()

_SEEDS_PATH = Path(__file__).parent / "seeds.json"


class CandidateProvider(Protocol):
    async def candidates(
        self,
        preferences: dict,
        profile: dict | None,
        known_companies: list[str],
    ) -> list[Candidate]: ...


class SeedListProvider:
    """Bundled list of companies tagged with taxonomy domains."""

    def __init__(self, seeds_path: Path = _SEEDS_PATH) -> None:
        self._seeds_path = seeds_path

    def _load(self) -> list[dict]:
        try:
            return json.loads(self._seeds_path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            logger.error("discovery.seeds_unreadable", error=str(exc))
            return []

    async def candidates(
        self,
        preferences: dict,
        profile: dict | None,
        known_companies: list[str],
    ) -> list[Candidate]:
        user_domains: set[str] = set()
        structured = (profile or {}).get("structured_profile") or {}
        user_domains.update(structured.get("domains") or [])

        seeds = self._load()
        results: list[Candidate] = []
        for seed in seeds:
            seed_domains = set(seed.get("domains") or [])
            # With no profile domains to filter on, every seed qualifies;
            # the probe budget and pending cap keep the run bounded.
            if user_domains and not (seed_domains & user_domains):
                continue
            known = seed.get("known") or {}
            results.append(
                Candidate(
                    company_name=seed["name"],
                    origin="seed_list",
                    reason=(
                        "Seed list match on "
                        + ", ".join(sorted(seed_domains & user_domains))
                        if user_domains
                        else "Seed list"
                    ),
                    known_provider=known.get("provider"),
                    known_slug=known.get("slug"),
                )
            )
        return results


_LLM_SYSTEM_PROMPT = (
    "You suggest companies that are likely to be hiring for a job seeker. "
    "Suggest real, currently operating companies that plausibly use a public "
    "Greenhouse, Lever, or Ashby job board. Prefer mid-size technology "
    "companies over giant enterprises. Never suggest companies in the "
    "exclusion list. Respond with JSON only."
)

_LLM_SCHEMA = {
    "type": "object",
    "properties": {
        "companies": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "company_name": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["company_name"],
            },
        }
    },
    "required": ["companies"],
}


class LLMCandidateProvider:
    """LLM-backed company suggestions; silently yields nothing when no
    LLM is configured or the discovery budget is spent."""

    async def candidates(
        self,
        preferences: dict,
        profile: dict | None,
        known_companies: list[str],
    ) -> list[Candidate]:
        if not settings.llm_configured:
            return []
        if not await budget.spend("discovery", 1):
            logger.info("discovery.llm_budget_exhausted")
            return []

        structured = (profile or {}).get("structured_profile") or {}
        user_prompt = json.dumps(
            {
                "target_roles": preferences.get("target_roles") or [],
                "seniority_levels": preferences.get("seniority_levels") or [],
                "locations": preferences.get("locations") or [],
                "remote_policy": preferences.get("remote_policy") or "any",
                "skills": (preferences.get("must_have_skills") or [])
                + (preferences.get("nice_to_have_skills") or []),
                "candidate_domains": structured.get("domains") or [],
                "exclude_companies": sorted(known_companies),
                "max_companies": settings.discovery_max_llm_candidates,
            }
        )

        try:
            from src.llm.factory import get_llm_provider

            provider = get_llm_provider()
            data = await provider.structured_output(
                _LLM_SYSTEM_PROMPT, user_prompt, schema=_LLM_SCHEMA
            )
        except Exception as exc:
            logger.warning("discovery.llm_failed", error=str(exc))
            return []

        companies = (data or {}).get("companies") or []
        results: list[Candidate] = []
        for entry in companies[: settings.discovery_max_llm_candidates]:
            name = (entry.get("company_name") or "").strip()
            if not name:
                continue
            results.append(
                Candidate(
                    company_name=name,
                    origin="llm",
                    reason=entry.get("reason"),
                )
            )
        return results
