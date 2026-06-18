-- The provider's own "last updated" timestamp for a posting, kept separate
-- from posted_at (original publish date) and from our row-level updated_at.
ALTER TABLE job_postings ADD COLUMN provider_updated_at TEXT;
