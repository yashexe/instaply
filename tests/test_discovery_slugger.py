"""Tests for slug guessing, name normalization, and title relevance."""

from src.discovery.relevance import matching_titles
from src.discovery.slugger import guess_slugs, normalize_name_key


class TestNormalizeNameKey:
    def test_strips_legal_suffixes_and_punctuation(self):
        assert normalize_name_key("Acme Corp, Inc.") == "acme"
        assert normalize_name_key("Acme") == "acme"

    def test_variants_collapse_to_same_key(self):
        assert normalize_name_key("Notion Labs") == normalize_name_key("notion-labs")
        assert normalize_name_key("Stripe, Inc.") == normalize_name_key("Stripe")

    def test_keeps_brand_words(self):
        # "labs"/"technologies" distinguish brands; only legal suffixes drop.
        assert normalize_name_key("Acme Labs") == "acmelabs"

    def test_empty_and_junk_names(self):
        assert normalize_name_key("") == ""
        assert normalize_name_key("Inc.") == ""


class TestGuessSlugs:
    def test_multi_word_company(self):
        slugs = guess_slugs("Acme Robotics Inc.")
        assert slugs == ["acmerobotics", "acme-robotics", "acme", "acmehq"]

    def test_single_word_company(self):
        slugs = guess_slugs("Stripe")
        assert slugs == ["stripe", "stripehq"]

    def test_no_duplicates_and_capped(self):
        slugs = guess_slugs("Acme")
        assert len(slugs) == len(set(slugs))
        assert len(slugs) <= 4

    def test_empty_name(self):
        assert guess_slugs("") == []
        assert guess_slugs("LLC") == []


class TestMatchingTitles:
    TITLES = [
        "Senior Software Engineer",
        "Backend Engineer, Payments",
        "Account Executive",
        "Head of Marketing",
        "Data Engineer",
    ]

    def test_direct_role_match(self):
        matched = matching_titles(self.TITLES, ["Software Engineer"])
        assert "Senior Software Engineer" in matched
        assert "Account Executive" not in matched

    def test_role_family_match(self):
        # "Backend Engineer, Payments" matches the software/backend family
        # even though the literal string "Software Engineer" is absent.
        matched = matching_titles(self.TITLES, ["Software Engineer"])
        assert "Backend Engineer, Payments" in matched

    def test_irrelevant_board(self):
        matched = matching_titles(
            ["Account Executive", "Sales Lead", "Recruiter"], ["Software Engineer"]
        )
        assert matched == []

    def test_no_target_roles(self):
        assert matching_titles(self.TITLES, []) == []

    def test_empty_titles_ignored(self):
        assert matching_titles(["", None, "Data Engineer"], ["Data Engineer"]) == [
            "Data Engineer"
        ]
