"""
Async SQLite connection management.

Provides a singleton connection with WAL mode and foreign keys enabled.
FastAPI routes use get_db() as a dependency.
"""

import aiosqlite
import structlog
from pathlib import Path

from src.config import settings

logger = structlog.get_logger()

_db: aiosqlite.Connection | None = None


async def init_db() -> aiosqlite.Connection:
    """Initialize the database connection. Called once at app startup."""
    global _db

    db_path = Path(settings.database_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    _db = await aiosqlite.connect(str(db_path))
    _db.row_factory = aiosqlite.Row

    # Enable WAL mode for better concurrent read performance
    await _db.execute("PRAGMA journal_mode=WAL")
    # Enable foreign key enforcement
    await _db.execute("PRAGMA foreign_keys=ON")
    # Improve write performance
    await _db.execute("PRAGMA synchronous=NORMAL")

    await _db.commit()

    logger.info("database.connected", path=str(db_path))
    return _db


async def close_db() -> None:
    """Close the database connection. Called at app shutdown."""
    global _db
    if _db is not None:
        await _db.close()
        _db = None
        logger.info("database.closed")


async def get_db() -> aiosqlite.Connection:
    """FastAPI dependency — returns the active database connection."""
    if _db is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    return _db
