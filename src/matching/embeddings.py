"""
Local embedding support for semantic matching.

Embeds the candidate profile and job postings with a local
sentence-transformers model and caches the vectors on their database rows
(invalidated when the model name changes). Everything degrades gracefully:
if the library or model is unavailable the rest of the pipeline behaves as
if the semantic dimension were unknown.

Embedding models truncate long inputs, so instead of feeding whole
documents we compose short, signal-dense texts (title, skills, roles,
domains, a description excerpt) for both sides of the comparison.
"""

from __future__ import annotations

import json
from typing import Any

import aiosqlite
import structlog

from src.config import settings

logger = structlog.get_logger()

_model = None
_model_failed = False
# Profile vectors are reused across thousands of jobs in one run.
_profile_cache: dict[tuple[str, str], Any] = {}


def _json_loads_safe(value: Any, default: Any = None) -> Any:
    if value is None:
        return default
    if isinstance(value, (list, dict)):
        return value
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return default


def is_available() -> bool:
    """Whether semantic embeddings can be computed in this environment."""
    if not settings.embeddings_enabled or _model_failed:
        return False
    try:
        import sentence_transformers  # noqa: F401
    except ImportError:
        return False
    return True


def _get_model():
    """Load the sentence-transformers model once, on first use."""
    global _model, _model_failed
    if _model is not None:
        return _model
    try:
        from sentence_transformers import SentenceTransformer

        logger.info("embeddings.loading_model", model=settings.embedding_model_name)
        _model = SentenceTransformer(settings.embedding_model_name)
        return _model
    except Exception:
        # Model download/load failure (e.g. offline first run) — disable for
        # this process rather than failing every score.
        _model_failed = True
        logger.exception("embeddings.model_load_failed")
        return None


def _encode(text: str) -> bytes | None:
    """Encode text to normalized float32 vector bytes."""
    model = _get_model()
    if model is None or not text.strip():
        return None
    vector = model.encode(text, normalize_embeddings=True)
    return vector.astype("float32").tobytes()


def cosine_similarity(a: bytes, b: bytes) -> float:
    """Cosine similarity between two stored (normalized) vectors."""
    import numpy as np

    va = np.frombuffer(a, dtype="float32")
    vb = np.frombuffer(b, dtype="float32")
    if va.shape != vb.shape or not va.size:
        return 0.0
    return float(va @ vb)


def job_embedding_text(job: dict) -> str:
    """Compose a short, signal-dense text for a job posting."""
    extracted = _json_loads_safe(job.get("extracted_requirements"), {}) or {}
    skills = (extracted.get("required_skills") or []) + (
        extracted.get("preferred_skills") or []
    )
    pieces = [
        job.get("title") or "",
        job.get("department") or "",
        ", ".join(str(s) for s in skills),
        ", ".join(str(s) for s in extracted.get("domain_signals") or []),
        (job.get("description_text") or "")[:1200],
    ]
    return ". ".join(piece for piece in pieces if piece)


def profile_embedding_text(profile: dict) -> str:
    """Compose a short, signal-dense text for the candidate profile."""
    data = _json_loads_safe(profile.get("structured_profile"), {}) or {}
    roles = [
        r.get("title") if isinstance(r, dict) else str(r)
        for r in data.get("roles") or []
    ]
    skills = [
        s.get("name") if isinstance(s, dict) else str(s)
        for s in data.get("skills") or []
    ]
    years = data.get("years_of_experience")
    pieces = [
        ", ".join(str(r) for r in roles if r),
        ", ".join(str(s) for s in skills if s),
        ", ".join(str(d) for d in data.get("domains") or []),
        f"{years} years of experience" if years else "",
        (profile.get("resume_text") or "")[:1200],
    ]
    return ". ".join(piece for piece in pieces if piece)


async def ensure_job_embedding(
    db: aiosqlite.Connection, job: dict,
) -> bytes | None:
    """Return the job's embedding, computing and caching it if needed."""
    if job.get("embedding") and job.get("embedding_model") == settings.embedding_model_name:
        return job["embedding"]

    vector = _encode(job_embedding_text(job))
    if vector is None:
        return None
    await db.execute(
        "UPDATE job_postings SET embedding = ?, embedding_model = ? WHERE id = ?",
        (vector, settings.embedding_model_name, job["id"]),
    )
    await db.commit()
    return vector


async def ensure_profile_embedding(
    db: aiosqlite.Connection, profile: dict,
) -> bytes | None:
    """Return the profile's embedding, computing and caching it if needed."""
    cache_key = (profile["id"], settings.embedding_model_name)
    cached = _profile_cache.get(cache_key)
    if cached is not None:
        return cached

    cursor = await db.execute(
        "SELECT embedding, embedding_model FROM candidate_profiles WHERE id = ?",
        (profile["id"],),
    )
    row = await cursor.fetchone()
    if row and row[0] and row[1] == settings.embedding_model_name:
        _profile_cache[cache_key] = row[0]
        return row[0]

    vector = _encode(profile_embedding_text(profile))
    if vector is None:
        return None
    await db.execute(
        "UPDATE candidate_profiles SET embedding = ?, embedding_model = ? WHERE id = ?",
        (vector, settings.embedding_model_name, profile["id"]),
    )
    await db.commit()
    _profile_cache[cache_key] = vector
    return vector


async def semantic_similarity_for(
    db: aiosqlite.Connection, job: dict, profile: dict,
) -> float | None:
    """Cosine similarity between a job and the profile, or None if unavailable."""
    if not is_available():
        return None
    try:
        job_vec = await ensure_job_embedding(db, job)
        profile_vec = await ensure_profile_embedding(db, profile)
    except Exception:
        logger.exception("embeddings.similarity_failed", job_id=job.get("id"))
        return None
    if job_vec is None or profile_vec is None:
        return None
    return cosine_similarity(job_vec, profile_vec)
