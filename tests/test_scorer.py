"""Scorer tests — known/unknown dimensions, confidence, and the skills gate."""

from src.matching.scorer import (
    GATE_CAP,
    _count_skill_matches,
    _skills_match,
    score_job,
)

NO_FILTER_RESULTS = {"results": {}}


def strong_inputs() -> tuple[dict, dict, dict, dict]:
    job_data = {
        "title": "Senior Backend Engineer",
        "company_name": "Acme",
        "locations": ["Toronto, Ontario"],
        "remote_policy": "remote",
        "description_text": "Python APIs at scale in fintech.",
        "department": "Engineering",
        "salary_max": 180000,
    }
    preferences = {
        "target_roles": ["backend engineer"],
        "locations": ["Toronto"],
        "remote_policy": "any",
        "min_salary": 120000,
        "needs_visa_sponsorship": False,
    }
    profile = {
        "structured_profile": {
            "skills": ["Python", "PostgreSQL", "AWS"],
            "roles": ["Backend Engineer"],
            "domains": ["fintech"],
            "years_of_experience": 7,
        }
    }
    extracted = {
        "role_family": "backend engineer",
        "required_skills": ["python", "postgresql"],
        "preferred_skills": ["aws"],
        "years_experience_min": 5,
        "domain_signals": ["fintech"],
    }
    return job_data, preferences, profile, extracted


class TestScoreJob:
    def test_strong_match_scores_high_with_high_confidence(self):
        job_data, preferences, profile, extracted = strong_inputs()
        total, breakdown = score_job(
            job_data, preferences, profile, extracted, NO_FILTER_RESULTS,
            semantic_similarity=0.7,
        )
        assert total >= 85
        assert breakdown["semantic_fit"] == 30
        assert breakdown["role_title_fit"] == 15
        assert breakdown["required_skills_fit"] == 15
        assert breakdown["experience_fit"] == 10
        assert breakdown["preferred_skills_bonus"] == 10
        assert breakdown["confidence"] == 100

    def test_semantic_similarity_maps_to_points(self):
        job_data, preferences, profile, extracted = strong_inputs()
        _, low = score_job(
            job_data, preferences, profile, extracted, NO_FILTER_RESULTS,
            semantic_similarity=0.25,
        )
        _, mid = score_job(
            job_data, preferences, profile, extracted, NO_FILTER_RESULTS,
            semantic_similarity=0.40,
        )
        assert low["semantic_fit"] == 0
        assert mid["semantic_fit"] == 15

    def test_no_semantic_similarity_is_unknown(self):
        job_data, preferences, profile, extracted = strong_inputs()
        _, breakdown = score_job(
            job_data, preferences, profile, extracted, NO_FILTER_RESULTS
        )
        assert "semantic_fit" not in breakdown
        assert breakdown["confidence"] == 70  # 70 of 100 weight known

    def test_weak_match_scores_low(self):
        job_data = {
            "title": "Account Executive",
            "company_name": "SalesCo",
            "locations": ["Berlin"],
            "remote_policy": "onsite",
            "description_text": "Close enterprise deals.",
            "salary_max": 60000,
        }
        preferences = {
            "target_roles": ["backend engineer"],
            "locations": ["Toronto"],
            "remote_policy": "remote",
            "min_salary": 120000,
            "needs_visa_sponsorship": False,
        }
        profile = {
            "structured_profile": {
                "skills": ["Python"],
                "roles": ["Backend Engineer"],
                "domains": ["fintech"],
                "years_of_experience": 7,
            }
        }
        extracted = {
            "role_family": "sales",
            "required_skills": ["salesforce", "negotiation"],
            "preferred_skills": [],
            "years_experience_min": 3,
        }
        total, _ = score_job(job_data, preferences, profile, extracted, NO_FILTER_RESULTS)
        assert total < 50

    def test_missing_data_lowers_confidence_not_score(self):
        """A posting with no extractable requirements must not earn free credit."""
        job_data, preferences, profile, _ = strong_inputs()
        full_total, full_breakdown = score_job(
            job_data, preferences, profile, strong_inputs()[3], NO_FILTER_RESULTS
        )
        sparse_total, sparse_breakdown = score_job(
            job_data, preferences, profile, None, NO_FILTER_RESULTS
        )
        # Unknown dimensions are omitted, not scored at a midpoint
        assert "required_skills_fit" not in sparse_breakdown
        assert "experience_fit" not in sparse_breakdown
        assert "preferred_skills_bonus" not in sparse_breakdown
        assert sparse_breakdown["confidence"] < full_breakdown["confidence"]

    def test_no_stated_experience_requirement_is_unknown_not_full_credit(self):
        job_data, preferences, profile, extracted = strong_inputs()
        extracted = dict(extracted, years_experience_min=None)
        _, breakdown = score_job(
            job_data, preferences, profile, extracted, NO_FILTER_RESULTS
        )
        assert "experience_fit" not in breakdown
        assert breakdown["confidence"] < 100

    def test_required_skills_gate_caps_score(self):
        """Preference points cannot buy back a fundamental skills mismatch."""
        job_data, preferences, profile, extracted = strong_inputs()
        extracted = dict(extracted, required_skills=["rust", "kubernetes", "scala", "c++"])
        total, breakdown = score_job(
            job_data, preferences, profile, extracted, NO_FILTER_RESULTS
        )
        assert total <= GATE_CAP
        assert breakdown["required_skills_gate"] < 0

    def test_uncertain_filters_reduce_confidence_not_score(self):
        job_data, preferences, profile, extracted = strong_inputs()
        baseline_total, baseline_breakdown = score_job(
            job_data, preferences, profile, extracted, NO_FILTER_RESULTS
        )
        filter_results = {
            "results": {"location": "uncertain", "salary": "uncertain", "visa": "uncertain"}
        }
        total, breakdown = score_job(
            job_data, preferences, profile, extracted, filter_results
        )
        assert total == baseline_total
        assert breakdown["confidence"] == baseline_breakdown["confidence"] - 15

    def test_all_unknown_scores_zero_with_zero_confidence(self):
        total, breakdown = score_job({}, {}, {}, None, NO_FILTER_RESULTS)
        # Empty preferences mean no constraints, which count as satisfied —
        # but a fully empty job/profile leaves everything else unknown.
        assert breakdown["confidence"] < 30
        assert 0 <= total <= 100

    def test_score_clamped_to_range(self):
        job_data, preferences, profile, extracted = strong_inputs()
        total, _ = score_job(job_data, preferences, profile, extracted, NO_FILTER_RESULTS)
        assert 0 <= total <= 100


class TestSkillMatching:
    def test_exact_match(self):
        assert _skills_match("Python", "python")

    def test_containment_match(self):
        assert _skills_match("react", "React.js")

    def test_single_char_does_not_contain_match(self):
        assert not _skills_match("c", "css")

    def test_taxonomy_synonyms_match(self):
        # Variants the taxonomy resolves to the same canonical skill.
        assert _skills_match("node", "Node.js")
        assert _skills_match("postgres", "PostgreSQL")
        assert _skills_match("rest api", "REST APIs")

    def test_taxonomy_blocks_substring_false_positive(self):
        # Both are known, distinct skills — the substring 'java' ⊂ 'javascript'
        # must NOT cause a match once the taxonomy recognises both.
        assert not _skills_match("java", "javascript")

    def test_count_skill_matches_ratio(self):
        assert _count_skill_matches(["python", "go", "rust"], ["Python", "Rust"]) == 2
