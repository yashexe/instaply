"""Tests for ATS provider detection."""

import pytest

from src.sources.detector import detect_provider


class TestDetectProvider:
    def test_greenhouse_board_url(self):
        provider, normalized, slug = detect_provider("https://boards.greenhouse.io/acme")
        assert provider == "greenhouse"
        assert normalized == "https://boards-api.greenhouse.io/v1/boards/acme/jobs?content=true"
        assert slug == "acme"

    def test_greenhouse_api_url(self):
        provider, normalized, slug = detect_provider(
            "https://boards-api.greenhouse.io/v1/boards/acme/jobs?content=true"
        )
        assert provider == "greenhouse"
        assert slug == "acme"

    def test_lever_board_url(self):
        provider, normalized, slug = detect_provider("https://jobs.lever.co/acme")
        assert provider == "lever"
        assert normalized == "https://api.lever.co/v0/postings/acme?mode=json"
        assert slug == "acme"

    def test_lever_api_url_roundtrips(self):
        """Slug must be re-derivable from the normalized API URL (used by discovery dedupe)."""
        provider, normalized, slug = detect_provider(
            "https://api.lever.co/v0/postings/acme?mode=json"
        )
        assert provider == "lever"
        assert normalized == "https://api.lever.co/v0/postings/acme?mode=json"
        assert slug == "acme"

    def test_lever_api_url_without_slug_is_custom(self):
        provider, _, slug = detect_provider("https://api.lever.co/v0/postings")
        assert provider == "custom"
        assert slug is None

    def test_ashby_board_url(self):
        provider, normalized, slug = detect_provider("https://jobs.ashbyhq.com/acme")
        assert provider == "ashby"
        assert normalized == "https://jobs.ashbyhq.com/acme"
        assert slug == "acme"

    def test_unknown_url_is_custom(self):
        provider, normalized, slug = detect_provider("https://careers.example.com/jobs")
        assert provider == "custom"
        assert slug is None

    def test_normalized_urls_roundtrip_for_all_providers(self):
        """detect_provider(normalized_url) must return the same provider and slug."""
        for url in [
            "https://boards.greenhouse.io/acme",
            "https://jobs.lever.co/acme",
            "https://jobs.ashbyhq.com/acme",
        ]:
            provider, normalized, slug = detect_provider(url)
            provider2, _, slug2 = detect_provider(normalized)
            assert (provider2, slug2) == (provider, slug)
