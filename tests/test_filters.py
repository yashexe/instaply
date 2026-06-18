"""Hard filter tests — good, weak/uncertain, and disqualifying cases."""

from src.matching.filters import (
    apply_hard_filters,
    excluded_keyword_filter,
    location_filter,
    role_family_filter,
    salary_filter,
    seniority_filter,
    visa_filter,
)


def job(**overrides) -> dict:
    base = {
        "title": "Senior Backend Engineer",
        "company_name": "Acme",
        "locations": ["Toronto, Ontario"],
        "remote_policy": "remote",
        "description_text": "Build APIs in Python.",
        "salary_min": 120000,
        "salary_max": 160000,
        "salary_currency": "CAD",
        "visa_sponsorship": "unknown",
    }
    base.update(overrides)
    return base


def prefs(**overrides) -> dict:
    base = {
        "target_roles": ["backend engineer"],
        "seniority_levels": ["senior"],
        "locations": ["Toronto"],
        "remote_policy": "any",
        "min_salary": 100000,
        "salary_currency": "CAD",
        "needs_visa_sponsorship": False,
        "excluded_keywords": [],
    }
    base.update(overrides)
    return base


PROFILE: dict = {}


# ── role_family_filter ─────────────────────────────────────────────────────

class TestRoleFamilyFilter:
    def test_no_target_roles_passes(self):
        assert role_family_filter(job(), prefs(target_roles=[]), PROFILE) == "pass"

    def test_exact_substring_match_passes(self):
        assert role_family_filter(job(title="Senior Backend Engineer"), prefs(), PROFILE) == "pass"

    def test_related_family_is_uncertain(self):
        result = role_family_filter(
            job(title="Full Stack Developer"),
            prefs(target_roles=["software engineer"]),
            PROFILE,
        )
        assert result == "uncertain"

    def test_unrelated_title_fails(self):
        result = role_family_filter(
            job(title="Account Executive"),
            prefs(target_roles=["software engineer"]),
            PROFILE,
        )
        assert result == "fail"


# ── seniority_filter ───────────────────────────────────────────────────────

class TestSeniorityFilter:
    def test_no_preference_passes(self):
        assert seniority_filter(job(), prefs(seniority_levels=[]), PROFILE) == "pass"

    def test_matching_seniority_passes(self):
        assert seniority_filter(job(title="Senior Backend Engineer"), prefs(), PROFILE) == "pass"

    def test_wrong_seniority_fails(self):
        assert seniority_filter(job(title="Engineering Manager"), prefs(), PROFILE) == "fail"

    def test_no_signal_is_uncertain(self):
        assert seniority_filter(job(title="Backend Engineer"), prefs(), PROFILE) == "uncertain"


# ── location_filter ────────────────────────────────────────────────────────

class TestLocationFilter:
    def test_any_remote_no_locations_passes(self):
        result = location_filter(
            job(), prefs(remote_policy="any", locations=[]), PROFILE
        )
        assert result == "pass"

    def test_remote_pref_remote_job_passes(self):
        result = location_filter(
            job(remote_policy="remote"), prefs(remote_policy="remote"), PROFILE
        )
        assert result == "pass"

    def test_remote_pref_onsite_job_fails(self):
        result = location_filter(
            job(remote_policy="onsite"), prefs(remote_policy="remote"), PROFILE
        )
        assert result == "fail"

    def test_location_substring_overlap_passes(self):
        result = location_filter(
            job(remote_policy="onsite", locations=["Toronto, Ontario"]),
            prefs(locations=["Toronto"]),
            PROFILE,
        )
        assert result == "pass"

    def test_no_location_overlap_fails(self):
        result = location_filter(
            job(remote_policy="onsite", locations=["Berlin, Germany"]),
            prefs(locations=["Toronto"]),
            PROFILE,
        )
        assert result == "fail"

    def test_remote_pref_hybrid_job_is_uncertain(self):
        result = location_filter(
            job(remote_policy="hybrid", locations=[]),
            prefs(remote_policy="remote", locations=[]),
            PROFILE,
        )
        assert result == "uncertain"


# ── salary_filter ──────────────────────────────────────────────────────────

class TestSalaryFilter:
    def test_no_minimum_passes(self):
        assert salary_filter(job(), prefs(min_salary=None), PROFILE) == "pass"

    def test_salary_above_minimum_passes(self):
        assert salary_filter(job(salary_max=160000), prefs(min_salary=100000), PROFILE) == "pass"

    def test_salary_below_minimum_fails(self):
        assert salary_filter(job(salary_max=80000), prefs(min_salary=100000), PROFILE) == "fail"

    def test_unknown_salary_is_uncertain(self):
        assert salary_filter(job(salary_max=None), prefs(min_salary=100000), PROFILE) == "uncertain"

    def test_currency_mismatch_is_uncertain(self):
        result = salary_filter(
            job(salary_max=160000, salary_currency="USD"),
            prefs(min_salary=100000, salary_currency="CAD"),
            PROFILE,
        )
        assert result == "uncertain"


# ── visa_filter ────────────────────────────────────────────────────────────

class TestVisaFilter:
    def test_no_visa_needed_passes(self):
        assert visa_filter(job(), prefs(needs_visa_sponsorship=False), PROFILE) == "pass"

    def test_needs_visa_and_job_sponsors_passes(self):
        result = visa_filter(
            job(visa_sponsorship="yes"), prefs(needs_visa_sponsorship=True), PROFILE
        )
        assert result == "pass"

    def test_needs_visa_and_job_refuses_fails(self):
        result = visa_filter(
            job(visa_sponsorship="no"), prefs(needs_visa_sponsorship=True), PROFILE
        )
        assert result == "fail"

    def test_needs_visa_unknown_is_uncertain(self):
        result = visa_filter(
            job(visa_sponsorship="unknown"), prefs(needs_visa_sponsorship=True), PROFILE
        )
        assert result == "uncertain"


# ── excluded_keyword_filter ────────────────────────────────────────────────

class TestExcludedKeywordFilter:
    def test_no_keywords_passes(self):
        assert excluded_keyword_filter(job(), prefs(excluded_keywords=[]), PROFILE) == "pass"

    def test_keyword_in_description_fails(self):
        result = excluded_keyword_filter(
            job(description_text="We build crypto trading tools."),
            prefs(excluded_keywords=["crypto"]),
            PROFILE,
        )
        assert result == "fail"

    def test_word_boundary_does_not_match_substring(self):
        result = excluded_keyword_filter(
            job(description_text="Modern JavaScript stack."),
            prefs(excluded_keywords=["java"]),
            PROFILE,
        )
        assert result == "pass"


# ── apply_hard_filters aggregate ───────────────────────────────────────────

class TestApplyHardFilters:
    def test_good_job_passes_overall(self):
        result = apply_hard_filters(job(), prefs(), PROFILE)
        assert result["overall"] == "passed"
        assert result["fail_reasons"] == []

    def test_disqualifying_salary_rejects(self):
        result = apply_hard_filters(job(salary_max=70000), prefs(), PROFILE)
        assert result["overall"] == "rejected"
        assert "salary" in result["fail_reasons"]

    def test_weak_job_passes_with_uncertainty(self):
        ambiguous = job(
            title="Platform Engineer",  # related family, no seniority signal
            remote_policy="unknown",
            locations=[],
            salary_max=None,
        )
        result = apply_hard_filters(ambiguous, prefs(target_roles=["backend engineer"]), PROFILE)
        assert result["overall"] == "passed"
        assert "uncertain" in result["results"].values()
