"""Alert creation idempotency tests."""

import asyncio

import src.alerts.service as alerts_service
from src.alerts.repository import create_alert
from src.alerts.service import send_combined_alert
from src.config import settings
from src.matching.service import rescore_backlog
from tests.test_rescore import insert_jobs, setup_profile


async def seed_match_result(db) -> str:
    """Profile + one scored job, returning its match result id."""
    await setup_profile(db)
    await insert_jobs(db, 1)
    await rescore_backlog(db)
    cursor = await db.execute("SELECT id FROM match_results LIMIT 1")
    return (await cursor.fetchone())[0]


async def seed_alert_tuples(db, count: int) -> list[tuple[dict, dict]]:
    """Seed `count` scored jobs and return (match_result, job) tuples for them."""
    await setup_profile(db)
    await insert_jobs(db, count)
    await rescore_backlog(db)
    # rescore records its own in-app alert rows; clear them so each test starts
    # from match results with no alerts yet.
    await db.execute("DELETE FROM alerts")
    await db.commit()
    cursor = await db.execute(
        """
        SELECT mr.id, mr.user_id, mr.score, mr.summary,
               jp.title, jp.company_name, jp.canonical_url
        FROM match_results mr
        JOIN job_postings jp ON jp.id = mr.job_posting_id
        """
    )
    rows = await cursor.fetchall()
    return [
        (
            {
                "id": r["id"],
                "user_id": r["user_id"],
                "score": r["score"],
                "summary": r["summary"],
            },
            {
                "title": r["title"],
                "company_name": r["company_name"],
                "canonical_url": r["canonical_url"],
            },
        )
        for r in rows
    ]


def fake_smtp(monkeypatch) -> list:
    """Configure email delivery and capture sent messages instead of sending."""
    sent: list = []

    async def _capture(message, **kwargs):
        sent.append(message)

    monkeypatch.setattr(type(settings), "smtp_configured", True)
    monkeypatch.setattr(settings, "alert_to_email", "me@example.com")
    monkeypatch.setattr(alerts_service.aiosmtplib, "send", _capture)
    return sent


class TestCombinedAlert:
    async def test_many_matches_send_exactly_one_email(self, db, monkeypatch):
        sent = fake_smtp(monkeypatch)
        alerts = await seed_alert_tuples(db, 3)

        result = await send_combined_alert(db, alerts)

        assert result == {"sent": 3, "channel": "email", "error": None}
        assert len(sent) == 1  # one email covers all three matches
        body = sent[0].get_content()
        for _, job in alerts:
            assert job["title"] in body
        cursor = await db.execute("SELECT status, channel FROM alerts")
        rows = await cursor.fetchall()
        assert len(rows) == 3
        assert all(r["status"] == "sent" and r["channel"] == "email" for r in rows)

    async def test_rerun_does_not_resend(self, db, monkeypatch):
        sent = fake_smtp(monkeypatch)
        alerts = await seed_alert_tuples(db, 2)

        first = await send_combined_alert(db, alerts)
        second = await send_combined_alert(db, alerts)

        assert first["sent"] == 2
        assert second["sent"] == 0  # already delivered — never double-notify
        assert len(sent) == 1

    async def test_empty_batch_sends_nothing(self, db, monkeypatch):
        sent = fake_smtp(monkeypatch)
        result = await send_combined_alert(db, [])
        assert result == {"sent": 0, "channel": None, "error": None}
        assert sent == []

    async def test_in_app_fallback_records_rows_without_email(self, db, monkeypatch):
        alerts = await seed_alert_tuples(db, 2)

        result = await send_combined_alert(db, alerts, force_channel="in_app")

        assert result["sent"] == 2
        assert result["channel"] == "in_app"
        cursor = await db.execute(
            "SELECT COUNT(*) FROM alerts WHERE channel = 'in_app' AND status = 'sent'"
        )
        assert (await cursor.fetchone())[0] == 2


class TestCreateAlertIdempotency:
    async def test_same_key_returns_existing_alert(self, db):
        match_id = await seed_match_result(db)
        first = await create_alert(
            db,
            user_id="default",
            match_result_id=match_id,
            channel="in_app",
            idempotency_key="alert-key",
        )
        second = await create_alert(
            db,
            user_id="default",
            match_result_id=match_id,
            channel="in_app",
            idempotency_key="alert-key",
        )
        assert first == second
        cursor = await db.execute(
            "SELECT COUNT(*) FROM alerts WHERE idempotency_key = 'alert-key'"
        )
        assert (await cursor.fetchone())[0] == 1

    async def test_concurrent_same_key_creates_one_alert(self, db):
        match_id = await seed_match_result(db)
        ids = await asyncio.gather(
            *[
                create_alert(
                    db,
                    user_id="default",
                    match_result_id=match_id,
                    channel="in_app",
                    idempotency_key="alert-key",
                )
                for _ in range(5)
            ]
        )
        assert len(set(ids)) == 1
        cursor = await db.execute(
            "SELECT COUNT(*) FROM alerts WHERE idempotency_key = 'alert-key'"
        )
        assert (await cursor.fetchone())[0] == 1

    async def test_distinct_keys_create_distinct_alerts(self, db):
        match_id = await seed_match_result(db)
        first = await create_alert(
            db,
            user_id="default",
            match_result_id=match_id,
            channel="in_app",
            idempotency_key="alert-key-1",
        )
        second = await create_alert(
            db,
            user_id="default",
            match_result_id=match_id,
            channel="email",
            idempotency_key="alert-key-2",
        )
        assert first != second
