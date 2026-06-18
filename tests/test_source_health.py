"""Source health tracking, degraded retry cadence, and escalation tests."""

import httpx
import pytest
import respx

import src.ingestion.http as ingestion_http
from src.config import settings
from src.ingestion.service import poll_source
from src.sources.repository import (
    list_due_sources,
    mark_source_failure,
    mark_source_success,
)
from tests.conftest import insert_source

GREENHOUSE_URL = "https://boards-api.greenhouse.io/v1/boards/acme/jobs?content=true"


@pytest.fixture(autouse=True)
def no_backoff(monkeypatch):
    monkeypatch.setattr(ingestion_http, "BACKOFF_BASE_SECONDS", 0)


async def get_source_row(db, source_id: str) -> dict:
    cursor = await db.execute("SELECT * FROM sources WHERE id = ?", (source_id,))
    return dict(await cursor.fetchone())


class TestMarkSourceFailure:
    async def test_failure_increments_error_count(self, db):
        source = await insert_source(db)
        just_degraded = await mark_source_failure(db, source["id"], "boom")

        row = await get_source_row(db, source["id"])
        assert row["consecutive_error_count"] == 1
        assert row["last_error_message"] == "boom"
        assert row["status"] == "active"
        assert not just_degraded

    async def test_degrades_and_escalates_exactly_once(self, db):
        source = await insert_source(db)
        threshold = settings.source_failure_escalation_threshold

        transitions = [
            await mark_source_failure(db, source["id"], f"failure {i}")
            for i in range(threshold + 2)
        ]

        row = await get_source_row(db, source["id"])
        assert row["status"] == "degraded"
        assert row["consecutive_error_count"] == threshold + 2
        # Only the failure that crossed the threshold reports the transition.
        assert transitions.count(True) == 1
        assert transitions[threshold - 1] is True

    async def test_success_resets_health(self, db):
        source = await insert_source(db)
        for i in range(settings.source_failure_escalation_threshold):
            await mark_source_failure(db, source["id"], "boom")
        await mark_source_success(db, source["id"])

        row = await get_source_row(db, source["id"])
        assert row["status"] == "active"
        assert row["consecutive_error_count"] == 0
        assert row["last_error_message"] is None


class TestListDueSources:
    async def test_never_polled_source_is_due(self, db):
        source = await insert_source(db)
        due = await list_due_sources(db)
        assert [s["id"] for s in due] == [source["id"]]

    async def test_recently_polled_source_is_not_due(self, db):
        source = await insert_source(db, fetch_interval_seconds=3600)
        await mark_source_success(db, source["id"])
        assert await list_due_sources(db) == []

    async def test_degraded_source_retries_after_slowed_interval(self, db):
        source = await insert_source(db, status="degraded", fetch_interval_seconds=60)
        # Last attempt long ago — well past interval * multiplier
        await db.execute(
            """
            UPDATE sources
            SET last_error_at = datetime('now', '-1 hour'),
                last_success_at = datetime('now', '-2 hours')
            WHERE id = ?
            """,
            (source["id"],),
        )
        await db.commit()
        due = await list_due_sources(db)
        assert [s["id"] for s in due] == [source["id"]]

    async def test_degraded_source_with_recent_attempt_is_not_due(self, db):
        source = await insert_source(db, status="degraded", fetch_interval_seconds=3600)
        await db.execute(
            "UPDATE sources SET last_error_at = datetime('now') WHERE id = ?",
            (source["id"],),
        )
        await db.commit()
        assert await list_due_sources(db) == []

    async def test_paused_source_is_never_due(self, db):
        await insert_source(db, status="paused")
        assert await list_due_sources(db) == []


class TestPollSourceHealthIntegration:
    @respx.mock
    async def test_failed_fetch_marks_source_failure(self, db):
        source = await insert_source(db, source_url=GREENHOUSE_URL)
        respx.get(GREENHOUSE_URL).mock(return_value=httpx.Response(500))

        result = await poll_source(db, source, score_matches=False)

        assert result["error"]
        row = await get_source_row(db, source["id"])
        assert row["consecutive_error_count"] == 1
        assert row["last_error_message"]

    @respx.mock
    async def test_escalation_fires_once_on_degraded_transition(self, db, monkeypatch):
        import src.ingestion.service as ingestion_service

        escalations = []

        async def record_escalation(source, message):
            escalations.append((source["id"], message))

        monkeypatch.setattr(
            ingestion_service.alerts_service,
            "send_source_failure_alert",
            record_escalation,
        )

        source = await insert_source(db, source_url=GREENHOUSE_URL)
        respx.get(GREENHOUSE_URL).mock(return_value=httpx.Response(500))

        for _ in range(settings.source_failure_escalation_threshold + 1):
            fresh = await get_source_row(db, source["id"])
            fresh["adapter_config"] = {}
            await poll_source(db, fresh, score_matches=False)

        assert len(escalations) == 1
        assert escalations[0][0] == source["id"]
        row = await get_source_row(db, source["id"])
        assert row["status"] == "degraded"

    @respx.mock
    async def test_successful_poll_resets_health_and_stores_jobs(self, db):
        source = await insert_source(db, source_url=GREENHOUSE_URL)
        await mark_source_failure(db, source["id"], "earlier failure")

        payload = {
            "jobs": [
                {
                    "id": 1,
                    "title": "Backend Engineer",
                    "location": {"name": "Remote"},
                    "departments": [],
                    "content": "<p>Python.</p>",
                    "absolute_url": "https://boards.greenhouse.io/acme/jobs/1",
                    "updated_at": "2026-06-01T12:00:00Z",
                }
            ]
        }
        respx.get(GREENHOUSE_URL).mock(return_value=httpx.Response(200, json=payload))

        result = await poll_source(db, source, score_matches=False)

        assert result["error"] is None
        assert result["job_count"] == 1
        assert result["new_count"] == 1
        row = await get_source_row(db, source["id"])
        assert row["consecutive_error_count"] == 0
        assert row["status"] == "active"
