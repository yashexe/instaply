"""Embedding cache and similarity tests — no model loads, encoder is faked."""

import json

import numpy as np

from src.matching import embeddings
from src.matching.service import rescore_backlog
from tests.test_rescore import insert_jobs, setup_profile


def _vec_bytes(values) -> bytes:
    v = np.array(values, dtype="float32")
    v = v / np.linalg.norm(v)
    return v.tobytes()


class TestCosineSimilarity:
    def test_identical_vectors(self):
        a = _vec_bytes([1, 2, 3])
        assert abs(embeddings.cosine_similarity(a, a) - 1.0) < 1e-6

    def test_orthogonal_vectors(self):
        a = _vec_bytes([1, 0])
        b = _vec_bytes([0, 1])
        assert abs(embeddings.cosine_similarity(a, b)) < 1e-6

    def test_mismatched_shapes_return_zero(self):
        assert embeddings.cosine_similarity(_vec_bytes([1, 0]), _vec_bytes([1, 0, 0])) == 0.0


class TestEmbeddingTexts:
    def test_job_text_includes_title_and_skills(self):
        job = {
            "title": "Backend Engineer",
            "department": "Platform",
            "description_text": "Build APIs.",
            "extracted_requirements": json.dumps(
                {"required_skills": ["Python"], "preferred_skills": ["AWS"],
                 "domain_signals": ["fintech"]}
            ),
        }
        text = embeddings.job_embedding_text(job)
        for fragment in ("Backend Engineer", "Platform", "Python", "AWS", "fintech", "Build APIs."):
            assert fragment in text

    def test_profile_text_includes_roles_skills_domains(self):
        profile = {
            "resume_text": "Did backend things.",
            "structured_profile": {
                "roles": ["Backend Engineer"],
                "skills": [{"name": "Python"}],
                "domains": ["fintech"],
                "years_of_experience": 7,
            },
        }
        text = embeddings.profile_embedding_text(profile)
        for fragment in ("Backend Engineer", "Python", "fintech", "7 years", "Did backend things."):
            assert fragment in text


class TestEmbeddingCache:
    async def test_job_embedding_computed_and_cached(self, db, monkeypatch):
        await setup_profile(db)
        (job_id,) = await insert_jobs(db, 1)
        calls = []

        def fake_encode(text):
            calls.append(text)
            return _vec_bytes([1, 2, 3])

        monkeypatch.setattr(embeddings, "_encode", fake_encode)

        cursor = await db.execute("SELECT * FROM job_postings WHERE id = ?", (job_id,))
        job = dict(await cursor.fetchone())

        vector = await embeddings.ensure_job_embedding(db, job)
        assert vector == _vec_bytes([1, 2, 3])
        assert len(calls) == 1

        # Cached on the row: a fresh read skips the encoder
        cursor = await db.execute("SELECT * FROM job_postings WHERE id = ?", (job_id,))
        job = dict(await cursor.fetchone())
        assert job["embedding"] == vector
        await embeddings.ensure_job_embedding(db, job)
        assert len(calls) == 1

    async def test_model_change_invalidates_cache(self, db, monkeypatch):
        await setup_profile(db)
        (job_id,) = await insert_jobs(db, 1)
        monkeypatch.setattr(embeddings, "_encode", lambda text: _vec_bytes([1, 2, 3]))

        cursor = await db.execute("SELECT * FROM job_postings WHERE id = ?", (job_id,))
        job = dict(await cursor.fetchone())
        job["embedding"] = _vec_bytes([9, 9, 9])
        job["embedding_model"] = "some-older-model"

        vector = await embeddings.ensure_job_embedding(db, job)
        assert vector == _vec_bytes([1, 2, 3])

    async def test_similarity_unavailable_returns_none(self, db):
        # conftest disables is_available
        assert await embeddings.semantic_similarity_for(db, {}, {}) is None


class TestSemanticScoringIntegration:
    async def test_rescore_uses_semantic_similarity(self, db, monkeypatch):
        await setup_profile(db)
        await insert_jobs(db, 1)

        monkeypatch.setattr(embeddings, "is_available", lambda: True)
        monkeypatch.setattr(embeddings, "_encode", lambda text: _vec_bytes([1, 2, 3]))
        # Profile cache may hold entries from other tests
        embeddings._profile_cache.clear()

        await rescore_backlog(db)

        cursor = await db.execute("SELECT score_breakdown, trace FROM match_results")
        row = await cursor.fetchone()
        breakdown = json.loads(row["score_breakdown"])
        trace = json.loads(row["trace"])
        # Identical fake vectors → similarity 1.0 → full semantic weight
        assert breakdown["semantic_fit"] == 30
        assert abs(trace["semantic_similarity"] - 1.0) < 1e-6
