"""Job posting repository and deduplication logic."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import aiosqlite
import structlog

from src.ingestion.models import RawJob

logger = structlog.get_logger()

TRACKING_QUERY_PREFIXES = ("utm_",)
TRACKING_QUERY_KEYS = {"gh_jid", "lever-source", "source", "ref", "referrer"}


def _json_dumps(value: Any) -> str:
    return json.dumps(value if value is not None else [])


def _json_loads(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, (list, dict)):
        return value
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


def _normalize_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().lower())


def normalize_url(url: str | None) -> str | None:
    """Normalize a URL for dedupe while preserving the canonical path."""
    if not url:
        return None
    parts = urlsplit(url.strip())
    query_pairs = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        key_lower = key.lower()
        if key_lower in TRACKING_QUERY_KEYS:
            continue
        if any(key_lower.startswith(prefix) for prefix in TRACKING_QUERY_PREFIXES):
            continue
        query_pairs.append((key, value))
    query = urlencode(query_pairs)
    path = parts.path.rstrip("/") or parts.path
    return urlunsplit(
        (
            parts.scheme.lower() or "https",
            parts.netloc.lower(),
            path,
            query,
            "",
        )
    )


def hash_value(value: str | None) -> str | None:
    """Return a sha256 hash for a non-empty string."""
    if not value:
        return None
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def content_hash(job: RawJob) -> str:
    """Build a stable hash for meaningful job content."""
    content = "|".join(
        [
            _normalize_text(job.title),
            _normalize_text(job.company_name),
            _normalize_text(" ".join(job.locations or [])),
            _normalize_text(job.description_text),
        ]
    )
    return hash_value(content) or ""


def semantic_key(job: RawJob) -> str:
    """Build a semantic dedupe key when provider IDs are missing."""
    return "|".join(
        [
            _normalize_text(job.company_name),
            _normalize_text(job.title),
            _normalize_text(" ".join(job.locations or [])),
        ]
    )


def _deserialize_job_row(row: aiosqlite.Row) -> dict:
    data = dict(row)
    for field in ("locations", "raw_payload", "extracted_requirements"):
        data[field] = _json_loads(data.get(field), [] if field == "locations" else None)
    return data


async def get_job(db: aiosqlite.Connection, job_id: str) -> dict | None:
    """Fetch one job posting."""
    cursor = await db.execute("SELECT * FROM job_postings WHERE id = ?", (job_id,))
    row = await cursor.fetchone()
    return _deserialize_job_row(row) if row else None


async def find_existing_job(
    db: aiosqlite.Connection,
    provider: str,
    provider_job_id: str | None,
    canonical_url: str | None,
    semantic: str,
) -> dict | None:
    """Find an existing posting using layered dedupe keys."""
    if provider_job_id:
        cursor = await db.execute(
            """
            SELECT *
            FROM job_postings
            WHERE provider = ? AND provider_job_id = ?
            LIMIT 1
            """,
            (provider, provider_job_id),
        )
        row = await cursor.fetchone()
        if row:
            return _deserialize_job_row(row)

    if canonical_url:
        cursor = await db.execute(
            """
            SELECT *
            FROM job_postings
            WHERE canonical_url = ?
            LIMIT 1
            """,
            (canonical_url,),
        )
        row = await cursor.fetchone()
        if row:
            return _deserialize_job_row(row)

    cursor = await db.execute(
        """
        SELECT jp.*
        FROM job_fingerprints fp
        JOIN job_postings jp ON jp.id = fp.job_posting_id
        WHERE fp.kind = 'semantic_key' AND fp.value = ?
        LIMIT 1
        """,
        (hash_value(semantic),),
    )
    row = await cursor.fetchone()
    return _deserialize_job_row(row) if row else None


async def _insert_fingerprints(
    db: aiosqlite.Connection,
    job_id: str,
    *,
    provider: str,
    provider_job_id: str | None,
    canonical_url: str | None,
    semantic: str,
    content: str,
) -> None:
    fingerprints: list[tuple[str, str]] = []
    if provider_job_id:
        fingerprints.append(("external_key", f"{provider}:{provider_job_id}"))
    if canonical_url:
        fingerprints.append(("canonical_url_hash", hash_value(canonical_url) or canonical_url))
    fingerprints.append(("semantic_key", hash_value(semantic) or semantic))
    fingerprints.append(("content_hash", content))

    for kind, value in fingerprints:
        await db.execute(
            """
            INSERT OR IGNORE INTO job_fingerprints (job_posting_id, kind, value)
            VALUES (?, ?, ?)
            """,
            (job_id, kind, value),
        )


async def upsert_raw_job(
    db: aiosqlite.Connection,
    source: dict,
    raw_job: RawJob,
) -> tuple[str, bool, bool]:
    """Insert or update a normalized job.

    Returns:
        (job_id, is_new, content_changed)
    """
    provider = source.get("provider") or "custom"
    raw_job = raw_job.model_copy(
        update={
            "title": raw_job.title.strip(),
            "company_name": raw_job.company_name.strip(),
        }
    )
    provider_job_id = raw_job.provider_job_id or None
    canonical_url = normalize_url(raw_job.url)
    semantic = semantic_key(raw_job)
    content = content_hash(raw_job)
    existing = await find_existing_job(
        db,
        provider,
        provider_job_id,
        canonical_url,
        semantic,
    )

    if existing:
        content_changed = existing.get("content_hash") != content
        if not content_changed:
            # Re-seeing an unchanged job only proves it is still open: bump
            # last_seen_at, leave updated_at and the content fields alone so
            # the posting's timestamps reflect real changes, not poll cycles.
            await db.execute(
                """
                UPDATE job_postings
                SET last_seen_at = CURRENT_TIMESTAMP,
                    status = 'active'
                WHERE id = ?
                """,
                (existing["id"],),
            )
            await db.commit()
            return existing["id"], False, False
        await db.execute(
            """
            UPDATE job_postings
            SET source_id = ?,
                company_name = ?,
                title = ?,
                canonical_url = COALESCE(?, canonical_url),
                locations = ?,
                remote_policy = ?,
                employment_type = ?,
                department = ?,
                description_text = ?,
                description_html = ?,
                salary_min = ?,
                salary_max = ?,
                salary_currency = ?,
                visa_sponsorship = ?,
                posted_at = ?,
                provider_updated_at = ?,
                last_seen_at = CURRENT_TIMESTAMP,
                content_hash = ?,
                raw_payload = ?,
                status = 'active',
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                source["id"],
                raw_job.company_name,
                raw_job.title,
                canonical_url,
                _json_dumps(raw_job.locations),
                raw_job.remote_policy,
                raw_job.employment_type,
                raw_job.department,
                raw_job.description_text,
                raw_job.description_html,
                raw_job.salary_min,
                raw_job.salary_max,
                raw_job.salary_currency,
                raw_job.visa_sponsorship,
                raw_job.posted_at,
                raw_job.provider_updated_at,
                content,
                _json_dumps(raw_job.raw_data),
                existing["id"],
            ),
        )
        await _insert_fingerprints(
            db,
            existing["id"],
            provider=provider,
            provider_job_id=provider_job_id,
            canonical_url=canonical_url,
            semantic=semantic,
            content=content,
        )
        await db.commit()
        return existing["id"], False, content_changed

    job_id = uuid.uuid4().hex
    await db.execute(
        """
        INSERT INTO job_postings (
            id, source_id, provider, provider_job_id, company_name, title,
            canonical_url, locations, remote_policy, employment_type,
            department, description_text, description_html,
            salary_min, salary_max, salary_currency, visa_sponsorship,
            posted_at, provider_updated_at, content_hash, raw_payload
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            job_id,
            source["id"],
            provider,
            provider_job_id,
            raw_job.company_name,
            raw_job.title,
            canonical_url,
            _json_dumps(raw_job.locations),
            raw_job.remote_policy,
            raw_job.employment_type,
            raw_job.department,
            raw_job.description_text,
            raw_job.description_html,
            raw_job.salary_min,
            raw_job.salary_max,
            raw_job.salary_currency,
            raw_job.visa_sponsorship,
            raw_job.posted_at,
            raw_job.provider_updated_at,
            content,
            _json_dumps(raw_job.raw_data),
        ),
    )
    await _insert_fingerprints(
        db,
        job_id,
        provider=provider,
        provider_job_id=provider_job_id,
        canonical_url=canonical_url,
        semantic=semantic,
        content=content,
    )
    await db.commit()
    logger.info("job.created", job_id=job_id, title=raw_job.title)
    return job_id, True, True


async def update_extracted_requirements(
    db: aiosqlite.Connection,
    job_id: str,
    requirements: dict,
) -> None:
    """Cache extracted requirements on a job posting."""
    await db.execute(
        """
        UPDATE job_postings
        SET extracted_requirements = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (json.dumps(requirements), job_id),
    )
    await db.commit()


def _like_pattern(query: str) -> str:
    """Build a LIKE pattern with wildcards in the user input escaped."""
    escaped = (
        query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    )
    return f"%{escaped}%"


# Whitelisted ORDER BY clauses — sort values map here, never into raw SQL.
JOB_SORT_ORDERS: dict[str, str] = {
    "newest": "first_seen_at DESC",
    "oldest": "first_seen_at ASC",
    "posted": "posted_at IS NULL, posted_at DESC",
    # TRIM with an explicit char set: tabs/newlines too, not just spaces.
    "title": (
        "TRIM(title, ' ' || char(9) || char(10) || char(13)) "
        "COLLATE NOCASE ASC, first_seen_at DESC"
    ),
    "company": (
        "TRIM(company_name, ' ' || char(9) || char(10) || char(13)) "
        "COLLATE NOCASE ASC, first_seen_at DESC"
    ),
}


async def list_jobs(
    db: aiosqlite.Connection,
    *,
    source_id: str | None = None,
    q: str | None = None,
    remote_policy: str | None = None,
    sort: str = "newest",
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    """List normalized jobs, optionally filtered and sorted."""
    conditions: list[str] = []
    params: list[Any] = []

    if source_id:
        conditions.append("source_id = ?")
        params.append(source_id)
    if q:
        conditions.append(
            "(title LIKE ? ESCAPE '\\' OR company_name LIKE ? ESCAPE '\\')"
        )
        pattern = _like_pattern(q)
        params.extend([pattern, pattern])
    if remote_policy:
        conditions.append("remote_policy = ?")
        params.append(remote_policy)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    order = JOB_SORT_ORDERS.get(sort, JOB_SORT_ORDERS["newest"])
    cursor = await db.execute(
        f"""
        SELECT job_postings.*, mr.score AS match_score, mr.decision AS match_decision
        FROM job_postings
        LEFT JOIN match_results mr ON mr.id = (
            SELECT id FROM match_results
            WHERE job_posting_id = job_postings.id
            ORDER BY created_at DESC
            LIMIT 1
        )
        {where}
        ORDER BY {order}
        LIMIT ? OFFSET ?
        """,
        (*params, limit, offset),
    )
    rows = await cursor.fetchall()
    return [_deserialize_job_row(row) for row in rows]


async def list_latest_user_actions(
    db: aiosqlite.Connection,
    user_id: str,
) -> list[dict]:
    """Return each job's most recent user action, joined with job details."""
    cursor = await db.execute(
        """
        SELECT a.id, a.user_id, a.job_posting_id, a.action, a.feedback,
               a.created_at,
               j.title AS job_title, j.company_name, j.canonical_url,
               j.locations, j.remote_policy,
               j.salary_min, j.salary_max, j.salary_currency
        FROM user_job_actions a
        JOIN job_postings j ON j.id = a.job_posting_id
        WHERE a.user_id = ?
          AND a.id = (
              SELECT a2.id FROM user_job_actions a2
              WHERE a2.user_id = a.user_id
                AND a2.job_posting_id = a.job_posting_id
              ORDER BY a2.created_at DESC, a2.rowid DESC
              LIMIT 1
          )
        ORDER BY a.created_at DESC
        """,
        (user_id,),
    )
    rows = await cursor.fetchall()
    results = []
    for row in rows:
        item = dict(row)
        item["locations"] = _json_loads(item.get("locations"), [])
        results.append(item)
    return results


async def create_user_action(
    db: aiosqlite.Connection,
    user_id: str,
    job_id: str,
    action: str,
    feedback: str | None,
) -> dict:
    """Create a user action for a job."""
    action_id = uuid.uuid4().hex
    await db.execute(
        """
        INSERT INTO user_job_actions (id, user_id, job_posting_id, action, feedback)
        VALUES (?, ?, ?, ?, ?)
        """,
        (action_id, user_id, job_id, action, feedback),
    )
    await db.commit()
    cursor = await db.execute(
        "SELECT * FROM user_job_actions WHERE id = ?",
        (action_id,),
    )
    row = await cursor.fetchone()
    return dict(row)
