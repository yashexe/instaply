"""
LLM-powered job requirement extraction.

Calls the configured LLM provider to extract structured hiring
requirements from a raw job description.
"""

from __future__ import annotations

import re

import structlog

from src.common.taxonomy import (
    extract_domains,
    extract_skill_hits,
    infer_role_family,
)
from src.config import settings

logger = structlog.get_logger()

SYSTEM_PROMPT = """\
You are extracting structured hiring requirements from a job posting.
Return only JSON matching the requested schema.
Do not infer requirements that are not stated or strongly implied.
Use null or unknown when the posting is unclear.

Extract:
- role_family (string)
- seniority (string: intern, junior, mid, senior, staff, principal, lead, manager, director, unknown)
- required_skills (array of strings)
- preferred_skills (array of strings)
- years_experience_min (integer or null)
- locations (array of strings)
- remote_policy (string: remote, hybrid, onsite, unknown)
- employment_type (string: full_time, contract, internship, unknown)
- salary_range (object with min, max, currency or null)
- visa_sponsorship (string: yes, no, unknown)
- responsibilities (array of strings)
- domain_signals (array of strings)
- disqualifying_constraints (array of strings)
"""

EMPTY_RESULT: dict = {
    "role_family": None,
    "seniority": "unknown",
    "required_skills": [],
    "preferred_skills": [],
    "years_experience_min": None,
    "locations": [],
    "remote_policy": "unknown",
    "employment_type": "unknown",
    "salary_range": None,
    "visa_sponsorship": "unknown",
    "responsibilities": [],
    "domain_signals": [],
    "disqualifying_constraints": [],
}

def _contains_phrase(text: str, phrase: str) -> bool:
    pattern = re.compile(r"\b" + re.escape(phrase.lower()) + r"\b", re.IGNORECASE)
    return bool(pattern.search(text))


def heuristic_extract_requirements(job_text: str) -> dict:
    """Extract a useful baseline without an LLM."""
    text = job_text.lower()
    result = dict(EMPTY_RESULT)

    skill_names = [name for name, _category in extract_skill_hits(job_text)]
    result["required_skills"] = skill_names

    preferred_section = ""
    preferred_match = re.search(
        r"(preferred|nice to have|bonus)(.*)",
        job_text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if preferred_match:
        preferred_section = preferred_match.group(2).lower()
    if preferred_section:
        result["preferred_skills"] = [
            name for name, _category in extract_skill_hits(preferred_section)
        ]

    year_match = re.search(r"(\d+)\+?\s+years?", text)
    if year_match:
        result["years_experience_min"] = int(year_match.group(1))

    if any(word in text for word in ("staff", "principal")):
        result["seniority"] = "staff" if "staff" in text else "principal"
    elif any(word in text for word in ("senior", "sr.")):
        result["seniority"] = "senior"
    elif any(word in text for word in ("junior", "entry level", "entry-level")):
        result["seniority"] = "junior"

    if "remote" in text:
        result["remote_policy"] = "remote"
    if "hybrid" in text:
        result["remote_policy"] = "hybrid"
    if any(word in text for word in ("onsite", "on-site", "in office", "in-office")):
        result["remote_policy"] = "onsite"

    if any(
        phrase in text
        for phrase in (
            "visa sponsorship is not mentioned",
            "sponsorship is not mentioned",
        )
    ):
        result["visa_sponsorship"] = "unknown"
    elif any(
        phrase in text
        for phrase in ("no visa", "unable to sponsor", "do not sponsor")
    ):
        result["visa_sponsorship"] = "no"
    elif any(phrase in text for phrase in ("will sponsor", "sponsorship available")):
        result["visa_sponsorship"] = "yes"

    result["role_family"] = infer_role_family(job_text)
    result["domain_signals"] = extract_domains(job_text)

    return result


async def extract_requirements(job_text: str, *, use_llm: bool = True) -> dict:
    """
    Extract structured requirements from a job posting via the LLM.

    Falls back to a minimal empty dict if the LLM provider is
    unavailable or the call fails.
    """
    if not job_text or not job_text.strip():
        logger.warning("extractor.empty_input")
        return dict(EMPTY_RESULT)

    if not use_llm:
        return heuristic_extract_requirements(job_text)

    if not settings.llm_configured:
        logger.info("extractor.llm_not_configured", fallback="heuristic")
        return heuristic_extract_requirements(job_text)

    from src.llm import budget, cooldown

    if cooldown.is_cooling_down():
        logger.info(
            "extractor.llm_cooldown",
            fallback="heuristic",
            seconds_remaining=round(cooldown.seconds_remaining(), 1),
        )
        return heuristic_extract_requirements(job_text)

    if not await budget.spend("extract"):
        return heuristic_extract_requirements(job_text)

    try:
        from src.llm.factory import get_llm_provider

        provider = get_llm_provider()
        result = await provider.structured_output(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=job_text,
        )

        if not isinstance(result, dict):
            logger.warning("extractor.unexpected_type", type=type(result).__name__)
            return dict(EMPTY_RESULT)

        # Merge with defaults to guarantee all keys exist
        merged = dict(EMPTY_RESULT)
        merged.update(result)
        return merged

    except ImportError:
        logger.warning("extractor.llm_factory_not_available")
        return heuristic_extract_requirements(job_text)
    except Exception as exc:
        if not cooldown.note_error(exc):
            logger.exception("extractor.llm_error")
        return heuristic_extract_requirements(job_text)
