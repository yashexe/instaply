"""
Hard filter engine — ALL DETERMINISTIC, no LLM.

Each filter function takes (job_data, preferences, profile) and returns
'pass', 'fail', or 'uncertain'.  The aggregate `apply_hard_filters`
runs every filter and derives an overall verdict.
"""

from __future__ import annotations

import json
import re
from typing import Any

import structlog

logger = structlog.get_logger()

# ── Seniority keyword mapping ──────────────────────────────────────────────

SENIORITY_KEYWORDS: dict[str, list[str]] = {
    "intern": ["intern", "internship"],
    "junior": ["junior", "jr", "jr.", "entry level", "entry-level", "associate"],
    "mid": ["mid", "mid-level", "mid level", "intermediate"],
    "senior": ["senior", "sr", "sr."],
    "staff": ["staff"],
    "principal": ["principal"],
    "lead": ["lead"],
    "manager": ["manager", "engineering manager", "eng manager"],
    "director": ["director"],
    "vp": ["vp", "vice president", "vice-president"],
    "chief": ["chief", "cto", "ceo", "cfo", "coo", "cpo"],
}

# Related role family clusters — used for "uncertain" classification
RELATED_ROLE_FAMILIES: dict[str, set[str]] = {
    "software engineer": {
        "developer", "programmer", "full stack", "fullstack", "full-stack",
        "backend", "frontend", "front-end", "back-end", "sde", "swe",
        "product engineer", "api engineer",
    },
    "backend engineer": {
        "backend", "back-end", "api engineer", "platform engineer",
        "distributed systems", "server-side", "server side",
    },
    "data engineer": {
        "etl", "data platform", "data pipeline", "data pipelines",
        "analytics engineer", "connector", "integration engineer",
    },
    "data scientist": {
        "machine learning", "ml engineer", "data analyst", "ai engineer",
        "research scientist",
    },
    "machine learning engineer": {
        "ml engineer", "ai engineer", "machine learning", "pytorch",
        "nlp engineer", "applied scientist",
    },
    "product manager": {
        "program manager", "project manager", "product owner", "technical pm",
    },
    "designer": {
        "ux designer", "ui designer", "product designer", "interaction designer",
        "visual designer", "ux/ui",
    },
    "devops": {
        "sre", "site reliability", "platform engineer", "infrastructure",
        "cloud engineer",
    },
    "platform engineer": {
        "sre", "site reliability", "devops", "infrastructure",
        "cloud engineer", "backend engineer",
    },
    "automation engineer": {
        "design automation", "developer tooling", "static analysis",
        "validation automation", "test automation",
    },
}


# ── Helpers ────────────────────────────────────────────────────────────────

def _json_loads_safe(value: Any, default: Any = None) -> Any:
    """Deserialize a JSON string, returning *default* on failure."""
    if value is None:
        return default
    if isinstance(value, (list, dict)):
        return value
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return default


def _normalize(text: str) -> str:
    """Lower-case and strip for comparison."""
    return text.strip().lower()


def _text_contains_keyword(text: str, keyword: str) -> bool:
    """Check if *keyword* appears in *text* as a word-boundary match."""
    pattern = re.compile(r"\b" + re.escape(keyword) + r"\b", re.IGNORECASE)
    return bool(pattern.search(text))


# ── Individual filters ─────────────────────────────────────────────────────

def role_family_filter(
    job_data: dict, preferences: dict, profile: dict,
) -> str:
    """Compare job title against target_roles in preferences."""
    target_roles: list[str] = _json_loads_safe(
        preferences.get("target_roles"), []
    )
    if not target_roles:
        return "pass"

    job_title = _normalize(job_data.get("title", ""))
    if not job_title:
        return "uncertain"

    # Exact substring match
    for role in target_roles:
        if _normalize(role) in job_title:
            return "pass"

    # Check if the job title is in a related family
    for role in target_roles:
        role_lower = _normalize(role)
        for family, related in RELATED_ROLE_FAMILIES.items():
            # If target role matches a family key or one of its synonyms
            if role_lower == family or role_lower in related:
                # Check if job title contains the family key or any synonym
                if _normalize(family) in job_title:
                    return "uncertain"
                for synonym in related:
                    if synonym in job_title:
                        return "uncertain"

    return "fail"


def seniority_filter(
    job_data: dict, preferences: dict, profile: dict,
) -> str:
    """Extract seniority from job title and compare to preferences."""
    seniority_levels: list[str] = _json_loads_safe(
        preferences.get("seniority_levels"), []
    )
    if not seniority_levels:
        return "pass"

    job_title = _normalize(job_data.get("title", ""))
    if not job_title:
        return "uncertain"

    preferred = {_normalize(s) for s in seniority_levels}

    # Detect seniority signals present in job title
    detected: set[str] = set()
    for level, keywords in SENIORITY_KEYWORDS.items():
        for kw in keywords:
            if _text_contains_keyword(job_title, kw):
                detected.add(level)

    if not detected:
        # No seniority signal found — ambiguous
        return "uncertain"

    # If any detected seniority matches preferences
    if detected & preferred:
        return "pass"

    # Detected but no overlap — clearly wrong level
    return "fail"


def location_filter(
    job_data: dict, preferences: dict, profile: dict,
) -> str:
    """Compare job locations against preferred locations / remote policy."""
    preferred_locations: list[str] = _json_loads_safe(
        preferences.get("locations"), []
    )
    remote_pref = _normalize(preferences.get("remote_policy", "any"))
    job_remote = _normalize(job_data.get("remote_policy", "unknown"))
    job_locations: list[str] = _json_loads_safe(
        job_data.get("locations"), []
    )

    # If user accepts anything, pass immediately
    if remote_pref == "any" and not preferred_locations:
        return "pass"

    # Remote policy checks
    if remote_pref == "remote":
        if job_remote == "remote":
            return "pass"
        if job_remote == "onsite":
            return "fail"
        # hybrid or unknown — uncertain

    if job_remote == "remote":
        # Job is remote — pass regardless of location list
        return "pass"

    # Geographic location overlap
    if preferred_locations and job_locations:
        pref_set = {_normalize(loc) for loc in preferred_locations}
        job_set = {_normalize(loc) for loc in job_locations}

        # Check for exact or substring overlap
        for pref_loc in pref_set:
            for job_loc in job_set:
                if pref_loc in job_loc or job_loc in pref_loc:
                    return "pass"

        # No location overlap
        if remote_pref in ("onsite", "hybrid") or remote_pref == "any":
            return "fail"

    # No location data available to compare
    if not job_locations and job_remote == "unknown":
        return "uncertain"

    if remote_pref == "remote" and job_remote in ("hybrid", "unknown"):
        return "uncertain"

    if preferred_locations and not job_locations:
        return "uncertain"

    return "uncertain"


def salary_filter(
    job_data: dict, preferences: dict, profile: dict,
) -> str:
    """Compare user min_salary against job salary_max."""
    min_salary = preferences.get("min_salary")
    if min_salary is None:
        return "pass"

    try:
        min_salary = int(min_salary)
    except (ValueError, TypeError):
        return "pass"

    salary_max = job_data.get("salary_max")
    if salary_max is None:
        return "uncertain"

    try:
        salary_max = int(salary_max)
    except (ValueError, TypeError):
        return "uncertain"

    # Compare currencies if available
    pref_currency = _normalize(preferences.get("salary_currency", ""))
    job_currency = _normalize(job_data.get("salary_currency", ""))
    if pref_currency and job_currency and pref_currency != job_currency:
        return "uncertain"

    if salary_max < min_salary:
        return "fail"

    return "pass"


def visa_filter(
    job_data: dict, preferences: dict, profile: dict,
) -> str:
    """Check visa sponsorship compatibility."""
    needs_visa = preferences.get("needs_visa_sponsorship")
    if not needs_visa:
        return "pass"

    visa_sponsorship = _normalize(job_data.get("visa_sponsorship", "unknown"))
    if visa_sponsorship == "no":
        return "fail"
    if visa_sponsorship == "unknown":
        return "uncertain"

    return "pass"


def excluded_keyword_filter(
    job_data: dict, preferences: dict, profile: dict,
) -> str:
    """Check job title, company, and description against excluded keywords."""
    excluded: list[str] = _json_loads_safe(
        preferences.get("excluded_keywords"), []
    )
    if not excluded:
        return "pass"

    # Build searchable text corpus
    searchable = " ".join(
        str(job_data.get(field, "") or "")
        for field in ("title", "company_name", "description_text")
    )

    for keyword in excluded:
        if _text_contains_keyword(searchable, keyword):
            logger.debug(
                "filter.excluded_keyword_match",
                keyword=keyword,
                job_title=job_data.get("title"),
            )
            return "fail"

    return "pass"


# ── Aggregate runner ───────────────────────────────────────────────────────

ALL_FILTERS: dict[str, Any] = {
    "role_family": role_family_filter,
    "seniority": seniority_filter,
    "location": location_filter,
    "salary": salary_filter,
    "visa": visa_filter,
    "excluded_keyword": excluded_keyword_filter,
}


def apply_hard_filters(
    job_data: dict, preferences: dict, profile: dict,
) -> dict:
    """
    Run every hard filter and return a results dict.

    Returns:
        {
            "results": {"role_family": "pass", "seniority": "uncertain", …},
            "overall": "passed" | "rejected",
            "fail_reasons": ["salary"],
        }
    """
    results: dict[str, str] = {}
    fail_reasons: list[str] = []

    for name, fn in ALL_FILTERS.items():
        try:
            outcome = fn(job_data, preferences, profile)
        except Exception:
            logger.exception("filter.error", filter_name=name)
            outcome = "uncertain"
        results[name] = outcome
        if outcome == "fail":
            fail_reasons.append(name)

    overall = "rejected" if fail_reasons else "passed"

    logger.debug(
        "filter.results",
        overall=overall,
        results=results,
        job_title=job_data.get("title"),
    )

    return {
        "results": results,
        "overall": overall,
        "fail_reasons": fail_reasons,
    }
