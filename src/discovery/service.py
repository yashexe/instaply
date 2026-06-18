"""Discovery orchestration: candidates -> probe -> relevance -> suggestion.

Suggestions never auto-poll. The user accepts (creating a normal source,
whose first poll is baselined) or rejects (remembered forever).
"""

from __future__ import annotations

import aiosqlite
import structlog

from src.config import settings
from src.discovery import repository as discovery_repo
from src.discovery.models import Candidate, DiscoveryRunStats
from src.discovery.prober import Prober, board_url, normalized_url
from src.discovery.providers import LLMCandidateProvider, SeedListProvider
from src.discovery.relevance import matching_titles
from src.discovery.slugger import guess_slugs, normalize_name_key
from src.preferences.repository import get_preferences
from src.profile.repository import get_active_profile
from src.sources.detector import detect_provider
from src.sources.repository import create_source, list_sources

logger = structlog.get_logger()

EVIDENCE_TITLE_LIMIT = 5


async def _monitored_slugs_and_names(
    db: aiosqlite.Connection, user_id: str
) -> tuple[set[tuple[str, str]], set[str]]:
    """(provider, slug) pairs and company name_keys already monitored."""
    slugs: set[tuple[str, str]] = set()
    names: set[str] = set()
    for source in await list_sources(db, user_id):
        names.add(normalize_name_key(source["company_name"]))
        provider, _, slug = detect_provider(
            source.get("normalized_url") or source["source_url"]
        )
        if provider != "custom" and slug:
            slugs.add((provider, slug.lower()))
    return slugs, names


async def run_discovery(
    db: aiosqlite.Connection,
    user_id: str,
    *,
    use_llm: bool = True,
    prober: Prober | None = None,
) -> DiscoveryRunStats:
    """One discovery pass. Returns run statistics."""
    stats = DiscoveryRunStats()

    preferences = await get_preferences(db, user_id)
    target_roles = (preferences or {}).get("target_roles") or []
    if not target_roles:
        logger.info("discovery.skipped_no_target_roles")
        return stats

    pending = await discovery_repo.count_by_status(db, user_id, "suggested")
    if pending >= settings.discovery_max_suggestions_pending:
        logger.info("discovery.skipped_pending_cap", pending=pending)
        return stats

    profile = await get_active_profile(db, user_id)
    monitored_slugs, monitored_names = await _monitored_slugs_and_names(db, user_id)
    known_keys = await discovery_repo.known_name_keys(db, user_id)
    exclude_names = sorted(
        {(s["company_name"]) for s in await list_sources(db, user_id)}
    )

    providers: list = [SeedListProvider()]
    if use_llm:
        providers.append(LLMCandidateProvider())

    candidates: list[Candidate] = []
    seen_keys: set[str] = set()
    for provider in providers:
        if isinstance(provider, LLMCandidateProvider):
            stats.llm_used = True
        for candidate in await provider.candidates(
            preferences or {}, profile, exclude_names
        ):
            key = normalize_name_key(candidate.company_name)
            if not key or key in seen_keys:
                continue
            seen_keys.add(key)
            candidates.append(candidate)
    stats.candidates = len(candidates)

    prober = prober or Prober()

    for candidate in candidates:
        key = normalize_name_key(candidate.company_name)
        if key in known_keys or key in monitored_names:
            stats.skipped_known += 1
            continue
        if pending + stats.suggested >= settings.discovery_max_suggestions_pending:
            logger.info("discovery.stopped_pending_cap")
            break
        if prober.exhausted:
            logger.info("discovery.stopped_probe_budget", probed=prober.probes_used)
            break

        if candidate.known_provider and candidate.known_slug:
            slugs = [candidate.known_slug]
        else:
            slugs = guess_slugs(candidate.company_name)
        if not slugs:
            continue

        probes_before = prober.probes_used
        result = await prober.probe_company(slugs)
        stats.probed += prober.probes_used - probes_before

        if result is None:
            # Inconclusive (budget, breaker, transient errors): record
            # nothing so the company is retried next run.
            continue

        if not result.found:
            await _record(
                db, user_id, candidate, key,
                status="not_found", provider=None, slug=None,
                job_count=0, titles=[],
            )
            stats.not_found += 1
            continue

        if (result.provider, result.slug.lower()) in monitored_slugs:
            stats.skipped_known += 1
            continue

        stats.boards_found += 1
        matched = matching_titles(result.titles, target_roles)
        if len(matched) >= settings.discovery_min_matching_titles:
            await _record(
                db, user_id, candidate, key,
                status="suggested", provider=result.provider, slug=result.slug,
                job_count=result.job_count,
                titles=matched[:EVIDENCE_TITLE_LIMIT],
            )
            stats.suggested += 1
        else:
            await _record(
                db, user_id, candidate, key,
                status="irrelevant", provider=result.provider, slug=result.slug,
                job_count=result.job_count, titles=[],
            )
            stats.irrelevant += 1

    logger.info(
        "discovery.run_complete",
        candidates=stats.candidates,
        probed=stats.probed,
        suggested=stats.suggested,
        not_found=stats.not_found,
        irrelevant=stats.irrelevant,
        skipped_known=stats.skipped_known,
    )
    return stats


async def _record(
    db: aiosqlite.Connection,
    user_id: str,
    candidate: Candidate,
    name_key: str,
    *,
    status: str,
    provider: str | None,
    slug: str | None,
    job_count: int,
    titles: list[str],
) -> None:
    """Insert a discovery outcome; on conflict (stale recheckable row),
    refresh that row instead."""
    b_url = board_url(provider, slug) if provider and slug else None
    n_url = normalized_url(provider, slug) if provider and slug else None
    inserted = await discovery_repo.insert_discovered(
        db,
        user_id,
        company_name=candidate.company_name,
        name_key=name_key,
        status=status,
        origin=candidate.origin,
        provider=provider,
        slug=slug,
        board_url=b_url,
        normalized_url=n_url,
        reason=candidate.reason,
        job_count=job_count,
        matching_titles=titles,
    )
    if inserted is None:
        await discovery_repo.reprobe_update(
            db,
            user_id,
            name_key,
            status=status,
            provider=provider,
            slug=slug,
            board_url=b_url,
            normalized_url=n_url,
            job_count=job_count,
            matching_titles=titles,
        )


async def accept_suggestion(
    db: aiosqlite.Connection,
    user_id: str,
    discovered_id: str,
) -> dict | None:
    """Promote a suggestion to a monitored source."""
    suggestion = await discovery_repo.get_suggestion(db, discovered_id, user_id)
    if suggestion is None or suggestion["status"] != "suggested":
        return None
    if not suggestion.get("provider") or not suggestion.get("normalized_url"):
        return None

    source_id = await create_source(
        db,
        user_id,
        company_name=suggestion["company_name"],
        provider=suggestion["provider"],
        source_url=suggestion.get("board_url") or suggestion["normalized_url"],
        normalized_url=suggestion["normalized_url"],
        priority="normal",
    )
    updated = await discovery_repo.set_status(
        db, discovered_id, user_id, "accepted", source_id=source_id
    )
    logger.info(
        "discovery.accepted",
        discovered_id=discovered_id,
        source_id=source_id,
        company=suggestion["company_name"],
    )
    return updated


async def reject_suggestion(
    db: aiosqlite.Connection,
    user_id: str,
    discovered_id: str,
) -> dict | None:
    """Permanently dismiss a suggestion."""
    suggestion = await discovery_repo.get_suggestion(db, discovered_id, user_id)
    if suggestion is None or suggestion["status"] != "suggested":
        return None
    return await discovery_repo.set_status(db, discovered_id, user_id, "rejected")
