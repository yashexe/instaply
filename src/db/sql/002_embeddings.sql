-- Cached embedding vectors for semantic matching.
-- embedding stores float32 bytes; embedding_model records which model
-- produced them so a model change invalidates the cache.

ALTER TABLE job_postings ADD COLUMN embedding BLOB;
ALTER TABLE job_postings ADD COLUMN embedding_model TEXT;

ALTER TABLE candidate_profiles ADD COLUMN embedding BLOB;
ALTER TABLE candidate_profiles ADD COLUMN embedding_model TEXT;
