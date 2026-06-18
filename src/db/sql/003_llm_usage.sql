-- Persistent daily LLM call ledger so the budget survives restarts.
-- day is the UTC date (YYYY-MM-DD); category is the call site
-- (extract / explain / judge / profile).

CREATE TABLE IF NOT EXISTS llm_usage (
    day TEXT NOT NULL,
    category TEXT NOT NULL,
    calls INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (day, category)
);
