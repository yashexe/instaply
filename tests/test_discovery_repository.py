"""Tests for the discovery staging repository."""

import pytest

from src.discovery import repository as repo


async def insert_basic(db, *, name_key="acme", status="suggested", **kwargs):
    defaults = dict(
        company_name="Acme",
        name_key=name_key,
        status=status,
        origin="seed_list",
        provider="greenhouse",
        slug="acme",
        board_url="https://boards.greenhouse.io/acme",
        normalized_url="https://boards-api.greenhouse.io/v1/boards/acme/jobs?content=true",
        job_count=12,
        matching_titles=["Senior Software Engineer"],
    )
    defaults.update(kwargs)
    return await repo.insert_discovered(db, "default", **defaults)


class TestInsertAndDedupe:
    async def test_insert_returns_id_and_roundtrips(self, db):
        discovered_id = await insert_basic(db)
        assert discovered_id is not None
        row = await repo.get_suggestion(db, discovered_id, "default")
        assert row["company_name"] == "Acme"
        assert row["status"] == "suggested"
        assert row["matching_titles"] == ["Senior Software Engineer"]

    async def test_duplicate_name_key_returns_none(self, db):
        first = await insert_basic(db)
        second = await insert_basic(db, company_name="Acme Corp")
        assert first is not None
        assert second is None

    async def test_same_name_key_different_user_allowed(self, db):
        await db.execute(
            "INSERT INTO users (id, email, name) VALUES ('other', 'o@x.com', 'O')"
        )
        first = await insert_basic(db)
        await db.execute(
            """
            INSERT INTO discovered_companies (
                id, user_id, company_name, name_key, status, origin
            ) VALUES ('xyz', 'other', 'Acme', 'acme', 'suggested', 'seed_list')
            """
        )
        await db.commit()
        assert first is not None


class TestStatusTransitions:
    async def test_set_status_accept_links_source(self, db):
        discovered_id = await insert_basic(db)
        updated = await repo.set_status(
            db, discovered_id, "default", "accepted", source_id=None
        )
        assert updated["status"] == "accepted"
        assert updated["decided_at"] is not None

    async def test_set_status_rejected(self, db):
        discovered_id = await insert_basic(db)
        updated = await repo.set_status(db, discovered_id, "default", "rejected")
        assert updated["status"] == "rejected"

    async def test_invalid_status_rejected_by_check_constraint(self, db):
        discovered_id = await insert_basic(db)
        with pytest.raises(Exception):
            await db.execute(
                "UPDATE discovered_companies SET status = 'bogus' WHERE id = ?",
                (discovered_id,),
            )


class TestKnownNameKeys:
    async def test_terminal_statuses_always_known(self, db):
        a = await insert_basic(db, name_key="a", status="suggested")
        b = await insert_basic(db, name_key="b", company_name="B", status="suggested")
        await repo.set_status(db, b, "default", "rejected")
        keys = await repo.known_name_keys(db, "default")
        assert {"a", "b"} <= keys

    async def test_recent_not_found_is_known(self, db):
        await insert_basic(db, name_key="ghost", status="not_found")
        keys = await repo.known_name_keys(db, "default")
        assert "ghost" in keys

    async def test_stale_not_found_becomes_recheckable(self, db):
        await insert_basic(db, name_key="ghost", status="not_found")
        await db.execute(
            """
            UPDATE discovered_companies
            SET last_probed_at = datetime(CURRENT_TIMESTAMP, '-30 days')
            WHERE name_key = 'ghost'
            """
        )
        await db.commit()
        keys = await repo.known_name_keys(db, "default")
        assert "ghost" not in keys


class TestListAndCount:
    async def test_list_by_status_ordered_by_job_count(self, db):
        await insert_basic(db, name_key="small", company_name="Small", job_count=2)
        await insert_basic(db, name_key="big", company_name="Big", job_count=50)
        rows = await repo.list_by_status(db, "default", "suggested")
        assert [r["company_name"] for r in rows] == ["Big", "Small"]

    async def test_count_by_status(self, db):
        await insert_basic(db, name_key="a")
        b = await insert_basic(db, name_key="b", company_name="B")
        await repo.set_status(db, b, "default", "rejected")
        assert await repo.count_by_status(db, "default", "suggested") == 1
        assert await repo.count_by_status(db, "default", "rejected") == 1


class TestReprobeUpdate:
    async def test_reprobe_promotes_not_found_to_suggested(self, db):
        await insert_basic(
            db, name_key="ghost", status="not_found", provider=None, slug=None
        )
        await repo.reprobe_update(
            db,
            "default",
            "ghost",
            status="suggested",
            provider="lever",
            slug="ghost",
            board_url="https://jobs.lever.co/ghost",
            normalized_url="https://api.lever.co/v0/postings/ghost?mode=json",
            job_count=7,
            matching_titles=["Data Engineer"],
        )
        rows = await repo.list_by_status(db, "default", "suggested")
        assert len(rows) == 1
        assert rows[0]["provider"] == "lever"
        assert rows[0]["matching_titles"] == ["Data Engineer"]

    async def test_reprobe_does_not_touch_terminal_rows(self, db):
        discovered_id = await insert_basic(db, name_key="acme")
        await repo.set_status(db, discovered_id, "default", "rejected")
        await repo.reprobe_update(
            db,
            "default",
            "acme",
            status="suggested",
            provider="lever",
            slug="acme",
            board_url=None,
            normalized_url=None,
            job_count=1,
            matching_titles=[],
        )
        row = await repo.get_suggestion(db, discovered_id, "default")
        assert row["status"] == "rejected"
