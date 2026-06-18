"""
Shared LLM rate-limit cooldown.

When a provider returns a rate-limit error (HTTP 429 / RESOURCE_EXHAUSTED),
callers trip a module-level cooldown so subsequent calls skip the LLM and
use their non-LLM fallbacks instead of hammering an exhausted quota.
"""

from __future__ import annotations

import re
import time

import structlog

logger = structlog.get_logger()

DEFAULT_COOLDOWN_SECONDS = 60.0
# Daily quotas don't reset for hours; the per-request retryDelay in the
# error message is misleading for these.
DAILY_QUOTA_COOLDOWN_SECONDS = 3600.0

_cooldown_until: float = 0.0


def is_cooling_down() -> bool:
    """Return True while the LLM is inside a rate-limit cooldown window."""
    return time.monotonic() < _cooldown_until


def seconds_remaining() -> float:
    """Return seconds left in the current cooldown window (0 if none)."""
    return max(0.0, _cooldown_until - time.monotonic())


def reset() -> None:
    """Clear any active cooldown (used by tests)."""
    global _cooldown_until
    _cooldown_until = 0.0


def _is_rate_limit_error(exc: Exception) -> bool:
    code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    if code == 429:
        return True
    message = str(exc)
    return (
        "429" in message
        or "RESOURCE_EXHAUSTED" in message
        or "rate limit" in message.lower()
        or "rate_limit" in message.lower()
    )


def _cooldown_seconds_for(exc: Exception) -> float:
    message = str(exc)
    if "PerDay" in message or "per day" in message.lower():
        return DAILY_QUOTA_COOLDOWN_SECONDS
    match = re.search(r"retry in ([0-9.]+)\s*s", message, re.IGNORECASE)
    if match:
        return max(float(match.group(1)), DEFAULT_COOLDOWN_SECONDS)
    return DEFAULT_COOLDOWN_SECONDS


def note_error(exc: Exception) -> bool:
    """Trip the cooldown if exc is a rate-limit error.

    Returns True if the error was a rate limit (cooldown tripped),
    False otherwise so callers can log it as an unexpected failure.
    """
    global _cooldown_until
    if not _is_rate_limit_error(exc):
        return False
    seconds = _cooldown_seconds_for(exc)
    _cooldown_until = max(_cooldown_until, time.monotonic() + seconds)
    logger.warning(
        "llm.rate_limited",
        cooldown_seconds=round(seconds, 1),
        error=str(exc)[:200],
    )
    return True
