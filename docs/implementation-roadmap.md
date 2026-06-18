# Implementation Roadmap

## Phase 0: Project Foundation

Goal: Create a runnable app skeleton with clear domain boundaries.

Tasks:

- Choose stack and package structure.
- Add database and migrations.
- Add background job runner or scheduler.
- Add environment configuration.
- Add structured logging.
- Add basic test setup.

Acceptance criteria:

- App starts locally.
- Database migrations run locally.
- A background job can execute and write a log line.
- Tests can run in one command.

## Phase 1: Profile and Preferences

Goal: Let the user define what a good job looks like.

Tasks:

- Add resume text input or upload.
- Parse resume into structured candidate profile.
- Add job preference fields.
- Store profile versions.
- Add profile preview/debug view.

Acceptance criteria:

- User can save resume/profile.
- User can save target roles, location, remote, salary, visa, and skills.
- The system can produce a structured profile JSON object.

## Phase 2: Source Registry

Goal: Let the user add monitored companies or ATS URLs.

Tasks:

- Add source create/list/pause/delete.
- Add provider detection for Greenhouse, Lever, and Ashby URLs.
- Store source health fields.
- Validate source URLs with a test fetch.

Acceptance criteria:

- User can add at least three source types.
- Invalid URLs show a useful error.
- Source health is visible somewhere.

## Phase 3: Ingestion

Goal: Poll sources and store normalized jobs.

Tasks:

- Implement adapter interface.
- Implement Greenhouse adapter.
- Implement Lever adapter.
- Implement Ashby adapter.
- Add scheduler job to poll active sources.
- Add dedupe and content hash logic.

Acceptance criteria:

- Polling a source creates normalized job records.
- Re-polling the same source does not create duplicates.
- Closed or missing jobs are handled predictably.
- Adapter failures are logged and tracked on the source.

## Phase 4: Matching and Scoring

Goal: Score new jobs against the active profile.

Tasks:

- Extract structured job requirements.
- Implement hard filter rules.
- Implement weighted scoring.
- Generate matching reasons and missing requirements.
- Store match traces.

Acceptance criteria:

- New jobs receive match results.
- Strong matches include an explanation.
- Rejected jobs include hard filter reasons.
- Match tests cover good, weak, and disqualifying examples.

## Phase 5: Alerts

Goal: Notify the user quickly for strong matches.

Tasks:

- Add alert threshold configuration.
- Add at least one notification channel.
- Add idempotency keys.
- Add alert history.
- Add save/dismiss/applied actions.

Acceptance criteria:

- A strong new match sends one alert.
- Re-polling does not send duplicate alerts.
- Alert contains link, score, reasons, missing requirements, and first-seen time.
- User actions are stored.

## Phase 6: Feedback Loop

Goal: Improve relevance using user behavior.

Tasks:

- Track saved, dismissed, applied, and not relevant actions.
- Add simple preference adjustment suggestions.
- Add per-source and per-alert quality metrics.
- Add digest mode for medium matches.

Acceptance criteria:

- User feedback is visible in match history.
- Dismissed jobs influence future scoring or filtering.
- Medium matches can be grouped instead of immediately sent.

## Phase 7: Expansion

Goal: Add more sources and workflow support after the alert loop works.

Possible additions:

- Workday adapter.
- SmartRecruiters adapter.
- Browser-assisted source discovery.
- Resume tailoring suggestions.
- Cover letter or application draft generation.
- Company watchlists.
- Team/shared search.

## Build Priority

If time is limited, build in this order:

1. Resume/profile parsing.
2. Preferences.
3. Source registry.
4. One reliable ATS adapter.
5. Deduped job storage.
6. Scoring.
7. Alerts.
8. More adapters.

Do not build a polished dashboard before the core detection, scoring, and alert loop works.

