"""Matching orchestration service."""

from __future__ import annotations

import json

import aiosqlite
import structlog

from src.alerts.service import create_and_send_alert
from src.config import settings
from src.jobs import repository as jobs_repository
from src.matching import repository as matching_repository
from src.matching import embeddings
from src.matching.explainer import explain_match
from src.matching.extractor import extract_requirements
from src.matching.filters import apply_hard_filters
from src.matching.scorer import score_job
from src.preferences import repository as preferences_repository
from src.profile import repository as profile_repository

logger = structlog.get_logger()

DEFAULT_USER_ID = "default"


def _json_loads_safe(value, default):
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


def _decision_for_score(
    score: int,
    confidence: int,
    hard_filter_results: dict,
    preferences: dict,
) -> str:
    """Turn score, data confidence, and hard filters into a match decision.

    A high score on mostly-unknown data is not alert-worthy: it demotes to
    digest, or to ignore when almost nothing about the posting was known.
    """
    if hard_filter_results.get("overall") == "rejected":
        return "rejected"
    alert_threshold = preferences.get("alert_threshold") or settings.default_alert_threshold
    if score >= alert_threshold and confidence >= settings.alert_min_confidence:
        return "alert"
    if score >= settings.digest_threshold and confidence >= settings.digest_min_confidence:
        return "digest"
    return "ignore"


def _job_text(job: dict) -> str:
    """Build the text used for requirement extraction."""
    pieces = [
        job.get("title") or "",
        job.get("department") or "",
        " ".join(job.get("locations") or []),
        job.get("description_text") or "",
    ]
    return "\n\n".join(piece for piece in pieces if piece)


async def score_job_for_user(
    db: aiosqlite.Connection,
    job_id: str,
    user_id: str = DEFAULT_USER_ID,
    *,
    send_alerts: bool = True,
    alert_channel: str | None = None,
    alert_sink: list | None = None,
    use_llm: bool = True,
    force: bool = False,
) -> dict | None:
    """Score a job against the active profile and create an alert if needed.

    Pass force=True to recompute and update an existing match result in
    place (e.g. after scorer or profile changes) instead of returning it.

    When alert_sink is provided, an alert-worthy match is appended to it as a
    (match_result, job) tuple instead of being emailed immediately, so a caller
    scoring many jobs (a poll) can batch them into one combined email.
    """
    job = await jobs_repository.get_job(db, job_id)
    if job is None:
        return None

    profile = await profile_repository.get_active_profile(db, user_id)
    if profile is None:
        logger.info("matching.skipped_no_profile", job_id=job_id)
        return None

    existing_match = None
    if await matching_repository.match_exists(db, user_id, profile["id"], job_id):
        existing_match = await matching_repository.get_match_for_job(db, user_id, job_id)
        if not force:
            logger.debug("matching.skipped_existing", job_id=job_id)
            return existing_match

    preferences = await preferences_repository.get_preferences(db, user_id)
    if preferences is None:
        preferences = preferences_repository.default_preferences(user_id)

    extracted_requirements = job.get("extracted_requirements")
    if not extracted_requirements:
        extracted_requirements = await extract_requirements(
            _job_text(job), use_llm=use_llm,
        )
        await jobs_repository.update_extracted_requirements(
            db,
            job_id,
            extracted_requirements,
        )

    hard_filters = apply_hard_filters(job, preferences, profile)
    semantic_similarity = await embeddings.semantic_similarity_for(db, job, profile)
    score, breakdown = score_job(
        job,
        preferences,
        profile,
        extracted_requirements,
        hard_filters,
        semantic_similarity=semantic_similarity,
    )
    confidence = breakdown.get("confidence", 0)

    # A forced rescore must not discard an existing LLM judgment (it cost
    # quota and read the full documents): re-blend it with the fresh
    # deterministic score and keep its grounded explanations.
    prior_trace = (existing_match or {}).get("trace") or {}
    prior_judgment = (
        prior_trace.get("llm_judge") if isinstance(prior_trace, dict) else None
    )
    if prior_judgment:
        from src.matching.judge import LLM_SCORE_WEIGHT

        score = round(
            LLM_SCORE_WEIGHT * prior_judgment["fit_score"]
            + (1 - LLM_SCORE_WEIGHT) * score
        )
        confidence = max(confidence, 85)
        breakdown["confidence"] = confidence

    decision = _decision_for_score(score, confidence, hard_filters, preferences)

    if prior_judgment:
        explanation = {
            "matching_reasons": existing_match.get("matching_reasons") or [],
            "missing_requirements": existing_match.get("missing_requirements") or [],
            "uncertainties": existing_match.get("uncertainties") or [],
            "summary": existing_match.get("summary"),
        }
    else:
        # LLM quota is scarce; only alert-worthy matches get an LLM explanation.
        explanation = await explain_match(
            job, profile, breakdown, score, use_llm=use_llm and decision == "alert",
        )

    result_payload = {
        "user_id": user_id,
        "candidate_profile_id": profile["id"],
        "job_posting_id": job_id,
        "score": score,
        "decision": decision,
        "hard_filter_results": hard_filters,
        "score_breakdown": breakdown,
        "matching_reasons": explanation.get("matching_reasons", []),
        "missing_requirements": explanation.get("missing_requirements", []),
        "uncertainties": explanation.get("uncertainties", []),
        "summary": explanation.get("summary"),
        "trace": {
            "profile_version": profile.get("version"),
            "extracted_requirements": extracted_requirements,
            "alert_threshold": preferences.get("alert_threshold"),
            "confidence": confidence,
            "semantic_similarity": semantic_similarity,
        },
    }
    if prior_judgment:
        result_payload["trace"]["llm_judge"] = prior_judgment
        result_payload["cover_letter"] = existing_match.get("cover_letter")
    if prior_trace.get("llm_judge_attempts"):
        result_payload["trace"]["llm_judge_attempts"] = prior_trace["llm_judge_attempts"]
    if existing_match:
        match_id = existing_match["id"]
        await matching_repository.update_match_result(db, match_id, result_payload)
    else:
        match_id = await matching_repository.create_match_result(db, result_payload)
    match_result = await matching_repository.get_match_result(db, match_id)
    if match_result is None:
        raise RuntimeError("Failed to create match result")

    if decision == "alert" and send_alerts:
        if alert_sink is not None:
            alert_sink.append((match_result, job))
        else:
            await create_and_send_alert(
                db, match_result=match_result, job=job, force_channel=alert_channel,
            )

    logger.info(
        "matching.completed",
        job_id=job_id,
        score=score,
        decision=decision,
    )
    return match_result


async def rescore_backlog(
    db: aiosqlite.Connection,
    user_id: str = DEFAULT_USER_ID,
    *,
    limit: int | None = None,
    use_llm: bool = False,
    alert_channel: str | None = "in_app",
    rescore_all: bool = False,
    progress_callback=None,
) -> dict:
    """Score every active job that has no match result for the active profile.

    Used to catch up after baselined first polls or a profile change. Alerts
    default to in_app so a large backfill cannot flood the email channel.
    Pass rescore_all=True to also recompute existing match results in place
    (after scorer, threshold, or profile changes).
    """
    profile = await profile_repository.get_active_profile(db, user_id)
    if profile is None:
        return {"error": "no_active_profile", "total": 0, "scored": 0, "decisions": {}}

    if rescore_all:
        job_ids = await matching_repository.list_active_job_ids(db, limit=limit)
    else:
        job_ids = await matching_repository.list_unscored_job_ids(
            db, user_id, profile["id"], limit=limit,
        )
    decisions: dict[str, int] = {}
    scored = 0
    for index, job_id in enumerate(job_ids, start=1):
        match = await score_job_for_user(
            db,
            job_id,
            user_id,
            send_alerts=True,
            alert_channel=alert_channel,
            use_llm=use_llm,
            force=rescore_all,
        )
        if match is not None:
            scored += 1
            decisions[match["decision"]] = decisions.get(match["decision"], 0) + 1
        if progress_callback is not None:
            progress_callback(index, len(job_ids))

    logger.info(
        "matching.rescore_complete",
        total=len(job_ids),
        scored=scored,
        decisions=decisions,
    )
    return {
        "error": None,
        "total": len(job_ids),
        "scored": scored,
        "decisions": decisions,
    }

