# Instaply

Instaply is a fast job discovery and alerting assistant. It monitors near-source ATS feeds, normalizes new postings, scores them against a candidate profile, and records alerts for strong matches.

## Current Status

This repository now has a runnable FastAPI backend with:

- Resume/profile parsing with LLM support and a local heuristic fallback.
- Job preference storage.
- Source registry for Greenhouse, Lever, and Ashby style sources.
- ATS ingestion adapters.
- Deduped job storage.
- Deterministic hard filters and weighted scoring over known data only: missing information lowers a separate confidence value instead of earning midpoint credit, and poor required-skills coverage caps the score outright.
- Local semantic matching: profile and job postings are embedded with a local sentence-transformers model (no API, resume never leaves the machine), and embedding similarity is the highest-weight scoring dimension. Vectors are cached in SQLite and computed lazily at scoring time; if the model is unavailable, scoring degrades gracefully to the other dimensions.
- LLM judge: an hourly job (or `./instaply judge`) has the LLM evaluate the top pending alert/digest matches against the actual resume and posting, blends its fit score with the deterministic one (60/40), replaces template explanations with grounded ones, and can promote or demote the decision.
- Cover letter drafts ride inside the same judge request (no extra API call): the judge is told the exact fit score at which the blend will reach the alert tier and writes a ~200 word draft only past that bar, in a fixed voice (direct, technical, plain sentences, no em dashes/colons/semicolons). Letters appear on inbox entries with a copy button and survive rescores.
- LLM budget: a persistent daily ledger caps total LLM calls (default 200/day, sized for Gemini free tier) with a protected slice for the judge (default 30/day) so judging can never starve extraction or alert explanations. On budget exhaustion or a 429, every caller falls back (heuristic extraction, template explanations), the judge stops cleanly, and unjudged matches stay pending for the next run. Failed judgments retry up to 2 attempts, then keep their template explanation permanently. `./instaply status` shows today's usage.
- Alert/digest decisions require both a score threshold and a minimum data confidence.
- Match explanations with LLM support and a template fallback.
- In-app alert history, with SMTP email support when configured.
- Scheduled match digest that batches mid-score matches into one email (or in-app alerts).
- APScheduler polling for due sources.
- Adapter fetches retry transient errors (429/5xx/network) with exponential backoff.
- Source failure tracking: after 3 consecutive failures a source is marked degraded, you get an escalation email (or log warning), and it keeps retrying at a slowed cadence until it recovers.
- Backlog rescore (`./instaply rescore`) that scores jobs skipped by baselined first polls or added before a profile change.

## Run Locally

Use Python 3.13 or newer. The `./instaply` wrapper creates the virtualenv and installs dependencies automatically on first run.

```bash
./instaply serve                      # web app + scheduler on port 8001
./instaply digest                     # send the match digest now
./instaply judge                      # LLM-judge the top pending matches now
./instaply rescore                    # score jobs skipped by baselined first polls
./instaply status                     # config and database counts
./instaply --help                     # all commands and options
```

The first poll of a new source is baselined: its existing jobs are stored but
not scored, so adding a source does not flood you with alerts for old
postings. Run `./instaply rescore` to score that backlog on demand, or
`./instaply rescore --all` to also recompute existing match results in place
(after scorer, threshold, or profile changes — alert and action history is
preserved). Rescore alerts are recorded in-app only;
pass `--email-alerts` to deliver them over email, and `--llm` to use LLM
requirement extraction instead of the fast heuristic.

Each subcommand has its own `--help` (e.g. `./instaply serve --help` for `--port`, `--host`, `--reload`).

## Tests

```bash
venv/bin/pip install -r requirements-dev.txt
venv/bin/python -m pytest
```

Then open:

- App UI: <http://127.0.0.1:8001/app>
- API health: <http://127.0.0.1:8001/health>
- API docs: <http://127.0.0.1:8001/docs>

## Key Endpoints

- `POST /api/profile/resume` - save and parse resume text.
- `GET /api/profile` - get active candidate profile.
- `PUT /api/preferences` - save job preferences.
- `GET /api/preferences` - get job preferences.
- `POST /api/sources` - add a monitored ATS source.
- `POST /api/sources/test` - test provider detection and source reachability.
- `POST /api/sources/{source_id}/poll` - manually poll a source.
- `GET /api/jobs` - list normalized jobs.
- `POST /api/matches/jobs/{job_id}` - score a job against the active profile.
- `GET /api/matches` - list match results.
- `GET /api/alerts` - list generated alerts.
- `POST /api/alerts/digest` - send the match digest immediately (optional `lookback_days` query param).

## Alerts and Digest

Matches that clear the alert threshold (default 85, adjustable per user in Preferences) trigger an immediate alert. Matches scoring between the digest threshold (default 65) and the alert threshold are batched: a scheduled job (default daily, `DIGEST_INTERVAL`) sends one combined email listing the top matches from the last `DIGEST_LOOKBACK_DAYS` days that have not been delivered before. Without SMTP configured, digest entries are recorded as in-app alerts instead. The Alerts view has a "Send digest now" button for on-demand delivery.

## UI

The app UI is served by FastAPI at `/app`, with static assets under `/static`.
Opening `/` redirects to `/app`, while `/docs` remains available for API debugging.

## Configuration

Copy `.env.example` to `.env` and fill in optional provider settings.

LLMs are optional for local development. Without an API key, the app uses deterministic heuristics for resume parsing, requirement extraction, and match explanations.
