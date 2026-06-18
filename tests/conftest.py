"""Shared test fixtures: in-memory database and source factory."""

import uuid

import aiosqlite
import pytest

from src.db.migrations import run_migrations


@pytest.fixture(autouse=True)
def no_embedding_model(monkeypatch):
    """Keep tests offline: never load the sentence-transformers model.

    Tests that exercise embeddings re-enable behavior by monkeypatching
    the functions they need.
    """
    monkeypatch.setattr("src.matching.embeddings.is_available", lambda: False)


@pytest.fixture
async def db():
    """In-memory SQLite database with the full schema applied."""
    conn = await aiosqlite.connect(":memory:")
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA foreign_keys=ON")
    await run_migrations(conn)
    yield conn
    await conn.close()


async def insert_source(
    db: aiosqlite.Connection,
    *,
    provider: str = "greenhouse",
    company_name: str = "Acme",
    source_url: str = "https://boards-api.greenhouse.io/v1/boards/acme/jobs?content=true",
    status: str = "active",
    fetch_interval_seconds: int = 300,
    user_id: str = "default",
) -> dict:
    """Insert a source row and return it as a dict."""
    source_id = uuid.uuid4().hex
    await db.execute(
        """
        INSERT INTO sources (
            id, user_id, company_name, provider, source_url, normalized_url,
            priority, status, fetch_interval_seconds, adapter_config
        ) VALUES (?, ?, ?, ?, ?, ?, 'normal', ?, ?, '{}')
        """,
        (
            source_id,
            user_id,
            company_name,
            provider,
            source_url,
            source_url,
            status,
            fetch_interval_seconds,
        ),
    )
    await db.commit()
    cursor = await db.execute("SELECT * FROM sources WHERE id = ?", (source_id,))
    row = await cursor.fetchone()
    data = dict(row)
    data["adapter_config"] = {}
    return data
