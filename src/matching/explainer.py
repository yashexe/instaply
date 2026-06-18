"""
LLM-powered match explanation generator.

Produces human-readable explanations of why a job does or does not
match a candidate profile, using the score breakdown as ground truth.
"""

from __future__ import annotations

import json
from typing import Any

import structlog

from src.config import settings

logger = structlog.get_logger()

SYSTEM_PROMPT = """\
You are explaining why a job does or does not match a candidate profile.
Use the supplied score breakdown and facts only.
Do not invent resume details.
Keep the explanation concise and useful for a job seeker deciding whether to apply quickly.

Return JSON:
{
  "summary": "one sentence",
  "matching_reasons": ["3 to 5 bullets"],
  "missing_requirements": ["0 to 5 bullets"],
  "uncertainties": ["0 to 5 bullets"]
}
"""


def _json_loads_safe(value: Any, default: Any = None) -> Any:
    if value is None:
        return default
    if isinstance(value, (list, dict)):
        return value
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return default


def _build_user_prompt(
    job_data: dict,
    profile: dict,
    score_breakdown: dict,
    total_score: int,
) -> str:
    """Compose a concise user prompt summarizing job, profile, and scores."""
    profile_data = _json_loads_safe(profile.get("structured_profile"), {})

    lines = [
        "## Job Posting",
        f"Title: {job_data.get('title', 'N/A')}",
        f"Company: {job_data.get('company_name', 'N/A')}",
        f"Locations: {json.dumps(_json_loads_safe(job_data.get('locations'), []))}",
        f"Remote Policy: {job_data.get('remote_policy', 'unknown')}",
        f"Salary Range: {job_data.get('salary_min', 'N/A')} – {job_data.get('salary_max', 'N/A')} {job_data.get('salary_currency', '')}",
        "",
        "## Candidate Profile",
    ]

    if isinstance(profile_data, dict):
        lines.append(f"Skills: {json.dumps(profile_data.get('skills', []))}")
        lines.append(f"Roles: {json.dumps(profile_data.get('roles', []))}")
        lines.append(
            f"Years of Experience: {profile_data.get('years_of_experience', 'N/A')}"
        )
        lines.append(f"Domains: {json.dumps(profile_data.get('domains', []))}")
    else:
        lines.append("No structured profile data available.")

    lines.extend([
        "",
        "## Score Breakdown",
        f"Total Score: {total_score}/100",
    ])
    for dim, val in score_breakdown.items():
        lines.append(f"  {dim}: {val}")

    return "\n".join(lines)


def _generate_template_explanation(
    score_breakdown: dict,
    total_score: int,
) -> dict:
    """Generate template-based explanations from score data as LLM fallback.

    Dimensions absent from the breakdown had no real data and are reported
    as unknowns rather than scored.
    """
    matching: list[str] = []
    missing: list[str] = []
    uncertainties: list[str] = []

    dimension_maxes = {
        "semantic_fit": 30,
        "role_title_fit": 15,
        "required_skills_fit": 15,
        "experience_fit": 10,
        "preferences_fit": 15,
        "domain_company_fit": 5,
        "preferred_skills_bonus": 10,
    }
    unknown_notes = {
        "semantic_fit": "Semantic similarity not computed for this posting",
        "required_skills_fit": "Required skills could not be extracted from the posting",
        "experience_fit": "Posting does not state a years-of-experience requirement",
        "preferred_skills_bonus": "Posting lists no preferred skills",
        "role_title_fit": "No target roles to compare the title against",
        "preferences_fit": "Posting has no location, remote, or salary data",
        "domain_company_fit": "Your profile lists no domains to compare against",
    }

    for dim, max_val in dimension_maxes.items():
        if dim not in score_breakdown:
            uncertainties.append(unknown_notes[dim])
            continue
        val = score_breakdown[dim]
        pct = val / max_val if max_val > 0 else 0
        label = dim.replace("_", " ").title()

        if pct >= 0.8:
            matching.append(f"Strong {label.lower()}")
        elif pct >= 0.5:
            uncertainties.append(f"Moderate {label.lower()} ({val}/{max_val})")
        elif pct < 0.3 and max_val >= 10:
            missing.append(f"Low {label.lower()} ({val}/{max_val})")

    if score_breakdown.get("required_skills_gate"):
        missing.append(
            "Score capped: the posting's required skills are mostly missing "
            "from your profile"
        )

    confidence = score_breakdown.get("confidence")
    if confidence is not None and confidence < 50:
        uncertainties.append(
            f"Low data confidence ({confidence}%) — score is based on "
            "limited information"
        )

    if total_score >= 85:
        summary = "This job is a strong match for your profile."
    elif total_score >= 70:
        summary = "This job is a good match with some areas to verify."
    elif total_score >= 55:
        summary = "This job partially matches your profile."
    else:
        summary = "This job is a weak match for your profile."

    return {
        "summary": summary,
        "matching_reasons": matching or ["No strong matching dimensions identified"],
        "missing_requirements": missing,
        "uncertainties": uncertainties,
    }


async def explain_match(
    job_data: dict,
    profile: dict,
    score_breakdown: dict,
    total_score: int,
    *,
    use_llm: bool = True,
) -> dict:
    """
    Generate an LLM-powered explanation for a match result.

    Pass use_llm=False to skip the LLM entirely (e.g. for matches the
    user will never see). Falls back to template-based explanations on
    failure or while the LLM is in a rate-limit cooldown.
    """
    if not use_llm:
        return _generate_template_explanation(score_breakdown, total_score)

    if not settings.llm_configured:
        logger.info("explainer.llm_not_configured", fallback="template")
        return _generate_template_explanation(score_breakdown, total_score)

    from src.llm import budget, cooldown

    if cooldown.is_cooling_down():
        logger.info(
            "explainer.llm_cooldown",
            fallback="template",
            seconds_remaining=round(cooldown.seconds_remaining(), 1),
        )
        return _generate_template_explanation(score_breakdown, total_score)

    if not await budget.spend("explain"):
        return _generate_template_explanation(score_breakdown, total_score)

    try:
        from src.llm.factory import get_llm_provider

        provider = get_llm_provider()
        user_prompt = _build_user_prompt(
            job_data, profile, score_breakdown, total_score,
        )

        result = await provider.structured_output(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=user_prompt,
        )

        if isinstance(result, dict):
            # Ensure all expected keys
            return {
                "summary": result.get("summary", ""),
                "matching_reasons": result.get("matching_reasons", []),
                "missing_requirements": result.get("missing_requirements", []),
                "uncertainties": result.get("uncertainties", []),
            }

        logger.warning("explainer.unexpected_type", type=type(result).__name__)
    except ImportError:
        logger.warning("explainer.llm_factory_not_available")
    except Exception as exc:
        if not cooldown.note_error(exc):
            logger.exception("explainer.llm_error")

    # Fallback: template-based explanation
    return _generate_template_explanation(score_breakdown, total_score)
