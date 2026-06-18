"""Tests for discovery candidate providers."""

import json

import pytest

from src.common.taxonomy import DOMAIN_KEYWORDS
from src.discovery.providers import LLMCandidateProvider, SeedListProvider


def profile_with_domains(domains):
    return {"structured_profile": {"domains": domains}}


class TestSeedListProvider:
    async def test_filters_by_profile_domains(self):
        provider = SeedListProvider()
        candidates = await provider.candidates(
            {}, profile_with_domains(["FinTech"]), []
        )
        assert candidates
        names = {c.company_name for c in candidates}
        assert "Stripe" in names
        assert "Anduril" not in names  # Hardware Automation / AI/ML only
        assert all(c.origin == "seed_list" for c in candidates)

    async def test_no_profile_returns_all_seeds(self):
        provider = SeedListProvider()
        candidates = await provider.candidates({}, None, [])
        seeds = json.loads(
            (provider._seeds_path).read_text()
        )
        assert len(candidates) == len(seeds)

    async def test_seed_domains_use_taxonomy_vocabulary(self):
        provider = SeedListProvider()
        seeds = json.loads(provider._seeds_path.read_text())
        valid = set(DOMAIN_KEYWORDS)
        for seed in seeds:
            unknown = set(seed["domains"]) - valid
            assert not unknown, f"{seed['name']} has unknown domains {unknown}"

    async def test_missing_seed_file_returns_empty(self, tmp_path):
        provider = SeedListProvider(seeds_path=tmp_path / "nope.json")
        assert await provider.candidates({}, None, []) == []


class TestDiscoveryBudgetSlice:
    @pytest.fixture
    def budget_db(self, db, monkeypatch):
        monkeypatch.setattr("src.db.connection._db", db)
        return db

    async def test_discovery_slice_is_enforced(self, budget_db, monkeypatch):
        from src.config import settings
        from src.llm import budget

        monkeypatch.setattr(settings, "llm_discovery_daily_budget", 2)
        assert await budget.spend("discovery")
        assert await budget.spend("discovery")
        assert not await budget.spend("discovery")
        # Other categories are unaffected by the discovery slice.
        assert await budget.spend("extract")


class FakeLLM:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    async def structured_output(self, system_prompt, user_prompt, schema=None):
        self.calls.append(user_prompt)
        return self.payload

    async def generate(self, system_prompt, user_prompt):
        return ""


class TestLLMCandidateProvider:
    @pytest.fixture
    def llm_configured(self, monkeypatch):
        monkeypatch.setattr(
            "src.discovery.providers.settings.__class__.llm_configured",
            property(lambda self: True),
        )

    async def test_returns_candidates_from_llm(self, monkeypatch, llm_configured):
        fake = FakeLLM(
            {"companies": [{"company_name": "Acme", "reason": "FinTech fit"}]}
        )
        monkeypatch.setattr("src.llm.factory.get_llm_provider", lambda: fake)

        async def allow(category, n=1):
            return True

        monkeypatch.setattr("src.discovery.providers.budget.spend", allow)
        candidates = await LLMCandidateProvider().candidates(
            {"target_roles": ["Software Engineer"]}, None, ["Stripe"]
        )
        assert len(candidates) == 1
        assert candidates[0].company_name == "Acme"
        assert candidates[0].origin == "llm"
        # The exclusion list must reach the prompt.
        assert "Stripe" in fake.calls[0]

    async def test_budget_exhausted_returns_empty(self, monkeypatch, llm_configured):
        async def deny(category, n=1):
            return False

        monkeypatch.setattr("src.discovery.providers.budget.spend", deny)
        candidates = await LLMCandidateProvider().candidates({}, None, [])
        assert candidates == []

    async def test_no_llm_key_returns_empty(self, monkeypatch):
        monkeypatch.setattr(
            "src.discovery.providers.settings.__class__.llm_configured",
            property(lambda self: False),
        )
        candidates = await LLMCandidateProvider().candidates({}, None, [])
        assert candidates == []

    async def test_llm_error_returns_empty(self, monkeypatch, llm_configured):
        async def allow(category, n=1):
            return True

        monkeypatch.setattr("src.discovery.providers.budget.spend", allow)

        def boom():
            raise RuntimeError("provider down")

        monkeypatch.setattr("src.llm.factory.get_llm_provider", boom)
        candidates = await LLMCandidateProvider().candidates({}, None, [])
        assert candidates == []

    async def test_caps_candidates(self, monkeypatch, llm_configured):
        from src.config import settings

        many = {
            "companies": [
                {"company_name": f"Company {i}"}
                for i in range(settings.discovery_max_llm_candidates + 10)
            ]
        }
        fake = FakeLLM(many)
        monkeypatch.setattr("src.llm.factory.get_llm_provider", lambda: fake)

        async def allow(category, n=1):
            return True

        monkeypatch.setattr("src.discovery.providers.budget.spend", allow)
        candidates = await LLMCandidateProvider().candidates({}, None, [])
        assert len(candidates) == settings.discovery_max_llm_candidates
