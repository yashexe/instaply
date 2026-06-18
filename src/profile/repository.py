"""
Profile repository — raw SQL operations against candidate_profiles.

All queries use aiosqlite with parameterised SQL.
"""

import json
import uuid

import aiosqlite
import structlog

logger = structlog.get_logger()


async def get_next_version(db: aiosqlite.Connection, user_id: str) -> int:
    """Return the next version number for this user's profile.

    If no profiles exist yet, returns 1.
    """
    cursor = await db.execute(
        "SELECT COALESCE(MAX(version), 0) + 1 FROM candidate_profiles WHERE user_id = ?",
        (user_id,),
    )
    row = await cursor.fetchone()
    return row[0] if row else 1


async def create_profile(
    db: aiosqlite.Connection,
    user_id: str,
    resume_text: str,
    structured_profile_json: str,
    version: int,
) -> str:
    """Insert a new profile version and deactivate previous versions.

    Args:
        db: Active database connection.
        user_id: The user who owns this profile.
        resume_text: Raw resume text.
        structured_profile_json: JSON-serialized StructuredProfile.
        version: Version number for this profile.

    Returns:
        The new profile's ID.
    """
    profile_id = uuid.uuid4().hex

    # Deactivate all previous versions for this user
    await db.execute(
        "UPDATE candidate_profiles SET is_active = 0 WHERE user_id = ? AND is_active = 1",
        (user_id,),
    )

    # Insert the new profile
    await db.execute(
        """
        INSERT INTO candidate_profiles (id, user_id, version, resume_text, structured_profile, is_active)
        VALUES (?, ?, ?, ?, ?, 1)
        """,
        (profile_id, user_id, version, resume_text, structured_profile_json),
    )

    await db.commit()

    logger.info(
        "profile.created",
        profile_id=profile_id,
        user_id=user_id,
        version=version,
    )

    return profile_id


async def get_active_profile(
    db: aiosqlite.Connection, user_id: str
) -> dict | None:
    """Get the currently active profile for a user.

    Returns:
        A dict with profile data, or None if no active profile exists.
    """
    cursor = await db.execute(
        """
        SELECT id, user_id, version, resume_text, structured_profile, is_active, created_at
        FROM candidate_profiles
        WHERE user_id = ? AND is_active = 1
        ORDER BY version DESC
        LIMIT 1
        """,
        (user_id,),
    )
    row = await cursor.fetchone()
    if row is None:
        return None

    return {
        "id": row[0],
        "user_id": row[1],
        "version": row[2],
        "resume_text": row[3],
        "structured_profile": json.loads(row[4]) if row[4] else None,
        "is_active": bool(row[5]),
        "created_at": row[6],
    }


async def get_profile_versions(
    db: aiosqlite.Connection, user_id: str
) -> list[dict]:
    """List all profile versions for a user, newest first.

    Returns:
        A list of dicts with profile data.
    """
    cursor = await db.execute(
        """
        SELECT id, user_id, version, resume_text, structured_profile, is_active, created_at
        FROM candidate_profiles
        WHERE user_id = ?
        ORDER BY version DESC
        """,
        (user_id,),
    )
    rows = await cursor.fetchall()

    return [
        {
            "id": row[0],
            "user_id": row[1],
            "version": row[2],
            "resume_text": row[3],
            "structured_profile": json.loads(row[4]) if row[4] else None,
            "is_active": bool(row[5]),
            "created_at": row[6],
        }
        for row in rows
    ]
