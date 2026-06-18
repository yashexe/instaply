"""
Resume parser — uses the configured LLM to extract structured data from resume text.
"""

import re

import structlog

from src.common.taxonomy import (
    ROLE_KEYWORDS,
    contains_keyword,
    extract_domains,
    extract_skill_hits,
)
from src.config import settings
from src.profile.models import RoleEntry, Skill, StructuredProfile

logger = structlog.get_logger()

RESUME_PARSE_SYSTEM_PROMPT = """\
You are a resume parser. Extract structured information from the provided resume text.

Return a JSON object with these fields:
- "skills": array of objects with "name" (string), "category" (string or null, e.g. "Programming Language", "Framework", "Cloud", "Database", "Soft Skill"), and "confidence" (float 0.0-1.0, how confident you are this is a real skill)
- "roles": array of objects with "title" (string), "company" (string or null), "start_date" (string or null, e.g. "2020-01"), "end_date" (string or null, e.g. "2023-06" or "Present"), and "summary" (string or null, brief description)
- "education": array of objects with "institution" (string), "degree" (string or null), "field" (string or null), and "graduation_year" (integer or null)
- "domains": array of strings — industry domains the candidate has experience in (e.g. "FinTech", "Healthcare", "E-commerce")
- "years_of_experience": float or null — estimated total years of professional experience
- "seniority_level": string or null — one of "intern", "junior", "mid", "senior", "staff", "principal", "lead", "manager", "director", "vp", "c-level"
- "summary": string or null — a 2-3 sentence professional summary

Be thorough but accurate. Only include skills explicitly mentioned or strongly implied.
If information is not available, use null or empty arrays.
"""

MONTHS: dict[str, int] = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}

MONTH_ALT = "|".join(sorted(MONTHS, key=len, reverse=True))
DATE_RANGE_PATTERN = re.compile(
    rf"\b(?P<start_month>{MONTH_ALT})\s+(?P<start_year>\d{{4}})"
    rf"\s*(?:-|\u2013|\u2014|to)\s*"
    rf"(?:(?P<present>present|current)|(?P<end_month>{MONTH_ALT})\s+(?P<end_year>\d{{4}}))",
    re.IGNORECASE,
)


def _parse_resume_locally(resume_text: str) -> StructuredProfile:
    """Best-effort local parser for development without an LLM key."""
    lower = resume_text.lower()
    skills = [
        Skill(name=name, category=category, confidence=0.75)
        for name, category in extract_skill_hits(resume_text)
    ]

    roles = _extract_experience_roles(resume_text)
    for role in ROLE_KEYWORDS:
        if contains_keyword(lower, role) and not _has_related_role(roles, role):
            roles.append(RoleEntry(title=role))

    seniority = _infer_seniority(lower, roles)
    domains = extract_domains(resume_text)

    explicit_years = None
    year_match = re.search(r"(\d+(?:\.\d+)?)\+?\s+years?", lower)
    if year_match:
        explicit_years = float(year_match.group(1))

    inferred_years = _estimate_years_from_date_ranges(resume_text)
    years_of_experience = _choose_years_of_experience(explicit_years, inferred_years)

    return StructuredProfile(
        skills=skills,
        roles=roles,
        domains=domains,
        years_of_experience=years_of_experience,
        seniority_level=seniority,
        summary=resume_text[:2000],
    )


def _extract_experience_roles(resume_text: str) -> list[RoleEntry]:
    """Extract company/title/date role rows from common resume formatting."""
    lines = [line.strip() for line in resume_text.splitlines() if line.strip()]
    roles: list[RoleEntry] = []

    for index, line in enumerate(lines[:-1]):
        match = DATE_RANGE_PATTERN.search(line)
        if not match:
            continue

        next_line = lines[index + 1]
        if next_line.startswith(("•", "-", "*")):
            continue
        if not _looks_like_role_title(next_line):
            continue

        company = line[: match.start()].strip(" -|")
        roles.append(
            RoleEntry(
                title=next_line,
                company=company or None,
                start_date=_format_year_month(
                    match.group("start_year"),
                    match.group("start_month"),
                ),
                end_date="Present"
                if match.group("present")
                else _format_year_month(match.group("end_year"), match.group("end_month")),
            )
        )

    return roles


def _looks_like_role_title(value: str) -> bool:
    lower = value.lower()
    role_words = (
        "engineer",
        "developer",
        "manager",
        "designer",
        "analyst",
        "scientist",
        "intern",
        "architect",
    )
    return any(word in lower for word in role_words)


def _has_related_role(roles: list[RoleEntry], candidate: str) -> bool:
    candidate_lower = candidate.lower()
    for role in roles:
        title = role.title.lower()
        if candidate_lower == title:
            return True
        if candidate_lower in title or title in candidate_lower:
            return True
    return False


def _format_year_month(year: str | None, month: str | None) -> str | None:
    if not year or not month:
        return None
    month_number = MONTHS.get(month.lower())
    if not month_number:
        return None
    return f"{int(year):04d}-{month_number:02d}"


def _estimate_years_from_date_ranges(resume_text: str) -> float | None:
    """Estimate experience duration by unioning months from resume date ranges."""
    from datetime import date

    months: set[tuple[int, int]] = set()
    today = date.today()

    for match in DATE_RANGE_PATTERN.finditer(resume_text):
        start_month = MONTHS.get(match.group("start_month").lower())
        start_year = int(match.group("start_year"))
        if match.group("present"):
            end_year = today.year
            end_month = today.month
        else:
            end_month_raw = match.group("end_month")
            end_year_raw = match.group("end_year")
            if not end_month_raw or not end_year_raw:
                continue
            end_month = MONTHS.get(end_month_raw.lower())
            end_year = int(end_year_raw)

        if not start_month or not end_month:
            continue

        cursor_year, cursor_month = start_year, start_month
        while (cursor_year, cursor_month) <= (end_year, end_month):
            months.add((cursor_year, cursor_month))
            cursor_month += 1
            if cursor_month > 12:
                cursor_year += 1
                cursor_month = 1

    if not months:
        return None
    return round(len(months) / 12, 1)


def _choose_years_of_experience(
    explicit_years: float | None,
    inferred_years: float | None,
) -> float | None:
    if explicit_years is None:
        return inferred_years
    if inferred_years is None:
        return explicit_years
    return max(explicit_years, inferred_years)


def _infer_seniority(text: str, roles: list[RoleEntry]) -> str | None:
    current_roles = [
        role for role in roles if (role.end_date or "").lower() == "present"
    ]
    current_titles = " ".join(role.title.lower() for role in current_roles)

    if any(word in current_titles for word in ("staff", "principal")):
        return "staff" if "staff" in current_titles else "principal"
    if any(word in current_titles for word in ("senior", "sr.")):
        return "senior"
    if current_roles and "intern" not in current_titles:
        return "mid"

    if any(word in text for word in ("staff", "principal")):
        return "staff" if "staff" in text else "principal"
    if any(word in text for word in ("senior", "sr.")):
        return "senior"
    if current_titles and "intern" in current_titles:
        return "intern"
    if roles:
        return "mid"
    return None


async def parse_resume(resume_text: str) -> StructuredProfile:
    """Parse resume text into a StructuredProfile using the configured LLM.

    If no LLM is configured, returns a minimal profile with the raw text as summary.
    Handles LLM errors gracefully by falling back to the minimal profile.

    Args:
        resume_text: Raw resume text to parse.

    Returns:
        A StructuredProfile with extracted data.
    """
    if not settings.llm_configured:
        logger.warning("parser.llm_not_configured", fallback="minimal_profile")
        return _parse_resume_locally(resume_text)

    from src.llm import budget, cooldown

    if cooldown.is_cooling_down():
        logger.warning(
            "parser.llm_cooldown",
            fallback="minimal_profile",
            seconds_remaining=round(cooldown.seconds_remaining(), 1),
        )
        return _parse_resume_locally(resume_text)

    if not await budget.spend("profile"):
        return _parse_resume_locally(resume_text)

    try:
        from src.llm.factory import get_llm_provider

        llm = get_llm_provider()

        logger.info("parser.parsing_resume", text_len=len(resume_text))

        result = await llm.structured_output(
            system_prompt=RESUME_PARSE_SYSTEM_PROMPT,
            user_prompt=resume_text,
        )

        profile = StructuredProfile.model_validate(result)

        logger.info(
            "parser.parse_complete",
            skills_count=len(profile.skills),
            roles_count=len(profile.roles),
            education_count=len(profile.education),
            domains_count=len(profile.domains),
            seniority=profile.seniority_level,
        )

        return profile

    except Exception as exc:
        if not cooldown.note_error(exc):
            logger.error(
                "parser.parse_failed",
                error=str(exc),
                exc_info=True,
            )
        # Fall back to a minimal profile with the raw text
        return _parse_resume_locally(resume_text)
