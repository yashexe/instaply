"""List filtering tests for jobs and matches."""

import uuid

from src.ingestion.models import RawJob
from src.jobs.repository import list_jobs, upsert_raw_job
from src.matching.repository import list_match_results
from tests.conftest import insert_source


async def seed_jobs(db) -> tuple[dict, dict, list[str]]:
    """Insert two sources and three jobs; return (source_a, source_b, job_ids)."""
    source_a = await insert_source(db, company_name="Acme")
    source_b = await insert_source(db, company_name="Globex")

    jobs = [
        (source_a, RawJob(
            provider_job_id="1",
            title="Senior Backend Engineer",
            company_name="Acme",
            url="https://example.com/jobs/1",
            remote_policy="remote",
            posted_at="2026-06-01T00:00:00+00:00",
        )),
        (source_a, RawJob(
            provider_job_id="2",
            title="Office Manager",
            company_name="Acme",
            url="https://example.com/jobs/2",
            remote_policy="onsite",
        )),
        (source_b, RawJob(
            provider_job_id="3",
            title="Data Engineer (100% remote)",
            company_name="Globex",
            url="https://example.com/jobs/3",
            remote_policy="remote",
            posted_at="2026-06-10T00:00:00+00:00",
        )),
    ]
    job_ids = []
    for source, raw in jobs:
        job_id, _, _ = await upsert_raw_job(db, source, raw)
        job_ids.append(job_id)
    return source_a, source_b, job_ids


class TestListJobsFilters:
    async def test_search_matches_title_case_insensitively(self, db):
        await seed_jobs(db)
        results = await list_jobs(db, q="backend")
        assert [job["title"] for job in results] == ["Senior Backend Engineer"]

    async def test_search_matches_company(self, db):
        await seed_jobs(db)
        results = await list_jobs(db, q="globex")
        assert [job["company_name"] for job in results] == ["Globex"]

    async def test_search_escapes_like_wildcards(self, db):
        await seed_jobs(db)
        # "%" must be treated literally, not as match-everything
        results = await list_jobs(db, q="100%")
        assert [job["title"] for job in results] == ["Data Engineer (100% remote)"]

    async def test_remote_policy_filter(self, db):
        await seed_jobs(db)
        results = await list_jobs(db, remote_policy="onsite")
        assert [job["title"] for job in results] == ["Office Manager"]

    async def test_source_filter(self, db):
        source_a, _, _ = await seed_jobs(db)
        results = await list_jobs(db, source_id=source_a["id"])
        assert {job["company_name"] for job in results} == {"Acme"}
        assert len(results) == 2

    async def test_combined_filters(self, db):
        source_a, _, _ = await seed_jobs(db)
        results = await list_jobs(db, source_id=source_a["id"], remote_policy="remote", q="engineer")
        assert [job["title"] for job in results] == ["Senior Backend Engineer"]

    async def test_no_filters_returns_all(self, db):
        await seed_jobs(db)
        assert len(await list_jobs(db)) == 3


class TestListJobsSort:
    async def stagger_first_seen(self, db, job_ids):
        """Give each job a distinct first_seen_at, oldest first."""
        for index, job_id in enumerate(job_ids):
            await db.execute(
                "UPDATE job_postings SET first_seen_at = datetime('now', ?) WHERE id = ?",
                (f"-{len(job_ids) - index} hours", job_id),
            )
        await db.commit()

    async def test_newest_first_is_default(self, db):
        _, _, job_ids = await seed_jobs(db)
        await self.stagger_first_seen(db, job_ids)
        results = await list_jobs(db)
        assert [job["id"] for job in results] == list(reversed(job_ids))

    async def test_oldest_first(self, db):
        _, _, job_ids = await seed_jobs(db)
        await self.stagger_first_seen(db, job_ids)
        results = await list_jobs(db, sort="oldest")
        assert [job["id"] for job in results] == job_ids

    async def test_recently_posted_puts_nulls_last(self, db):
        await seed_jobs(db)
        results = await list_jobs(db, sort="posted")
        assert [job["posted_at"] for job in results] == [
            "2026-06-10T00:00:00+00:00",
            "2026-06-01T00:00:00+00:00",
            None,
        ]

    async def test_title_alphabetical(self, db):
        await seed_jobs(db)
        results = await list_jobs(db, sort="title")
        assert [job["title"] for job in results] == [
            "Data Engineer (100% remote)",
            "Office Manager",
            "Senior Backend Engineer",
        ]

    async def test_company_alphabetical(self, db):
        await seed_jobs(db)
        results = await list_jobs(db, sort="company")
        assert [job["company_name"] for job in results] == ["Acme", "Acme", "Globex"]

    async def test_unknown_sort_falls_back_to_newest(self, db):
        _, _, job_ids = await seed_jobs(db)
        await self.stagger_first_seen(db, job_ids)
        results = await list_jobs(db, sort="nonsense")
        assert [job["id"] for job in results] == list(reversed(job_ids))


async def insert_profile(db, user_id: str = "default") -> str:
    profile_id = uuid.uuid4().hex
    await db.execute(
        """
        INSERT INTO candidate_profiles (id, user_id, version, resume_text, structured_profile)
        VALUES (?, ?, 1, '', '{}')
        """,
        (profile_id, user_id),
    )
    await db.commit()
    return profile_id


async def insert_match(db, profile_id: str, job_id: str, score: int, decision: str) -> str:
    match_id = uuid.uuid4().hex
    await db.execute(
        """
        INSERT INTO match_results (
            id, user_id, candidate_profile_id, job_posting_id, score, decision
        ) VALUES (?, 'default', ?, ?, ?, ?)
        """,
        (match_id, profile_id, job_id, score, decision),
    )
    await db.commit()
    return match_id


async def seed_matches(db) -> list[str]:
    _, _, job_ids = await seed_jobs(db)
    profile_id = await insert_profile(db)
    return [
        await insert_match(db, profile_id, job_ids[0], 90, "alert"),
        await insert_match(db, profile_id, job_ids[1], 40, "rejected"),
        await insert_match(db, profile_id, job_ids[2], 70, "digest"),
    ]


class TestListMatchesFilters:
    async def test_search_matches_job_title(self, db):
        await seed_matches(db)
        results = await list_match_results(db, "default", q="backend")
        assert [match["score"] for match in results] == [90]

    async def test_min_score_filter(self, db):
        await seed_matches(db)
        results = await list_match_results(db, "default", min_score=65)
        assert {match["score"] for match in results} == {90, 70}

    async def test_decision_filter(self, db):
        await seed_matches(db)
        results = await list_match_results(db, "default", decision="digest")
        assert [match["score"] for match in results] == [70]

    async def test_sort_by_score(self, db):
        await seed_matches(db)
        results = await list_match_results(db, "default", sort="score")
        assert [match["score"] for match in results] == [90, 70, 40]

    async def test_other_users_matches_excluded(self, db):
        await seed_matches(db)
        results = await list_match_results(db, "someone-else")
        assert results == []
