"""Company name normalization and ATS slug guessing. Pure functions."""

from __future__ import annotations

import re

# Trailing legal/corporate suffixes that never appear in board slugs.
_LEGAL_SUFFIXES = {
    "inc",
    "incorporated",
    "llc",
    "ltd",
    "limited",
    "plc",
    "gmbh",
    "corp",
    "corporation",
    "co",
    "company",
}

_MAX_SLUG_GUESSES = 4


def _name_words(name: str) -> list[str]:
    """Lowercased words with punctuation stripped and legal suffixes removed."""
    cleaned = re.sub(r"[^a-z0-9\s-]", " ", name.lower())
    words = [w for w in re.split(r"[\s-]+", cleaned) if w]
    while words and words[-1] in _LEGAL_SUFFIXES:
        words.pop()
    return words


def normalize_name_key(name: str) -> str:
    """Stable dedupe key for a company name.

    "Acme Corp, Inc." and "acme-corp" both map to "acmecorp" so the same
    company suggested by different providers collapses to one row.
    """
    return "".join(_name_words(name))


def guess_slugs(name: str) -> list[str]:
    """Plausible ATS board slugs for a company name, most likely first."""
    words = _name_words(name)
    if not words:
        return []

    guesses: list[str] = []

    def add(slug: str) -> None:
        if slug and slug not in guesses:
            guesses.append(slug)

    add("".join(words))
    add("-".join(words))
    add(words[0])
    add(words[0] + "hq")
    return guesses[:_MAX_SLUG_GUESSES]
