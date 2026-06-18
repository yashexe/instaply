"""
LLM judge for the daily match shortlist.

Takes the top unjudged alert/digest matches by deterministic score and has
the LLM evaluate each one against the actual resume and posting text. The
LLM's fit score is blended with the deterministic score, explanations are
replaced with grounded ones, and the decision is re-derived (a judged
digest match can be promoted to an alert and vice versa).

Quota discipline, in order of defense:
- a per-day call slice (settings.llm_judge_daily_budget) enforced through
  the shared llm.budget ledger, so judging can't starve extraction;
- the shared cooldown: a rate-limit error stops the whole run;
- per-match attempt cap (settings.judge_max_attempts): a match that fails
  repeatedly keeps its template explanation and is never retried again.

Anything not judged today is simply still pending: the next run picks up
the current top of the shortlist again.
"""

from __future__ import annotations

from datetime import datetime, timezone

import aiosqlite
import structlog

from src.config import settings
from src.jobs import repository as jobs_repository
from src.matching import repository as matching_repository
from src.profile import repository as profile_repository

logger = structlog.get_logger()

# Blend: the LLM read the actual documents, the deterministic score is the
# tiebreaker that keeps one bad generation from swinging a decision alone.
LLM_SCORE_WEIGHT = 0.6

JUDGE_SYSTEM_PROMPT = """\
You are an expert technical recruiter deciding whether a candidate should
apply to a job. Use only the supplied resume and job posting. Be critical
and realistic: most jobs are a partial fit.

Return JSON:
{
  "fit_score": 0-100,
  "verdict": "apply_now" | "worth_a_look" | "skip",
  "summary": "one or two sentences naming the strongest reason to apply and the biggest risk",
  "matching_reasons": ["3 to 5 specific bullets grounded in the resume and posting"],
  "missing_requirements": ["0 to 5 bullets"],
  "uncertainties": ["0 to 3 bullets"],
  "cover_letter": "see the cover letter instruction in the user message; omit this field entirely when it does not apply"
}

Scoring guide:
- 85-100: exceptional fit, apply immediately
- 70-84: strong fit, clearly worth applying
- 50-69: partial fit, apply only if the role is otherwise attractive
- below 50: weak fit, likely rejected at screening
"""

COVER_LETTER_STYLE = """\
Voice and style rules for the cover letter, follow them strictly:
- Write in the candidate's voice: confident, direct, technical, and human.
- No corporate fluff, no poetic language, no over-polished essay tone.
- Use concrete engineering details from the resume, plain sentences, and
  short paragraphs.
- It should sound like a thoughtful software engineer applying seriously,
  not an English major or a marketing team.
- Do not use em dashes, colons, or semicolons anywhere in the letter.
- Around 200 words. No address block or date, start at the greeting and
  end with a sign-off using the candidate's first name."""


def _letter_fit_threshold(deterministic_score: int, alert_threshold: int) -> int | None:
    """Minimum LLM fit_score at which the blended score reaches the alert tier.

    Computed before the request so the cover letter is generated in the same
    call, exactly when the match will become an alert. None when no fit
    score could reach the tier (don't ask for a letter at all).
    """
    import math

    needed = (alert_threshold - (1 - LLM_SCORE_WEIGHT) * deterministic_score) / LLM_SCORE_WEIGHT
    if needed > 100:
        return None
    return max(0, math.ceil(needed))


def _build_judge_prompt(
    job: dict, profile: dict, match: dict, letter_fit_threshold: int | None,
) -> str:
    locations = job.get("locations") or []
    salary = ""
    if job.get("salary_min") or job.get("salary_max"):
        salary = f"{job.get('salary_min') or '?'} - {job.get('salary_max') or '?'} {job.get('salary_currency') or ''}"
    lines = [
        "## Job Posting",
        f"Title: {job.get('title')}",
        f"Company: {job.get('company_name')}",
        f"Locations: {', '.join(locations) if locations else 'not stated'}",
        f"Remote policy: {job.get('remote_policy') or 'not stated'}",
        f"Salary: {salary or 'not stated'}",
        "",
        (job.get("description_text") or "")[:6000],
        "",
        "## Candidate Resume",
        (profile.get("resume_text") or "")[:6000],
        "",
        "## Pre-screen (deterministic, for reference only)",
        f"Score: {match.get('score')}/100",
        "",
        "## Cover letter instruction",
    ]
    if letter_fit_threshold is None:
        lines.append("Do not write a cover letter. Omit the cover_letter field.")
    else:
        lines.extend([
            f"If your fit_score is {letter_fit_threshold} or higher, also write "
            "a cover letter draft for this application in the cover_letter "
            "field. If your fit_score is lower, omit the cover_letter field.",
            "",
            COVER_LETTER_STYLE,
        ])
    return "\n".join(lines)


async def _list_pending(
    db: aiosqlite.Connection,
    user_id: str,
    limit: int,
) -> list[dict]:
    """Top unjudged alert/digest matches, best deterministic score first."""
    cursor = await db.execute(
        """
        SELECT * FROM match_results
        WHERE user_id = ?
          AND decision IN ('alert', 'digest')
          AND json_extract(trace, '$.llm_judge') IS NULL
          AND COALESCE(json_extract(trace, '$.llm_judge_attempts'), 0) < ?
        ORDER BY score DESC, created_at DESC
        LIMIT ?
        """,
        (user_id, settings.judge_max_attempts, limit),
    )
    rows = await cursor.fetchall()
    return [matching_repository._deserialize_row(row) for row in rows]


async def _record_attempt(db: aiosqlite.Connection, match: dict) -> None:
    trace = match.get("trace") or {}
    trace["llm_judge_attempts"] = int(trace.get("llm_judge_attempts") or 0) + 1
    match["trace"] = trace
    await matching_repository.update_match_result(db, match["id"], match)


def _validated(result: dict) -> dict | None:
    if not isinstance(result, dict):
        return None
    try:
        fit_score = int(result.get("fit_score"))
    except (TypeError, ValueError):
        return None
    if not 0 <= fit_score <= 100:
        return None
    # The letter is best-effort: a mangled or missing field must never
    # invalidate the judgment it rode along with.
    cover_letter = result.get("cover_letter")
    if not isinstance(cover_letter, str) or not cover_letter.strip():
        cover_letter = None
    return {
        "fit_score": fit_score,
        "verdict": str(result.get("verdict") or "worth_a_look"),
        "summary": str(result.get("summary") or "").strip(),
        "matching_reasons": [str(x) for x in result.get("matching_reasons") or []],
        "missing_requirements": [str(x) for x in result.get("missing_requirements") or []],
        "uncertainties": [str(x) for x in result.get("uncertainties") or []],
        "cover_letter": cover_letter.strip() if cover_letter else None,
    }


async def judge_pending_matches(
    db: aiosqlite.Connection,
    user_id: str = "default",
    *,
    limit: int | None = None,
    alert_channel: str | None = None,
) -> dict:
    """Judge the pending shortlist. Returns a summary with a stop reason.

    stopped_reason is None (worked through the list), 'budget'
    (daily judge slice exhausted), 'cooldown' (provider rate-limited),
    or 'not_configured'.
    """
    from src.alerts.service import send_combined_alert
    from src.llm import budget, cooldown
    from src.matching.service import _decision_for_score
    from src.preferences import repository as preferences_repository

    summary = {"judged": 0, "promoted": 0, "demoted": 0, "failed": 0,
               "pending": 0, "stopped_reason": None}
    # Collect promotions and deliver them as one combined email at the end of
    # the run instead of one email per promoted match.
    alert_sink: list = []

    if not settings.llm_configured:
        summary["stopped_reason"] = "not_configured"
        return summary

    profile = await profile_repository.get_active_profile(db, user_id)
    if profile is None:
        return summary

    preferences = await preferences_repository.get_preferences(db, user_id)
    if preferences is None:
        preferences = preferences_repository.default_preferences(user_id)

    matches = await _list_pending(db, user_id, limit or settings.judge_top_k)
    summary["pending"] = len(matches)

    for match in matches:
        if cooldown.is_cooling_down():
            summary["stopped_reason"] = "cooldown"
            break
        if not await budget.spend("judge"):
            summary["stopped_reason"] = "budget"
            break

        job = await jobs_repository.get_job(db, match["job_posting_id"])
        if job is None:
            await _record_attempt(db, match)
            continue

        alert_threshold = (
            preferences.get("alert_threshold") or settings.default_alert_threshold
        )
        letter_threshold = _letter_fit_threshold(int(match["score"]), alert_threshold)

        try:
            from src.llm.factory import get_llm_provider

            provider = get_llm_provider()
            raw = await provider.structured_output(
                system_prompt=JUDGE_SYSTEM_PROMPT,
                user_prompt=_build_judge_prompt(job, profile, match, letter_threshold),
            )
        except Exception as exc:
            summary["failed"] += 1
            await _record_attempt(db, match)
            if cooldown.note_error(exc):
                summary["stopped_reason"] = "cooldown"
                break
            logger.exception("judge.llm_error", match_id=match["id"])
            continue

        judgment = _validated(raw)
        if judgment is None:
            summary["failed"] += 1
            await _record_attempt(db, match)
            logger.warning("judge.invalid_response", match_id=match["id"])
            continue

        old_decision = match["decision"]
        deterministic_score = int(match["score"])
        blended = round(
            LLM_SCORE_WEIGHT * judgment["fit_score"]
            + (1 - LLM_SCORE_WEIGHT) * deterministic_score
        )

        breakdown = match.get("score_breakdown") or {}
        # The LLM read the full posting and resume; data coverage is no
        # longer the limiting factor for this match.
        confidence = max(int(breakdown.get("confidence") or 0), 85)
        breakdown["confidence"] = confidence
        decision = _decision_for_score(
            blended, confidence, match.get("hard_filter_results") or {}, preferences,
        )

        trace = match.get("trace") or {}
        trace["llm_judge"] = {
            "fit_score": judgment["fit_score"],
            "verdict": judgment["verdict"],
            "deterministic_score": deterministic_score,
            "judged_at": datetime.now(timezone.utc).isoformat(),
        }
        match.update(
            score=blended,
            decision=decision,
            score_breakdown=breakdown,
            matching_reasons=judgment["matching_reasons"],
            missing_requirements=judgment["missing_requirements"],
            uncertainties=judgment["uncertainties"],
            summary=judgment["summary"] or match.get("summary"),
            cover_letter=judgment["cover_letter"] or match.get("cover_letter"),
            trace=trace,
        )
        await matching_repository.update_match_result(db, match["id"], match)

        if decision == "alert" and old_decision != "alert":
            summary["promoted"] += 1
            updated = await matching_repository.get_match_result(db, match["id"])
            alert_sink.append((updated, job))
        elif decision != "alert" and old_decision == "alert":
            summary["demoted"] += 1

        summary["judged"] += 1
        logger.info(
            "judge.match_judged",
            match_id=match["id"],
            fit_score=judgment["fit_score"],
            blended=blended,
            decision=decision,
        )

    if alert_sink:
        await send_combined_alert(db, alert_sink, force_channel=alert_channel)

    return summary
