# Source Ingestion

## Goal

Monitor job postings as close to the original source as practical, detect new postings quickly, and normalize provider-specific data into a common job schema.

## Source Types

### ATS Feeds

Preferred V1 source type. These are usually close to the original company posting and easier to normalize.

Initial providers:

- Greenhouse.
- Lever.
- Ashby.

Future providers:

- Workday.
- SmartRecruiters.
- Teamtailor.
- iCIMS.
- Recruitee.
- Breezy.

### Company Career Pages

Use when the ATS feed cannot be identified or when a company hosts jobs directly. Start with discovery and manual confirmation rather than brittle scraping.

### Job Boards

Use later as a backup source, not the primary source. Job boards can be delayed, duplicated, or rewritten.

## Adapter Interface

Every source adapter should implement the same conceptual interface:

```ts
type SourceAdapter = {
  provider: string;
  canHandle(input: SourceInput): Promise<boolean>;
  discover(input: SourceInput): Promise<DiscoveredSource>;
  fetchJobs(source: SourceConfig): Promise<RawJobBatch>;
  normalize(raw: RawJobBatch, source: SourceConfig): Promise<NormalizedJob[]>;
};
```

## Normalized Job Fields

Required when available:

- `source_id`
- `provider`
- `provider_job_id`
- `company_name`
- `title`
- `canonical_url`
- `locations`
- `remote_policy`
- `employment_type`
- `department`
- `description_text`
- `description_html`
- `salary_min`
- `salary_max`
- `salary_currency`
- `visa_sponsorship`
- `posted_at`
- `first_seen_at`
- `raw_payload_hash`

Unknown values should be represented as `null` or `unknown`, not guessed.

## Provider Notes

### Greenhouse

Use official public job board endpoints when available. Greenhouse often exposes company boards through predictable public paths. Normalize departments, offices, job IDs, and hosted application URLs.

Watch for:

- Departments nested in responses.
- Office/location arrays.
- Job description HTML.
- Boards with custom slugs.

### Lever

Lever postings are commonly available from public company posting endpoints. Normalize workplace type, categories, lists, and posting hosted URLs.

Watch for:

- Multiple locations.
- Commitment/team/department fields.
- Hosted apply URLs.
- Remote-friendly roles represented through text fields.

### Ashby

Ashby career boards often expose structured posting data. Normalize job IDs, location objects, department/team fields, employment type, and hosted URLs.

Watch for:

- Board-specific organization identifiers.
- Structured location data.
- HTML descriptions.
- Job state/status.

### Workday

Workday varies by tenant and is more complex. Treat Workday as a later adapter unless the user provides a specific tenant URL. Implement discovery and parsing per tenant pattern instead of assuming one universal endpoint.

Watch for:

- Tenant-specific API paths.
- Pagination.
- Search payloads.
- Bot protection.
- Inconsistent posted dates.

## Polling Strategy

Each source should store:

- `fetch_interval_seconds`
- `last_fetch_started_at`
- `last_fetch_completed_at`
- `last_success_at`
- `last_error_at`
- `last_error_message`
- `consecutive_error_count`
- `etag` or `last_modified` when available

Use conditional requests when supported.

Recommended behavior:

- No overlapping fetches for the same source.
- Back off after repeated failures.
- Mark source as degraded after repeated errors.
- Alert the user or admin when an important source has been failing for a long time.

## Freshness

Use `posted_at` when provided by the source. If unavailable, use `first_seen_at`. Always show which freshness signal is being used.

For fast alerts, `first_seen_at` is often the most reliable product metric because not every ATS exposes a trustworthy posted timestamp.

## First Poll Baseline

Most ATS feeds return the full currently open job board, not a delta of newly
posted jobs. The first successful poll for a source should be treated as a
baseline snapshot:

- Insert normalized postings and fingerprints.
- Mark the source as successfully seen.
- Do not score or alert every existing posting by default.
- On later polls, score only postings that are new to the database or whose meaningful content hash changed.

This keeps "new" aligned with "new since Instaply started watching this source"
instead of "all jobs that existed before the source was added."

## Duplicate Detection

Generate:

- `external_key`: provider + provider job ID, when present.
- `canonical_url_hash`: normalized canonical URL.
- `semantic_key`: company + normalized title + normalized location set.
- `content_hash`: normalized title + locations + description text.

Use the strongest available key. Store all keys to help debug duplicates.

## Politeness and Compliance

- Prefer official public endpoints.
- Do not bypass authentication, CAPTCHA, or access controls.
- Respect robots and terms where applicable.
- Use conservative polling intervals for pages without official APIs.
- Identify the app with a clear user agent if the implementation controls HTTP headers.

## Ingestion Acceptance Criteria

An implementation is good enough for V1 when:

- A user can add at least one Greenhouse, Lever, and Ashby source.
- The app detects newly added postings from those sources.
- The app stores normalized jobs with original URLs.
- Duplicate polling does not create duplicate jobs.
- Failed sources are visible in a source health view or log.
