-- Instaply V1 Schema
-- All tables for the job discovery and alerting system.

-- ============================================================================
-- Users (single-user for V1, but schema-ready for multi-user)
-- ============================================================================
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    email TEXT UNIQUE,
    name TEXT,
    timezone TEXT DEFAULT 'UTC',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Insert default single user
INSERT OR IGNORE INTO users (id, email, name)
VALUES ('default', 'user@instaply.local', 'Default User');


-- ============================================================================
-- Candidate Profiles (versioned, parsed from resume)
-- ============================================================================
CREATE TABLE IF NOT EXISTS candidate_profiles (
    id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    version INTEGER NOT NULL DEFAULT 1,
    resume_text TEXT,
    structured_profile TEXT,  -- JSON: skills, roles, education, domains
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_candidate_profiles_user
    ON candidate_profiles(user_id, is_active);


-- ============================================================================
-- Job Preferences
-- ============================================================================
CREATE TABLE IF NOT EXISTS job_preferences (
    id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    target_roles TEXT,          -- JSON array of role families/titles
    seniority_levels TEXT,      -- JSON array of accepted seniority levels
    locations TEXT,             -- JSON array of cities/countries/timezones
    remote_policy TEXT DEFAULT 'any',  -- remote, hybrid, onsite, any
    min_salary INTEGER,
    salary_currency TEXT,
    needs_visa_sponsorship INTEGER DEFAULT 0,
    must_have_skills TEXT,      -- JSON array
    nice_to_have_skills TEXT,   -- JSON array
    excluded_keywords TEXT,     -- JSON array
    alert_threshold INTEGER DEFAULT 85,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_job_preferences_user
    ON job_preferences(user_id);


-- ============================================================================
-- Sources (monitored companies / ATS feeds)
-- ============================================================================
CREATE TABLE IF NOT EXISTS sources (
    id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    company_name TEXT NOT NULL,
    provider TEXT NOT NULL,     -- greenhouse, lever, ashby, workday, custom
    source_url TEXT NOT NULL,
    normalized_url TEXT,
    priority TEXT DEFAULT 'normal',  -- high, normal, low
    status TEXT DEFAULT 'active',    -- active, paused, degraded, disabled
    fetch_interval_seconds INTEGER,
    last_success_at TIMESTAMP,
    last_error_at TIMESTAMP,
    last_error_message TEXT,
    consecutive_error_count INTEGER DEFAULT 0,
    adapter_config TEXT,       -- JSON provider-specific config
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_sources_user ON sources(user_id);
CREATE INDEX IF NOT EXISTS idx_sources_status ON sources(status);


-- ============================================================================
-- Job Postings (canonical, normalized)
-- ============================================================================
CREATE TABLE IF NOT EXISTS job_postings (
    id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    provider TEXT,
    provider_job_id TEXT,
    company_name TEXT NOT NULL,
    title TEXT NOT NULL,
    canonical_url TEXT,
    locations TEXT,            -- JSON array of normalized locations
    remote_policy TEXT DEFAULT 'unknown',  -- remote, hybrid, onsite, unknown
    employment_type TEXT DEFAULT 'unknown', -- full_time, contract, internship, unknown
    department TEXT,
    description_text TEXT,
    description_html TEXT,
    salary_min INTEGER,
    salary_max INTEGER,
    salary_currency TEXT,
    visa_sponsorship TEXT DEFAULT 'unknown', -- yes, no, unknown
    posted_at TIMESTAMP,
    first_seen_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_seen_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    content_hash TEXT,
    raw_payload TEXT,          -- JSON, optional/debug
    extracted_requirements TEXT, -- JSON, cached LLM extraction
    status TEXT DEFAULT 'active',  -- active, closed, unknown
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Unique partial index: provider + provider_job_id when not null
CREATE UNIQUE INDEX IF NOT EXISTS idx_job_postings_provider_id
    ON job_postings(provider, provider_job_id)
    WHERE provider_job_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_job_postings_canonical_url
    ON job_postings(canonical_url);

CREATE INDEX IF NOT EXISTS idx_job_postings_source_seen
    ON job_postings(source_id, first_seen_at);

CREATE INDEX IF NOT EXISTS idx_job_postings_content_hash
    ON job_postings(content_hash);


-- ============================================================================
-- Job Fingerprints (multi-key deduplication)
-- ============================================================================
CREATE TABLE IF NOT EXISTS job_fingerprints (
    id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    job_posting_id TEXT NOT NULL REFERENCES job_postings(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,        -- external_key, canonical_url_hash, semantic_key, content_hash
    value TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_job_fingerprints_kind_value
    ON job_fingerprints(kind, value);

CREATE INDEX IF NOT EXISTS idx_job_fingerprints_job
    ON job_fingerprints(job_posting_id);


-- ============================================================================
-- Match Results (scoring output)
-- ============================================================================
CREATE TABLE IF NOT EXISTS match_results (
    id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    candidate_profile_id TEXT NOT NULL REFERENCES candidate_profiles(id) ON DELETE CASCADE,
    job_posting_id TEXT NOT NULL REFERENCES job_postings(id) ON DELETE CASCADE,
    score INTEGER NOT NULL,    -- 0 to 100
    decision TEXT NOT NULL,    -- alert, digest, ignore, rejected
    hard_filter_results TEXT,  -- JSON rule outcomes
    score_breakdown TEXT,      -- JSON dimension scores
    matching_reasons TEXT,     -- JSON array of strings
    missing_requirements TEXT, -- JSON array of strings
    uncertainties TEXT,        -- JSON array of strings
    summary TEXT,
    trace TEXT,                -- JSON debug details
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_match_results_unique
    ON match_results(user_id, candidate_profile_id, job_posting_id);

CREATE INDEX IF NOT EXISTS idx_match_results_decision
    ON match_results(decision);


-- ============================================================================
-- Alerts (notification delivery)
-- ============================================================================
CREATE TABLE IF NOT EXISTS alerts (
    id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    match_result_id TEXT NOT NULL REFERENCES match_results(id) ON DELETE CASCADE,
    channel TEXT NOT NULL,     -- email, slack, sms, push, in_app
    status TEXT DEFAULT 'pending',  -- pending, sent, failed, suppressed
    idempotency_key TEXT UNIQUE NOT NULL,
    sent_at TIMESTAMP,
    failure_message TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_alerts_user ON alerts(user_id);
CREATE INDEX IF NOT EXISTS idx_alerts_status ON alerts(status);


-- ============================================================================
-- User Job Actions (feedback tracking)
-- ============================================================================
CREATE TABLE IF NOT EXISTS user_job_actions (
    id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    job_posting_id TEXT NOT NULL REFERENCES job_postings(id) ON DELETE CASCADE,
    action TEXT NOT NULL,      -- saved, dismissed, applied, not_relevant
    feedback TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_user_job_actions_user
    ON user_job_actions(user_id, job_posting_id);
