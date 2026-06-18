"""LLM budget ledger and match judge tests — provider is always faked."""

import asyncio
import json

import pytest

from src.config import settings
from src.llm import budget, cooldown
from src.matching.judge import judge_pending_matches
from src.matching.service import rescore_backlog
from tests.test_rescore import insert_jobs, setup_profile


@pytest.fixture(autouse=True)
def reset_llm_state(monkeypatch):
    """Wire the budget ledger to the test db and clear cooldown state."""
    cooldown.reset()
    monkeypatch.setattr(type(settings), "llm_configured", True)
    yield
    cooldown.reset()


@pytest.fixture
def budget_db(db, monkeypatch):
    """Point the global connection (used by the budget ledger) at the test db."""
    monkeypatch.setattr("src.db.connection._db", db)
    return db


class FakeProvider:
    def __init__(self, fit_score=90, fail_times=0, cover_letter=None):
        self.fit_score = fit_score
        self.fail_times = fail_times
        self.cover_letter = cover_letter
        self.calls = 0
        self.prompts = []

    async def structured_output(self, system_prompt, user_prompt, schema=None):
        self.calls += 1
        self.prompts.append(user_prompt)
        if self.fail_times > 0:
            self.fail_times -= 1
            raise RuntimeError("provider exploded")
        result = {
            "fit_score": self.fit_score,
            "verdict": "apply_now",
            "summary": "Great fit, but salary is unstated.",
            "matching_reasons": ["Python depth matches the core stack"],
            "missing_requirements": ["No Kubernetes experience"],
            "uncertainties": [],
        }
        if self.cover_letter is not None:
            result["cover_letter"] = self.cover_letter
        return result


def install_provider(monkeypatch, provider):
    monkeypatch.setattr("src.llm.factory.get_llm_provider", lambda: provider)


async def seed_matches(db, count=2) -> None:
    """Profile + jobs scored into digest/alert decisions."""
    await setup_profile(db)
    await insert_jobs(db, count)
    await rescore_backlog(db)


class TestBudgetLedger:
    async def test_spend_within_budget(self, budget_db):
        assert await budget.spend("extract") is True
        usage = await budget.usage_today()
        assert usage["total"] == 1
        assert usage["categories"]["extract"] == 1

    async def test_daily_budget_denies_when_exhausted(self, budget_db, monkeypatch):
        monkeypatch.setattr(settings, "llm_daily_budget", 2)
        assert await budget.spend("extract")
        assert await budget.spend("explain")
        assert not await budget.spend("extract")

    async def test_judge_slice_protects_other_categories(self, budget_db, monkeypatch):
        monkeypatch.setattr(settings, "llm_judge_daily_budget", 1)
        assert await budget.spend("judge")
        assert not await budget.spend("judge")
        # Other categories still have room
        assert await budget.spend("extract")

    async def test_fails_open_without_connection(self, monkeypatch):
        monkeypatch.setattr("src.db.connection._db", None)
        assert await budget.spend("extract") is True

    async def test_concurrent_spends_never_exceed_budget(self, budget_db, monkeypatch):
        monkeypatch.setattr(settings, "llm_daily_budget", 5)
        results = await asyncio.gather(*[budget.spend("extract") for _ in range(10)])
        assert sum(results) == 5
        usage = await budget.usage_today()
        assert usage["total"] == 5

    async def test_concurrent_spends_respect_judge_slice(self, budget_db, monkeypatch):
        monkeypatch.setattr(settings, "llm_judge_daily_budget", 3)
        results = await asyncio.gather(*[budget.spend("judge") for _ in range(8)])
        assert sum(results) == 3
        usage = await budget.usage_today()
        assert usage["categories"]["judge"] == 3


class TestJudge:
    async def test_judges_blends_and_replaces_explanations(self, budget_db, monkeypatch):
        await seed_matches(budget_db)
        provider = FakeProvider(fit_score=100)
        install_provider(monkeypatch, provider)

        result = await judge_pending_matches(budget_db, alert_channel="in_app")

        assert result["judged"] == result["pending"] > 0
        assert result["stopped_reason"] is None
        cursor = await budget_db.execute(
            "SELECT score, summary, trace FROM match_results WHERE decision IN ('alert','digest')"
        )
        for row in await cursor.fetchall():
            trace = json.loads(row["trace"])
            judged = trace["llm_judge"]
            assert judged["fit_score"] == 100
            expected = round(0.6 * 100 + 0.4 * judged["deterministic_score"])
            assert row["score"] == expected
            assert row["summary"] == "Great fit, but salary is unstated."

    async def test_promotion_creates_alert(self, budget_db, monkeypatch):
        await seed_matches(budget_db, count=1)
        # Force the seeded match into digest so a high judgment promotes it
        await budget_db.execute(
            "UPDATE match_results SET decision = 'digest', score = 70"
        )
        await budget_db.commit()
        install_provider(monkeypatch, FakeProvider(fit_score=100))

        result = await judge_pending_matches(budget_db, alert_channel="in_app")

        assert result["promoted"] == 1
        cursor = await budget_db.execute("SELECT channel FROM alerts")
        rows = await cursor.fetchall()
        assert [r["channel"] for r in rows].count("in_app") >= 1

    async def test_budget_stops_run_and_leaves_rest_pending(self, budget_db, monkeypatch):
        await seed_matches(budget_db, count=3)
        monkeypatch.setattr(settings, "llm_judge_daily_budget", 1)
        install_provider(monkeypatch, FakeProvider())

        result = await judge_pending_matches(budget_db)

        assert result["judged"] == 1
        assert result["stopped_reason"] == "budget"
        # Unjudged matches remain pending for the next run
        next_run = await judge_pending_matches(budget_db)
        assert next_run["stopped_reason"] == "budget"
        assert next_run["pending"] > 0

    async def test_rate_limit_trips_cooldown_and_stops(self, budget_db, monkeypatch):
        await seed_matches(budget_db, count=2)

        class RateLimited(FakeProvider):
            async def structured_output(self, *a, **k):
                self.calls += 1
                raise RuntimeError("429 rate limit exceeded, retry in 30s")

        provider = RateLimited()
        install_provider(monkeypatch, provider)

        result = await judge_pending_matches(budget_db)

        assert result["stopped_reason"] == "cooldown"
        assert provider.calls == 1  # stopped after the first 429
        assert cooldown.is_cooling_down()

    async def test_attempt_cap_gives_up_permanently(self, budget_db, monkeypatch):
        await seed_matches(budget_db, count=1)
        provider = FakeProvider(fail_times=99)
        install_provider(monkeypatch, provider)

        first = await judge_pending_matches(budget_db)
        second = await judge_pending_matches(budget_db)
        third = await judge_pending_matches(budget_db)

        assert first["failed"] == first["pending"]
        assert second["failed"] == second["pending"]
        assert third["pending"] == 0  # attempts exhausted, never retried again

    async def test_cover_letter_stored_when_provided(self, budget_db, monkeypatch):
        await seed_matches(budget_db, count=1)
        letter = "Dear team. I built an ETL platform. Yash"
        install_provider(monkeypatch, FakeProvider(fit_score=95, cover_letter=letter))

        await judge_pending_matches(budget_db, alert_channel="in_app")

        cursor = await budget_db.execute("SELECT cover_letter FROM match_results")
        row = await cursor.fetchone()
        assert row["cover_letter"] == letter

    async def test_mangled_cover_letter_does_not_break_judgment(self, budget_db, monkeypatch):
        await seed_matches(budget_db, count=1)
        install_provider(monkeypatch, FakeProvider(fit_score=95, cover_letter={"oops": 1}))

        result = await judge_pending_matches(budget_db, alert_channel="in_app")

        assert result["judged"] == 1
        cursor = await budget_db.execute("SELECT cover_letter, trace FROM match_results")
        row = await cursor.fetchone()
        assert row["cover_letter"] is None
        assert json.loads(row["trace"])["llm_judge"]["fit_score"] == 95

    async def test_letter_instruction_includes_computed_threshold(self, budget_db, monkeypatch):
        await seed_matches(budget_db, count=1)
        cursor = await budget_db.execute("SELECT score FROM match_results")
        det = (await cursor.fetchone())["score"]
        provider = FakeProvider()
        install_provider(monkeypatch, provider)

        await judge_pending_matches(budget_db, alert_channel="in_app")

        import math
        expected = max(0, math.ceil((85 - 0.4 * det) / 0.6))
        prompt = provider.prompts[0]
        if expected > 100:
            assert "Do not write a cover letter" in prompt
        else:
            assert f"If your fit_score is {expected} or higher" in prompt
            assert "Do not use em dashes, colons, or semicolons" in prompt
            assert "confident, direct, technical, and human" in prompt

    async def test_rescore_all_preserves_judgment(self, budget_db, monkeypatch):
        await seed_matches(budget_db, count=1)
        install_provider(
            monkeypatch, FakeProvider(fit_score=100, cover_letter="Dear team. Yash")
        )
        await judge_pending_matches(budget_db)

        await rescore_backlog(budget_db, rescore_all=True)

        cursor = await budget_db.execute(
            "SELECT score, summary, cover_letter, trace FROM match_results"
        )
        row = await cursor.fetchone()
        trace = json.loads(row["trace"])
        assert trace["llm_judge"]["fit_score"] == 100
        assert row["summary"] == "Great fit, but salary is unstated."
        assert row["cover_letter"] == "Dear team. Yash"
        # Score stays blended, not reset to pure deterministic
        assert row["score"] == round(0.6 * 100 + 0.4 * trace["llm_judge"]["deterministic_score"])
