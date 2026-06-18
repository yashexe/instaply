# Data Model

This file defines a practical V1 relational model. Names can be adapted to the chosen framework, but the domain concepts should remain stable.

## Entities

### users

Stores account-level information.

| Field | Type | Notes |
| --- | --- | --- |
| id | uuid | Primary key |
| email | text | Unique |
| name | text | Optional |
| timezone | text | Used for digest timing |
| created_at | timestamp |  |
| updated_at | timestamp |  |

### candidate_profiles

Stores structured user profile data derived from resume and preferences.

| Field | Type | Notes |
| --- | --- | --- |
| id | uuid | Primary key |
| user_id | uuid | FK users.id |
| version | integer | Increment on resume/preference changes |
| resume_text | text | Sensitive; optional retention |
| structured_profile | jsonb | Skills, roles, education, domains |
| created_at | timestamp |  |

Only one profile version should be active for matching, but old versions can be useful for audit/debug.

### job_preferences

Stores user-configured search constraints.

| Field | Type | Notes |
| --- | --- | --- |
| id | uuid | Primary key |
| user_id | uuid | FK users.id |
| target_roles | jsonb | Role families and titles |
| seniority_levels | jsonb | Accepted seniority levels |
| locations | jsonb | Cities, countries, time zones |
| remote_policy | text | remote, hybrid, onsite, any |
| min_salary | integer | Optional |
| salary_currency | text | Optional |
| needs_visa_sponsorship | boolean |  |
| must_have_skills | jsonb | User-defined hard requirements |
| nice_to_have_skills | jsonb | Boosts score |
| excluded_keywords | jsonb | Reject or penalize |
| alert_threshold | integer | Default 85 |
| created_at | timestamp |  |
| updated_at | timestamp |  |

### sources

Stores monitored company or ATS sources.

| Field | Type | Notes |
| --- | --- | --- |
| id | uuid | Primary key |
| user_id | uuid | FK users.id |
| company_name | text | User-facing company name |
| provider | text | greenhouse, lever, ashby, workday, custom |
| source_url | text | Original user-entered or discovered URL |
| normalized_url | text | Canonical source URL |
| priority | text | high, normal, low |
| status | text | active, paused, degraded, disabled |
| fetch_interval_seconds | integer |  |
| last_success_at | timestamp |  |
| last_error_at | timestamp |  |
| last_error_message | text | Truncated |
| consecutive_error_count | integer |  |
| adapter_config | jsonb | Provider-specific config |
| created_at | timestamp |  |
| updated_at | timestamp |  |

### job_postings

Stores canonical job postings.

| Field | Type | Notes |
| --- | --- | --- |
| id | uuid | Primary key |
| source_id | uuid | FK sources.id |
| provider | text |  |
| provider_job_id | text | Nullable |
| company_name | text |  |
| title | text |  |
| canonical_url | text |  |
| locations | jsonb | Array of normalized locations |
| remote_policy | text | remote, hybrid, onsite, unknown |
| employment_type | text | full_time, contract, internship, unknown |
| department | text | Optional |
| description_text | text | Normalized plain text |
| description_html | text | Optional |
| salary_min | integer | Optional |
| salary_max | integer | Optional |
| salary_currency | text | Optional |
| visa_sponsorship | text | yes, no, unknown |
| posted_at | timestamp | Nullable |
| first_seen_at | timestamp | Required |
| last_seen_at | timestamp | Required |
| content_hash | text | For change detection |
| raw_payload | jsonb | Optional/debug |
| status | text | active, closed, unknown |
| created_at | timestamp |  |
| updated_at | timestamp |  |

Recommended indexes:

- Unique partial index on `provider, provider_job_id` where provider_job_id is not null.
- Index on `canonical_url`.
- Index on `source_id, first_seen_at`.
- Index on `content_hash`.

### job_fingerprints

Stores multiple dedupe keys per job.

| Field | Type | Notes |
| --- | --- | --- |
| id | uuid | Primary key |
| job_posting_id | uuid | FK job_postings.id |
| kind | text | external_key, canonical_url_hash, semantic_key, content_hash |
| value | text |  |
| created_at | timestamp |  |

Unique index on `kind, value`.

### match_results

Stores scoring results for one job and one profile version.

| Field | Type | Notes |
| --- | --- | --- |
| id | uuid | Primary key |
| user_id | uuid | FK users.id |
| candidate_profile_id | uuid | FK candidate_profiles.id |
| job_posting_id | uuid | FK job_postings.id |
| score | integer | 0 to 100 |
| decision | text | alert, digest, ignore, rejected |
| hard_filter_results | jsonb | Rule outcomes |
| score_breakdown | jsonb | Dimension scores |
| matching_reasons | jsonb | Array of strings |
| missing_requirements | jsonb | Array of strings |
| uncertainties | jsonb | Array of strings |
| summary | text | One sentence |
| trace | jsonb | Debug details |
| created_at | timestamp |  |

Unique index on `user_id, candidate_profile_id, job_posting_id`.

### alerts

Stores notification decisions and delivery results.

| Field | Type | Notes |
| --- | --- | --- |
| id | uuid | Primary key |
| user_id | uuid | FK users.id |
| match_result_id | uuid | FK match_results.id |
| channel | text | email, slack, sms, push, in_app |
| status | text | pending, sent, failed, suppressed |
| idempotency_key | text | Unique |
| sent_at | timestamp | Nullable |
| failure_message | text | Nullable |
| created_at | timestamp |  |

### user_job_actions

Tracks user feedback.

| Field | Type | Notes |
| --- | --- | --- |
| id | uuid | Primary key |
| user_id | uuid | FK users.id |
| job_posting_id | uuid | FK job_postings.id |
| action | text | saved, dismissed, applied, not_relevant |
| feedback | text | Optional |
| created_at | timestamp |  |

## Useful Enums

Do not overfit enums too early, but normalize these:

- `remote_policy`: remote, hybrid, onsite, unknown.
- `source_status`: active, paused, degraded, disabled.
- `match_decision`: alert, digest, ignore, rejected.
- `alert_status`: pending, sent, failed, suppressed.
- `visa_sponsorship`: yes, no, unknown.

## Idempotency

Use deterministic idempotency keys:

- Alert: `user_id + job_posting_id + candidate_profile_id + channel`.
- Fetch lock: `source_id + fetch_window`.
- Match result: `user_id + candidate_profile_id + job_posting_id`.

## Retention

Suggested V1 defaults:

- Keep normalized job postings indefinitely unless deleted by user policy.
- Keep raw provider payloads for 30 to 90 days.
- Keep resume text until user deletes or replaces it.
- Keep match traces while the associated profile version exists.

