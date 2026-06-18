-- Staging table for automated source discovery.
-- Suggestions live here until the user accepts (-> sources row) or rejects.
CREATE TABLE IF NOT EXISTS discovered_companies (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    company_name TEXT NOT NULL,
    name_key TEXT NOT NULL,
    provider TEXT,
    slug TEXT,
    board_url TEXT,
    normalized_url TEXT,
    status TEXT NOT NULL DEFAULT 'suggested'
        CHECK (status IN ('suggested', 'accepted', 'rejected', 'not_found', 'irrelevant')),
    origin TEXT NOT NULL,
    reason TEXT,
    job_count INTEGER NOT NULL DEFAULT 0,
    matching_titles TEXT NOT NULL DEFAULT '[]',
    source_id TEXT REFERENCES sources(id) ON DELETE SET NULL,
    last_probed_at TIMESTAMP,
    discovered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    decided_at TIMESTAMP,
    UNIQUE(user_id, name_key)
);

CREATE INDEX IF NOT EXISTS idx_discovered_status
    ON discovered_companies(user_id, status);
