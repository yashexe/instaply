# Agent Build Guide

This guide is for AI coding agents implementing Instaply.

## Mission

Build a fast, high-signal job discovery assistant. The product should monitor near-source job postings, detect new roles quickly, score them against a user profile, and alert only when the match is strong.

## Product Boundaries

Build:

- Resume/profile ingestion.
- Job preference configuration.
- Source monitoring.
- ATS adapters.
- Deduplication.
- Match scoring.
- Explanatory alerts.
- Seen-job tracking.

Do not build in V1:

- Auto-application.
- Form filling.
- CAPTCHA bypass.
- Credentialed scraping.
- Mass crawling.
- Generic job board aggregation as the primary source.

## Implementation Rules

1. Keep source adapters isolated from the rest of the app.
2. Normalize all jobs before matching.
3. Make deduplication idempotent.
4. Make scoring explainable.
5. Store match traces.
6. Prefer official public ATS data where possible.
7. Treat resume data as sensitive.
8. Add tests around adapters, dedupe, hard filters, and alert idempotency.

## Suggested Module Layout

Adapt to the chosen stack, but keep these boundaries:

```text
src/
  profile/
  preferences/
  sources/
  ingestion/
    adapters/
      greenhouse/
      lever/
      ashby/
  jobs/
  matching/
  alerts/
  scheduler/
  db/
  web/
```

## First Vertical Slice

The best first implementation slice is:

1. User stores resume text and preferences.
2. User adds one Greenhouse source.
3. Scheduler fetches the Greenhouse source.
4. Jobs are normalized and deduped.
5. New jobs are scored.
6. Strong matches trigger one notification.

This proves the whole product loop before expanding providers.

## Definition of Done For A New Adapter

An ATS adapter is done when:

- It can validate whether it handles a source.
- It can fetch active jobs from a real source URL.
- It maps provider IDs and canonical URLs.
- It normalizes title, company, locations, remote policy, department, description, and posted time when available.
- It handles empty sources.
- It handles provider errors without crashing the scheduler.
- It has fixture-based tests.
- It does not create duplicate jobs when run repeatedly.

## Definition of Done For Matching

Matching is done when:

- Hard filters are separate from weighted scoring.
- Every score has a breakdown.
- Every alert has matching reasons and missing requirements.
- The same job/profile pair is scored idempotently.
- Tests cover strong fit, weak fit, wrong seniority, wrong location, missing visa, and duplicate job cases.

## Suggested Prompt For LLM Requirement Extraction

Use a structured output prompt like this when extracting job requirements:

```text
You are extracting structured hiring requirements from a job posting.
Return only JSON matching the requested schema.
Do not infer requirements that are not stated or strongly implied.
Use null or unknown when the posting is unclear.

Extract:
- role_family
- seniority
- required_skills
- preferred_skills
- years_experience_min
- locations
- remote_policy
- employment_type
- salary_range
- visa_sponsorship
- responsibilities
- domain_signals
- disqualifying_constraints
```

## Suggested Prompt For Match Explanation

Use a structured output prompt like this after deterministic scores are computed:

```text
You are explaining why a job does or does not match a candidate profile.
Use the supplied score breakdown and facts only.
Do not invent resume details.
Keep the explanation concise and useful for a job seeker deciding whether to apply quickly.

Return JSON:
{
  "summary": "one sentence",
  "matching_reasons": ["3 to 5 bullets"],
  "missing_requirements": ["0 to 5 bullets"],
  "uncertainties": ["0 to 5 bullets"]
}
```

## Test Fixtures To Create Early

Create fixtures for:

- Greenhouse job list with multiple departments.
- Lever job list with multiple locations.
- Ashby job list with HTML descriptions.
- Job with no posted date.
- Job with remote policy only in description text.
- Duplicate job with different URL query params.
- Strong candidate match.
- Keyword-similar but wrong role.
- Good job missing one preferred skill.
- Explicit no-sponsorship job.

## Manual QA Checklist

Before calling the MVP usable:

- Add a resume and confirm structured extraction is reasonable.
- Add target preferences.
- Add at least one real source per supported adapter.
- Run ingestion twice and confirm no duplicates.
- Confirm a strong job produces an alert.
- Confirm a weak job does not alert.
- Confirm the alert explains match reasons and gaps.
- Pause a source and confirm it stops polling.
- Break a source URL and confirm the failure is visible.

## Engineering Biases

- Build the narrow working loop first.
- Keep provider quirks inside adapters.
- Favor clear data over clever prompts.
- Make every automated decision inspectable.
- Avoid irreversible actions on behalf of the user.

