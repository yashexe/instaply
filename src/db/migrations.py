"""
Simple SQL migration runner.

Reads numbered .sql files from src/db/sql/ and applies them in order.
Tracks applied migrations in a _migrations table.
"""

import os
from pathlib import Path

import aiosqlite
import structlog

logger = structlog.get_logger()

MIGRATIONS_DIR = Path(__file__).parent / "sql"


async def run_migrations(db: aiosqlite.Connection) -> None:
    """Run all pending migrations in order."""

    # Create migrations tracking table
    await db.execute("""
        CREATE TABLE IF NOT EXISTS _migrations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT NOT NULL UNIQUE,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    await db.commit()

    # Get already-applied migrations
    cursor = await db.execute("SELECT filename FROM _migrations ORDER BY filename")
    applied = {row[0] for row in await cursor.fetchall()}

    # Find all .sql files in the migrations directory
    if not MIGRATIONS_DIR.exists():
        logger.warning("migrations.dir_not_found", path=str(MIGRATIONS_DIR))
        return

    migration_files = sorted(
        f for f in os.listdir(MIGRATIONS_DIR)
        if f.endswith(".sql") and f not in applied
    )

    if not migration_files:
        logger.info("migrations.up_to_date")
        return

    for filename in migration_files:
        filepath = MIGRATIONS_DIR / filename
        sql = filepath.read_text(encoding="utf-8")

        logger.info("migrations.applying", filename=filename)

        # Execute the migration (may contain multiple statements)
        await db.executescript(sql)

        # Record that it was applied
        await db.execute(
            "INSERT INTO _migrations (filename) VALUES (?)",
            (filename,),
        )
        await db.commit()

        logger.info("migrations.applied", filename=filename)

    logger.info("migrations.complete", applied_count=len(migration_files))
