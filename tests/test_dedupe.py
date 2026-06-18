"""Job dedupe and URL normalization tests against a real schema."""

from src.ingestion.models import RawJob
from src.jobs.repository import normalize_url, upsert_raw_job
from tests.conftest import insert_source


def raw_job(**overrides) -> RawJob:
    base = {
        "provider_job_id": "12345",
        "title": "Senior Backend Engineer",
        "company_name": "Acme",
        "url": "https://boards.greenhouse.io/acme/jobs/12345",
        "locations": ["Toronto, Ontario"],
        "remote_policy": "remote",
        "description_text": "Build APIs in Python.",
        "raw_data": {"id": 12345},
    }
    base.update(overrides)
    return RawJob(**base)


async def count_jobs(db) -> int:
    cursor = await db.execute("SELECT COUNT(*) FROM job_postings")
    row = await cursor.fetchone()
    return row[0]


class TestUpsertRawJob:
    async def test_first_insert_is_new(self, db):
        source = await insert_source(db)
        job_id, is_new, content_changed = await upsert_raw_job(db, source, raw_job())
        assert is_new
        assert content_changed
        assert job_id

    async def test_repolling_same_job_does_not_duplicate(self, db):
        source = await insert_source(db)
        first_id, _, _ = await upsert_raw_job(db, source, raw_job())
        second_id, is_new, content_changed = await upsert_raw_job(db, source, raw_job())

        assert second_id == first_id
        assert not is_new
        assert not content_changed
        assert await count_jobs(db) == 1

    async def test_content_change_detected(self, db):
        source = await insert_source(db)
        first_id, _, _ = await upsert_raw_job(db, source, raw_job())
        second_id, is_new, content_changed = await upsert_raw_job(
            db, source, raw_job(description_text="Build APIs in Python and Go.")
        )

        assert second_id == first_id
        assert not is_new
        assert content_changed

    async def test_unchanged_repoll_does_not_touch_updated_at(self, db):
        source = await insert_source(db)
        job_id, _, _ = await upsert_raw_job(db, source, raw_job())
        await db.execute(
            """
            UPDATE job_postings
            SET updated_at = '2020-01-01 00:00:00',
                last_seen_at = '2020-01-01 00:00:00',
                status = 'closed'
            WHERE id = ?
            """,
            (job_id,),
        )
        await db.commit()

        await upsert_raw_job(db, source, raw_job())

        cursor = await db.execute(
            "SELECT updated_at, last_seen_at, status FROM job_postings WHERE id = ?",
            (job_id,),
        )
        row = await cursor.fetchone()
        assert row["updated_at"] == "2020-01-01 00:00:00"
        assert row["last_seen_at"] != "2020-01-01 00:00:00"
        assert row["status"] == "active"

    async def test_changed_repoll_touches_updated_at(self, db):
        source = await insert_source(db)
        job_id, _, _ = await upsert_raw_job(db, source, raw_job())
        await db.execute(
            "UPDATE job_postings SET updated_at = '2020-01-01 00:00:00' WHERE id = ?",
            (job_id,),
        )
        await db.commit()

        await upsert_raw_job(
            db, source, raw_job(description_text="Build APIs in Python and Go.")
        )

        cursor = await db.execute(
            "SELECT updated_at FROM job_postings WHERE id = ?", (job_id,)
        )
        row = await cursor.fetchone()
        assert row["updated_at"] != "2020-01-01 00:00:00"

    async def test_semantic_dedupe_without_provider_id(self, db):
        source = await insert_source(db)
        first_id, _, _ = await upsert_raw_job(
            db, source, raw_job(provider_job_id=None, url=None)
        )
        # Same company/title/location, still no stable identifiers
        second_id, is_new, _ = await upsert_raw_job(
            db, source, raw_job(provider_job_id=None, url=None)
        )

        assert second_id == first_id
        assert not is_new
        assert await count_jobs(db) == 1

    async def test_different_jobs_are_kept_separate(self, db):
        source = await insert_source(db)
        await upsert_raw_job(db, source, raw_job())
        await upsert_raw_job(
            db,
            source,
            raw_job(
                provider_job_id="99999",
                title="Data Engineer",
                url="https://boards.greenhouse.io/acme/jobs/99999",
            ),
        )
        assert await count_jobs(db) == 2


class TestNormalizeUrl:
    def test_strips_tracking_params(self):
        url = "https://boards.greenhouse.io/acme/jobs/1?utm_source=x&utm_medium=y&gh_jid=1"
        assert normalize_url(url) == "https://boards.greenhouse.io/acme/jobs/1"

    def test_preserves_meaningful_params(self):
        url = "https://example.com/jobs?id=42&utm_campaign=z"
        assert normalize_url(url) == "https://example.com/jobs?id=42"

    def test_lowercases_host_and_trims_trailing_slash(self):
        assert (
            normalize_url("https://Example.COM/Jobs/123/")
            == "https://example.com/Jobs/123"
        )

    def test_none_stays_none(self):
        assert normalize_url(None) is None
