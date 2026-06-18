"""Backlog rescore tests — scoring jobs skipped by baselined first polls."""

import json

from src.ingestion.models import RawJob
from src.jobs.repository import upsert_raw_job
from src.matching.service import rescore_backlog
from src.preferences.repository import default_preferences, upsert_preferences
from src.profile.repository import create_profile
from tests.conftest import insert_source

STRUCTURED_PROFILE = {
    "skills": ["Python", "PostgreSQL", "AWS"],
    "roles": ["Backend Engineer"],
    "domains": ["fintech"],
    "years_of_experience": 7,
}


def raw_job(provider_job_id: str, **overrides) -> RawJob:
    base = {
        "provider_job_id": provider_job_id,
        "title": "Senior Backend Engineer",
        "company_name": "Acme",
        "url": f"https://boards.greenhouse.io/acme/jobs/{provider_job_id}",
        "locations": ["Toronto, Ontario"],
        "remote_policy": "remote",
        "description_text": "Build Python APIs at scale in fintech.",
        "raw_data": {"id": provider_job_id},
    }
    base.update(overrides)
    return RawJob(**base)


async def setup_profile(db, user_id: str = "default") -> str:
    return await create_profile(
        db, user_id, "resume text", json.dumps(STRUCTURED_PROFILE), 1
    )


async def insert_jobs(db, count: int) -> list[str]:
    source = await insert_source(db)
    job_ids = []
    # Vary the title so semantic dedupe keeps each posting distinct.
    for i in range(count):
        job_id, _, _ = await upsert_raw_job(
            db,
            source,
            raw_job(str(1000 + i), title=f"Senior Backend Engineer {i}"),
        )
        job_ids.append(job_id)
    return job_ids


async def count_matches(db) -> int:
    cursor = await db.execute("SELECT COUNT(*) FROM match_results")
    return (await cursor.fetchone())[0]


class TestRescoreBacklog:
    async def test_requires_active_profile(self, db):
        await insert_jobs(db, 2)
        result = await rescore_backlog(db)
        assert result["error"] == "no_active_profile"
        assert await count_matches(db) == 0

    async def test_scores_all_unscored_jobs(self, db):
        await setup_profile(db)
        await insert_jobs(db, 3)

        result = await rescore_backlog(db)

        assert result["error"] is None
        assert result["total"] == 3
        assert result["scored"] == 3
        assert sum(result["decisions"].values()) == 3
        assert await count_matches(db) == 3

    async def test_second_run_is_a_no_op(self, db):
        await setup_profile(db)
        await insert_jobs(db, 2)

        await rescore_backlog(db)
        result = await rescore_backlog(db)

        assert result["total"] == 0
        assert result["scored"] == 0
        assert await count_matches(db) == 2

    async def test_limit_caps_the_run(self, db):
        await setup_profile(db)
        await insert_jobs(db, 3)

        result = await rescore_backlog(db, limit=2)

        assert result["total"] == 2
        assert await count_matches(db) == 2

    async def test_alerts_are_recorded_in_app(self, db):
        await setup_profile(db)
        preferences = default_preferences()
        preferences.update(
            {
                "target_roles": ["backend engineer"],
                "locations": ["Toronto"],
                "alert_threshold": 1,
            }
        )
        await upsert_preferences(db, "default", preferences)
        await insert_jobs(db, 1)

        result = await rescore_backlog(db)

        assert result["decisions"].get("alert") == 1
        cursor = await db.execute("SELECT channel, status FROM alerts")
        rows = await cursor.fetchall()
        assert len(rows) == 1
        assert rows[0]["channel"] == "in_app"
        assert rows[0]["status"] == "sent"

    async def test_rescore_all_recomputes_in_place(self, db):
        await setup_profile(db)
        await insert_jobs(db, 2)
        await rescore_backlog(db)

        cursor = await db.execute("SELECT id, score FROM match_results")
        before = {row["id"]: row["score"] for row in await cursor.fetchall()}
        # Simulate a stale score from an older scorer version
        stale_id = next(iter(before))
        await db.execute(
            "UPDATE match_results SET score = 1, decision = 'ignore' WHERE id = ?",
            (stale_id,),
        )
        await db.commit()

        result = await rescore_backlog(db, rescore_all=True)

        assert result["total"] == 2
        assert result["scored"] == 2
        cursor = await db.execute("SELECT id, score FROM match_results")
        after = {row["id"]: row["score"] for row in await cursor.fetchall()}
        assert set(after) == set(before)  # same rows, no duplicates
        assert after[stale_id] == before[stale_id]  # recomputed, not stale

    async def test_reports_progress(self, db):
        await setup_profile(db)
        await insert_jobs(db, 2)
        seen = []

        await rescore_backlog(
            db, progress_callback=lambda done, total: seen.append((done, total))
        )

        assert seen == [(1, 2), (2, 2)]
