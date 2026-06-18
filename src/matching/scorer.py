"""
Weighted scoring engine — DETERMINISTIC.

Each dimension reports earned points, possible points, and whether it had
real data to judge (`known`). The composite score is computed over known
dimensions only and rescaled to 0–100, so missing information neither
rewards nor punishes a posting. Data coverage is reported separately as
`confidence` (0–100): the share of total dimension weight that was known,
reduced when hard filters were uncertain.

A non-compensatory gate caps the score when most required skills are
missing — location and preference points cannot buy back a fundamental
skills mismatch.
"""

from __future__ import annotations

import json
import re
from typing import Any, NamedTuple

import structlog

from src.common.taxonomy import canonical_skill

logger = structlog.get_logger()

# Dimension weights (total 100; freshness is deliberately not a fit signal).
# Semantic similarity is the primary relevance signal; keyword skill
# matching is kept at lower weight and still drives the gate.
# Mirrored in SCORE_DIMENSIONS in src/web/static/app.js — update both.
WEIGHTS = {
    "semantic_fit": 30,
    "role_title_fit": 15,
    "required_skills_fit": 15,
    "experience_fit": 10,
    "preferences_fit": 15,
    "domain_company_fit": 5,
    "preferred_skills_bonus": 10,
}

# Cosine similarity mapping to the semantic dimension: at or below the
# floor earns 0, at or above the ceiling earns full weight. Calibrated
# against the live corpus with all-MiniLM-L6-v2: clearly unrelated roles
# (sales, marketing, logistics) cluster below ≈0.25, engineering-adjacent
# roles span ≈0.3–0.45, and strongly aligned roles sit ≈0.45+ up to a
# p99 of ≈0.56. The floor marks the unrelated boundary, the ceiling p99.
SEMANTIC_SIM_FLOOR = 0.25
SEMANTIC_SIM_CEIL = 0.55

# Required-skills coverage below this ratio caps the total score at GATE_CAP.
GATE_RATIO = 0.3
GATE_CAP = 49


class DimensionScore(NamedTuple):
    points: float
    max_points: float
    known: bool


UNKNOWN = DimensionScore(0, 0, False)


# ── Helpers ────────────────────────────────────────────────────────────────

def _json_loads_safe(value: Any, default: Any = None) -> Any:
    if value is None:
        return default
    if isinstance(value, (list, dict)):
        return value
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return default


def _normalize_skill(skill: str) -> str:
    """Normalize a skill string for comparison."""
    return re.sub(r"[.\-/]", "", str(skill).strip().lower())


def _extract_skill_names(raw_skills: list[Any]) -> list[str]:
    """Extract skill names from strings or structured skill objects."""
    names: list[str] = []
    for skill in raw_skills or []:
        if isinstance(skill, dict):
            name = skill.get("name")
            if name:
                names.append(str(name))
        elif skill:
            names.append(str(skill))
    return names


def _extract_role_titles(raw_roles: list[Any]) -> list[str]:
    """Extract role titles from strings or structured role objects."""
    titles: list[str] = []
    for role in raw_roles or []:
        if isinstance(role, dict):
            title = role.get("title")
            if title:
                titles.append(str(title))
        elif role:
            titles.append(str(role))
    return titles


def _skills_match(skill_a: str, skill_b: str) -> bool:
    """
    Check if two skill strings match.

    Exact normalized match first; then taxonomy canonicalization so synonyms
    and variants resolve to the same skill ('node' ↔ 'Node.js',
    'postgres' ↔ 'PostgreSQL'); then containment ('react' matches 'react.js').
    """
    a = _normalize_skill(skill_a)
    b = _normalize_skill(skill_b)
    if not a or not b:
        return False
    if a == b:
        return True
    # Taxonomy is authoritative when it recognises both skills: they match iff
    # they share a canonical name ('node' ↔ 'Node.js'), and crucially do NOT
    # match otherwise ('java' is not 'javascript') — skip the fuzzy fallback.
    canon_a = canonical_skill(skill_a)
    canon_b = canonical_skill(skill_b)
    if canon_a and canon_b:
        return canon_a[0] == canon_b[0]
    # Containment fallback for skills the taxonomy doesn't know: only if the
    # shorter is ≥ 2 chars (avoid false matches).
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    if len(shorter) >= 2 and shorter in longer:
        return True
    return False


def _count_skill_matches(target_skills: list[str], candidate_skills: list[str]) -> int:
    """Count how many target skills are covered by the candidate's skill list."""
    matched = 0
    for target in target_skills:
        for candidate in candidate_skills:
            if _skills_match(target, candidate):
                matched += 1
                break
    return matched


def _profile_data(profile: dict) -> dict:
    data = _json_loads_safe(profile.get("structured_profile"), {})
    return data if isinstance(data, dict) else {}


# ── Scoring dimensions ─────────────────────────────────────────────────────

def _score_semantic_fit(semantic_similarity: float | None) -> DimensionScore:
    """Semantic similarity fit — weight 30. Unknown when no embeddings exist."""
    max_points = WEIGHTS["semantic_fit"]
    if semantic_similarity is None:
        return UNKNOWN
    ratio = (semantic_similarity - SEMANTIC_SIM_FLOOR) / (
        SEMANTIC_SIM_CEIL - SEMANTIC_SIM_FLOOR
    )
    ratio = max(0.0, min(1.0, ratio))
    return DimensionScore(ratio * max_points, max_points, True)


def _score_role_title_fit(
    job_data: dict,
    preferences: dict,
    profile: dict,
    extracted_reqs: dict | None,
) -> DimensionScore:
    """Role/title fit — weight 20. Unknown when the candidate lists no roles."""
    max_points = WEIGHTS["role_title_fit"]
    job_title = (job_data.get("title") or "").lower()

    target_roles: list[str] = _json_loads_safe(preferences.get("target_roles"), [])
    profile_roles = _extract_role_titles(_profile_data(profile).get("roles", []))
    all_candidate_roles = [
        str(role).lower() for role in target_roles + profile_roles if role
    ]
    if not all_candidate_roles or not job_title:
        return UNKNOWN

    # Exact substring match
    for role in all_candidate_roles:
        if role in job_title or job_title in role:
            return DimensionScore(max_points, max_points, True)

    # Extracted role family match
    if extracted_reqs:
        ext_family = (extracted_reqs.get("role_family") or "").lower()
        if ext_family:
            for role in all_candidate_roles:
                if role in ext_family or ext_family in role:
                    return DimensionScore(0.75 * max_points, max_points, True)

    # Word overlap
    job_words = set(re.findall(r"\w+", job_title))
    for role in all_candidate_roles:
        role_words = set(re.findall(r"\w+", role))
        overlap = job_words & role_words
        if overlap and len(overlap) >= len(role_words) * 0.5:
            return DimensionScore(0.5 * max_points, max_points, True)

    return DimensionScore(0.15 * max_points, max_points, True)


def _score_required_skills_fit(
    profile: dict,
    extracted_reqs: dict | None,
) -> DimensionScore:
    """Required skills fit — weight 25. Unknown when either side lists nothing."""
    max_points = WEIGHTS["required_skills_fit"]

    required: list[str] = []
    if extracted_reqs:
        required = extracted_reqs.get("required_skills") or []
    candidate_skills = _extract_skill_names(_profile_data(profile).get("skills", []))

    if not required or not candidate_skills:
        return UNKNOWN

    matched = _count_skill_matches(required, candidate_skills)
    ratio = matched / len(required)
    return DimensionScore(round(ratio * max_points), max_points, True)


def _score_experience_fit(
    profile: dict,
    extracted_reqs: dict | None,
) -> DimensionScore:
    """Experience fit — weight 15. Unknown when the posting states no requirement."""
    max_points = WEIGHTS["experience_fit"]

    years_min = (extracted_reqs or {}).get("years_experience_min")
    if years_min is None:
        return UNKNOWN
    try:
        years_min = int(years_min)
    except (ValueError, TypeError):
        return UNKNOWN

    candidate_years = _profile_data(profile).get("years_of_experience")
    if candidate_years is None:
        return UNKNOWN
    try:
        candidate_years = int(candidate_years)
    except (ValueError, TypeError):
        return UNKNOWN

    if candidate_years >= years_min:
        ratio = 1.0
    elif candidate_years >= years_min - 1:
        ratio = 0.8
    elif candidate_years >= years_min - 2:
        ratio = 0.55
    elif candidate_years >= years_min - 3:
        ratio = 0.33
    else:
        ratio = 0.13
    return DimensionScore(ratio * max_points, max_points, True)


def _score_preferences_fit(
    job_data: dict,
    preferences: dict,
) -> DimensionScore:
    """Preferences fit — weight 15: location 5, remote 4, salary 4, visa 2.

    A sub-dimension the user has no constraint on counts as satisfied; a
    constraint the job gives no data for is excluded from the denominator.
    """
    earned = 0.0
    possible = 0.0

    # Location sub (5 pts)
    preferred_locations: list[str] = _json_loads_safe(preferences.get("locations"), [])
    job_locations: list[str] = _json_loads_safe(job_data.get("locations"), [])
    if not preferred_locations:
        earned += 5
        possible += 5
    elif job_locations:
        pref_set = {loc.strip().lower() for loc in preferred_locations}
        job_set = {loc.strip().lower() for loc in job_locations}
        matched = any(p in j or j in p for p in pref_set for j in job_set)
        earned += 5 if matched else 0
        possible += 5
    # else: constraint exists but job location unknown — excluded

    # Remote sub (4 pts)
    remote_pref = (preferences.get("remote_policy") or "any").lower()
    job_remote = (job_data.get("remote_policy") or "unknown").lower()
    if remote_pref == "any":
        earned += 4
        possible += 4
    elif job_remote != "unknown":
        if remote_pref == job_remote:
            earned += 4
        elif remote_pref == "remote" and job_remote == "hybrid":
            earned += 1
        elif remote_pref == "hybrid" and job_remote == "remote":
            earned += 3
        possible += 4
    # else: constraint exists but job remote policy unknown — excluded

    # Salary sub (4 pts)
    min_salary = preferences.get("min_salary")
    salary_max_job = job_data.get("salary_max")
    if min_salary is None:
        earned += 4
        possible += 4
    elif salary_max_job is not None:
        try:
            if int(salary_max_job) >= int(min_salary):
                earned += 4
            elif int(salary_max_job) >= int(min_salary) * 0.9:
                earned += 2
            possible += 4
        except (ValueError, TypeError):
            pass  # unparseable salary — excluded
    # else: constraint exists but job salary unknown — excluded

    # Visa sub (2 pts)
    needs_visa = preferences.get("needs_visa_sponsorship")
    if not needs_visa:
        earned += 2
        possible += 2
    else:
        visa = (job_data.get("visa_sponsorship") or "unknown").lower()
        if visa in ("yes", "no"):
            earned += 2 if visa == "yes" else 0
            possible += 2
        # else: constraint exists but sponsorship unknown — excluded

    if possible == 0:
        return UNKNOWN
    # Rescale to the dimension weight so partial coverage is comparable
    max_points = WEIGHTS["preferences_fit"]
    return DimensionScore(earned / possible * max_points, max_points, True)


def _score_domain_company_fit(
    job_data: dict,
    profile: dict,
    extracted_reqs: dict | None,
) -> DimensionScore:
    """Domain/company fit — weight 10. Unknown when the profile lists no domains."""
    max_points = WEIGHTS["domain_company_fit"]

    profile_domains: list[str] = _profile_data(profile).get("domains", [])
    if not profile_domains:
        return UNKNOWN

    domain_signals: list[str] = []
    if extracted_reqs:
        domain_signals = extracted_reqs.get("domain_signals") or []

    job_text = " ".join(
        str(job_data.get(f, "") or "")
        for f in ("description_text", "department", "company_name")
    ).lower()

    matched = 0
    for domain in profile_domains:
        d = domain.strip().lower()
        if d in job_text:
            matched += 1
        elif any(_skills_match(d, sig) for sig in domain_signals):
            matched += 1

    ratio = min(matched / len(profile_domains), 1.0)
    return DimensionScore(round(ratio * max_points), max_points, True)


def _score_preferred_skills_bonus(
    profile: dict,
    extracted_reqs: dict | None,
) -> DimensionScore:
    """Preferred-skills bonus — weight 10. Unknown when none are listed."""
    max_points = WEIGHTS["preferred_skills_bonus"]

    nice_to_have: list[str] = []
    if extracted_reqs:
        nice_to_have = extracted_reqs.get("preferred_skills") or []
    candidate_skills = _extract_skill_names(_profile_data(profile).get("skills", []))

    if not nice_to_have or not candidate_skills:
        return UNKNOWN

    matched = _count_skill_matches(nice_to_have, candidate_skills)
    ratio = min(matched / len(nice_to_have), 1.0)
    return DimensionScore(round(ratio * max_points), max_points, True)


# ── Main scorer ────────────────────────────────────────────────────────────

def score_job(
    job_data: dict,
    preferences: dict,
    profile: dict,
    extracted_reqs: dict | None,
    filter_results: dict,
    semantic_similarity: float | None = None,
) -> tuple[int, dict]:
    """
    Compute a composite score and data confidence for a job–profile pair.

    Returns:
        (total_score: int 0–100, breakdown)

    The breakdown contains earned points for each dimension that had real
    data (unknown dimensions are omitted), a `confidence` percentage, and
    a `required_skills_gate` entry when the cap was applied.
    """
    dimensions = {
        "semantic_fit": _score_semantic_fit(semantic_similarity),
        "role_title_fit": _score_role_title_fit(
            job_data, preferences, profile, extracted_reqs,
        ),
        "required_skills_fit": _score_required_skills_fit(profile, extracted_reqs),
        "experience_fit": _score_experience_fit(profile, extracted_reqs),
        "preferences_fit": _score_preferences_fit(job_data, preferences),
        "domain_company_fit": _score_domain_company_fit(
            job_data, profile, extracted_reqs,
        ),
        "preferred_skills_bonus": _score_preferred_skills_bonus(
            profile, extracted_reqs,
        ),
    }

    earned = sum(d.points for d in dimensions.values() if d.known)
    possible = sum(d.max_points for d in dimensions.values() if d.known)
    total = round(100 * earned / possible) if possible else 0

    breakdown: dict[str, int] = {
        name: round(d.points) for name, d in dimensions.items() if d.known
    }

    # Confidence: how much dimension weight had real data, discounted for
    # hard filters that could not reach a verdict.
    filter_outcomes = filter_results.get("results", {})
    uncertain_count = sum(1 for v in filter_outcomes.values() if v == "uncertain")
    total_weight = sum(WEIGHTS.values())
    confidence = round(100 * possible / total_weight) - 5 * uncertain_count
    confidence = max(0, min(100, confidence))
    breakdown["confidence"] = confidence

    # Non-compensatory gate: missing most required skills caps the total.
    skills = dimensions["required_skills_fit"]
    if skills.known and skills.points / skills.max_points < GATE_RATIO:
        if total > GATE_CAP:
            breakdown["required_skills_gate"] = GATE_CAP - total
            total = GATE_CAP

    total = max(0, min(100, total))

    logger.debug(
        "scorer.result",
        total=total,
        confidence=confidence,
        breakdown=breakdown,
        job_title=job_data.get("title"),
    )

    return total, breakdown
