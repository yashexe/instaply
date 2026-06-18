"""Relevance check: do a board's live titles match the user's target roles?"""

from __future__ import annotations

from src.common.taxonomy import (
    ROLE_FAMILY_KEYWORDS,
    contains_keyword,
    infer_role_family,
)


def matching_titles(titles: list[str], target_roles: list[str]) -> list[str]:
    """Titles that match a target role directly or by role family.

    Family matching uses the keyword set of each target role's family
    (not family equality), since infer_role_family is first-match: a
    "Backend Engineer" title and a "Software Engineer" target land in
    different families even though they overlap.

    Returns every matching title (callers decide how many to keep as
    evidence and compare the count against the suggestion threshold).
    """
    if not target_roles:
        return []

    family_keywords: set[str] = set()
    for role in target_roles:
        family = infer_role_family(role)
        if family:
            family_keywords.update(ROLE_FAMILY_KEYWORDS[family])

    matched: list[str] = []
    for title in titles:
        if not title:
            continue
        if any(contains_keyword(title, role) for role in target_roles):
            matched.append(title)
        elif any(contains_keyword(title, kw) for kw in family_keywords):
            matched.append(title)
    return matched
