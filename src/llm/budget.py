"""
Persistent daily LLM call budget.

The cooldown module reacts to rate-limit errors after they happen; this
ledger prevents them by capping calls per UTC day, with a separate slice
for the match judge so it can never starve extraction or alert
explanations. Counts live in the llm_usage table and survive restarts.

Callers ask spend() before each LLM call; a False answer means "use your
non-LLM fallback". If no database connection is initialized (unit tests,
ad-hoc scripts) the budget fails open.
"""

from __future__ import annotations

from datetime import datetime, timezone

import aiosqlite
import structlog

from src.config import settings

logger = structlog.get_logger()


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


async def _get_db() -> aiosqlite.Connection | None:
    try:
        from src.db.connection import get_db

        return await get_db()
    except RuntimeError:
        return None


def _category_limit(category: str) -> int | None:
    if category == "judge":
        return settings.llm_judge_daily_budget
    if category == "discovery":
        return settings.llm_discovery_daily_budget
    return None


async def spend(category: str, n: int = 1) -> bool:
    """Reserve n LLM calls against today's budget.

    Returns False (and records nothing) when the daily total or the
    category's slice would be exceeded — the caller must fall back.
    """
    db = await _get_db()
    if db is None:
        return True

    day = _today()
    limit = _category_limit(category)
    # Budget checks live inside the insert itself: a guarded statement is
    # atomic, so concurrent spend() calls can't both pass a stale total.
    cursor = await db.execute(
        """
        INSERT INTO llm_usage (day, category, calls)
        SELECT :day, :category, :n
        WHERE (SELECT COALESCE(SUM(calls), 0) FROM llm_usage WHERE day = :day)
              + :n <= :daily_budget
          AND (:limit IS NULL
               OR (SELECT COALESCE(SUM(calls), 0) FROM llm_usage
                   WHERE day = :day AND category = :category) + :n <= :limit)
        ON CONFLICT(day, category) DO UPDATE SET calls = calls + excluded.calls
        """,
        {
            "day": day,
            "category": category,
            "n": n,
            "daily_budget": settings.llm_daily_budget,
            "limit": limit,
        },
    )
    await db.commit()
    if cursor.rowcount:
        return True

    cursor = await db.execute(
        "SELECT COALESCE(SUM(calls), 0) FROM llm_usage WHERE day = ?", (day,)
    )
    total = (await cursor.fetchone())[0]
    if total + n <= settings.llm_daily_budget and limit is not None:
        cursor = await db.execute(
            "SELECT COALESCE(SUM(calls), 0) FROM llm_usage"
            " WHERE day = ? AND category = ?",
            (day, category),
        )
        used = (await cursor.fetchone())[0]
        logger.info(
            "llm.category_budget_exhausted",
            category=category,
            used=used,
            limit=limit,
        )
    else:
        logger.warning(
            "llm.daily_budget_exhausted",
            category=category,
            used=total,
            budget=settings.llm_daily_budget,
        )
    return False


async def usage_today() -> dict:
    """Per-category and total LLM calls spent today."""
    db = await _get_db()
    if db is None:
        return {"total": 0, "budget": settings.llm_daily_budget, "categories": {}}
    cursor = await db.execute(
        "SELECT category, calls FROM llm_usage WHERE day = ?", (_today(),)
    )
    categories = {row[0]: row[1] for row in await cursor.fetchall()}
    return {
        "total": sum(categories.values()),
        "budget": settings.llm_daily_budget,
        "categories": categories,
    }
