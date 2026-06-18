"""
Proactive client-side request spacing for LLM calls.

The cooldown module (src/llm/cooldown.py) reacts to rate-limit errors *after*
they happen; this module prevents them by enforcing a minimum interval between
consecutive LLM API calls. Tight loops (backlog rescore, match judging) would
otherwise fire requests back-to-back and blow past the provider's per-minute
limit (e.g. Gemini free tier ~10 RPM) in a fraction of a second.

A single module-level lock + timestamp serialises spacing across all callers,
so concurrent and sequential call sites share one rate budget.
"""

from __future__ import annotations

import asyncio
import time

import structlog

from src.config import settings

logger = structlog.get_logger()

_lock = asyncio.Lock()
_next_allowed_at: float = 0.0


async def acquire() -> None:
    """Block until the configured min interval has elapsed since the last call.

    No-op when llm_min_request_interval_seconds is 0. Reserves the next slot
    before sleeping so concurrent callers queue rather than all firing at once.
    """
    interval = settings.llm_min_request_interval_seconds
    if interval <= 0:
        return

    global _next_allowed_at
    async with _lock:
        now = time.monotonic()
        wait = _next_allowed_at - now
        # Schedule this call's slot; the next caller waits one interval beyond.
        start_at = max(now, _next_allowed_at)
        _next_allowed_at = start_at + interval

    if wait > 0:
        logger.debug("llm.ratelimit.wait", seconds=round(wait, 2))
        await asyncio.sleep(wait)


def reset() -> None:
    """Clear the spacing window (used by tests)."""
    global _next_allowed_at
    _next_allowed_at = 0.0
