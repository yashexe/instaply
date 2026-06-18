"""Discovery service tests — fake candidate provider and fake prober."""

import pytest

import src.discovery.service as service
from src.config import settings
from src.discovery import repository as discovery_repo
from src.discovery.models import Candidate, ProbeResult
from src.preferences.repository import upsert_preferences
from tests.conftest import insert_source


class FakeProvider:
    def __init__(self, names):
        self.names = names

    async def candidates(self, preferences, profile, known_companies):
        return [
            Candidate(company_name=name, origin="seed_list", reason="test")
            for name in self.names
        ]


class FakeProber:
    """Maps the first slug guess to a preset outcome."""

    def __init__(self, results, max_probes=60):
        self.results = results
        self.max_probes = max_probes
        self.probes_used = 0

    @property
    def exhausted(self):
        return self.probes_used >= self.max_probes

    async def probe_company(self, slugs):
        self.probes_used += 1
        return self.results.get(slugs[0])


def hit(slug, titles, provider="greenhouse"):
    return ProbeResult(
        found=True,
        provider=provider,
        slug=slug,
        job_count=len(titles),
        titles=titles,
    )


MISS = ProbeResult(found=False)


async def set_prefs(db, target_roles=("Software Engineer",)):
    await upsert_preferences(db, "default", {"target_roles": list(target_roles)})


def use_provider(monkeypatch, names):
    monkeypatch.setattr(service, "SeedListProvider", lambda: FakeProvider(names))


class TestRunDiscovery:
    async def test_relevant_board_becomes_suggestion(self, db, monkeypatch):
        await set_prefs(db)
        use_provider(monkeypatch, ["Acme"])
        prober = FakeProber({"acme": hit("acme", ["Senior Software Engineer"])})

        stats = await service.run_discovery(db, "default", use_llm=False, prober=prober)

        assert stats.suggested == 1
        rows = await discovery_repo.list_by_status(db, "default", "suggested")
        assert rows[0]["company_name"] == "Acme"
        assert rows[0]["provider"] == "greenhouse"
        assert rows[0]["matching_titles"] == ["Senior Software Engineer"]
        assert rows[0]["board_url"] == "https://boards.greenhouse.io/acme"

    async def test_no_target_roles_skips_run(self, db, monkeypatch):
        use_provider(monkeypatch, ["Acme"])
        prober = FakeProber({"acme": hit("acme", ["Software Engineer"])})
        stats = await service.run_discovery(db, "default", use_llm=False, prober=prober)
        assert stats.candidates == 0
        assert prober.probes_used == 0

    async def test_existing_source_company_not_suggested(self, db, monkeypatch):
        await set_prefs(db)
        await insert_source(db, company_name="Acme")
        use_provider(monkeypatch, ["Acme"])
        prober = FakeProber({"acme": hit("acme", ["Software Engineer"])})

        stats = await service.run_discovery(db, "default", use_llm=False, prober=prober)

        assert stats.skipped_known == 1
        assert stats.suggested == 0
        assert prober.probes_used == 0

    async def test_existing_source_matched_by_slug(self, db, monkeypatch):
        """A source added under a different display name still blocks the
        same board slug from being re-suggested."""
        await set_prefs(db)
        await insert_source(
            db,
            company_name="Acme Inc (manual)",
            source_url="https://boards-api.greenhouse.io/v1/boards/acme/jobs?content=true",
        )
        use_provider(monkeypatch, ["Acme"])
        prober = FakeProber({"acme": hit("acme", ["Software Engineer"])})

        stats = await service.run_discovery(db, "default", use_llm=False, prober=prober)

        assert stats.suggested == 0
        assert stats.skipped_known == 1

    async def test_rejected_company_never_resurfaces(self, db, monkeypatch):
        await set_prefs(db)
        use_provider(monkeypatch, ["Acme"])
        prober = FakeProber({"acme": hit("acme", ["Software Engineer"])})
        await service.run_discovery(db, "default", use_llm=False, prober=prober)

        rows = await discovery_repo.list_by_status(db, "default", "suggested")
        await service.reject_suggestion(db, "default", rows[0]["id"])

        stats = await service.run_discovery(db, "default", use_llm=False, prober=prober)
        assert stats.skipped_known == 1
        assert stats.suggested == 0

    async def test_irrelevant_board_recorded(self, db, monkeypatch):
        await set_prefs(db)
        use_provider(monkeypatch, ["Acme"])
        prober = FakeProber({"acme": hit("acme", ["Account Executive", "Recruiter"])})

        stats = await service.run_discovery(db, "default", use_llm=False, prober=prober)

        assert stats.irrelevant == 1
        rows = await discovery_repo.list_by_status(db, "default", "irrelevant")
        assert rows[0]["company_name"] == "Acme"

    async def test_not_found_recorded(self, db, monkeypatch):
        await set_prefs(db)
        use_provider(monkeypatch, ["Ghost Co"])
        prober = FakeProber({"ghost": MISS})  # "Co" is a stripped legal suffix

        stats = await service.run_discovery(db, "default", use_llm=False, prober=prober)

        assert stats.not_found == 1
        rows = await discovery_repo.list_by_status(db, "default", "not_found")
        assert rows[0]["company_name"] == "Ghost Co"

    async def test_inconclusive_probe_records_nothing(self, db, monkeypatch):
        await set_prefs(db)
        use_provider(monkeypatch, ["Acme"])
        prober = FakeProber({})  # probe_company returns None

        stats = await service.run_discovery(db, "default", use_llm=False, prober=prober)

        assert stats.suggested == stats.not_found == stats.irrelevant == 0
        for status in ("suggested", "not_found", "irrelevant"):
            assert await discovery_repo.list_by_status(db, "default", status) == []

    async def test_pending_cap_stops_suggesting(self, db, monkeypatch):
        await set_prefs(db)
        monkeypatch.setattr(settings, "discovery_max_suggestions_pending", 2)
        names = ["Alpha", "Beta", "Gamma", "Delta"]
        use_provider(monkeypatch, names)
        prober = FakeProber(
            {n.lower(): hit(n.lower(), ["Software Engineer"]) for n in names}
        )

        stats = await service.run_discovery(db, "default", use_llm=False, prober=prober)

        assert stats.suggested == 2

    async def test_probe_budget_stops_run(self, db, monkeypatch):
        await set_prefs(db)
        use_provider(monkeypatch, ["Alpha", "Beta", "Gamma"])
        prober = FakeProber(
            {n: hit(n, ["Software Engineer"]) for n in ["alpha", "beta", "gamma"]},
            max_probes=1,
        )

        stats = await service.run_discovery(db, "default", use_llm=False, prober=prober)

        assert stats.suggested == 1  # stopped after budget ran out


class TestAcceptReject:
    async def make_suggestion(self, db, monkeypatch):
        await set_prefs(db)
        use_provider(monkeypatch, ["Acme"])
        prober = FakeProber({"acme": hit("acme", ["Software Engineer"])})
        await service.run_discovery(db, "default", use_llm=False, prober=prober)
        rows = await discovery_repo.list_by_status(db, "default", "suggested")
        return rows[0]

    async def test_accept_creates_active_source(self, db, monkeypatch):
        suggestion = await self.make_suggestion(db, monkeypatch)
        updated = await service.accept_suggestion(db, "default", suggestion["id"])

        assert updated["status"] == "accepted"
        assert updated["source_id"]
        cursor = await db.execute(
            "SELECT * FROM sources WHERE id = ?", (updated["source_id"],)
        )
        source = dict(await cursor.fetchone())
        assert source["status"] == "active"
        assert source["company_name"] == "Acme"
        assert (
            source["normalized_url"]
            == "https://boards-api.greenhouse.io/v1/boards/acme/jobs?content=true"
        )

    async def test_accept_twice_returns_none(self, db, monkeypatch):
        suggestion = await self.make_suggestion(db, monkeypatch)
        assert await service.accept_suggestion(db, "default", suggestion["id"])
        assert await service.accept_suggestion(db, "default", suggestion["id"]) is None

    async def test_reject_is_terminal(self, db, monkeypatch):
        suggestion = await self.make_suggestion(db, monkeypatch)
        updated = await service.reject_suggestion(db, "default", suggestion["id"])
        assert updated["status"] == "rejected"
        assert await service.reject_suggestion(db, "default", suggestion["id"]) is None

    async def test_accept_unknown_id_returns_none(self, db):
        assert await service.accept_suggestion(db, "default", "nope") is None
