# UI API Contract

This document describes how the UI should use the existing backend API.

Base URL:

```text
/api
```

## Health

### `GET /health`

Use for a lightweight system status indicator.

Response:

```json
{
  "status": "ok",
  "version": "0.1.0",
  "llm_configured": false,
  "smtp_configured": false
}
```

## Profile

### `GET /api/profile`

Returns active profile.

UI behavior:

- If `404`, show no-profile setup state.
- If successful, show parsed profile facts.

### `POST /api/profile/resume`

Request:

```json
{
  "resume_text": "resume content"
}
```

Response includes:

- `id`
- `version`
- `structured_profile`
- `is_active`
- `created_at`

UI behavior:

- Disable save while request is pending.
- Show parsed facts after success.
- Warn user that resume text is sensitive.

## Preferences

### `GET /api/preferences`

Returns saved preferences or defaults.

### `PUT /api/preferences`

Request:

```json
{
  "target_roles": ["Software Engineer"],
  "seniority_levels": ["senior"],
  "locations": ["Remote", "Toronto"],
  "remote_policy": "remote",
  "min_salary": 150000,
  "salary_currency": "USD",
  "needs_visa_sponsorship": false,
  "must_have_skills": ["TypeScript", "React"],
  "nice_to_have_skills": ["FastAPI"],
  "excluded_keywords": ["intern"],
  "alert_threshold": 85
}
```

UI behavior:

- Treat array fields as tag inputs.
- Use segmented controls for `remote_policy`.
- Use toggle for `needs_visa_sponsorship`.
- Use number input or slider for `alert_threshold`.

## Sources

### `GET /api/sources`

Query params:

- `status` optional.

Use to populate source table.

### `POST /api/sources/test`

Request:

```json
{
  "url": "https://boards.greenhouse.io/company",
  "company_name": "Company",
  "priority": "normal"
}
```

Response:

```json
{
  "success": true,
  "provider": "greenhouse",
  "job_count": 12,
  "message": "Found 12 jobs from Greenhouse."
}
```

UI behavior:

- Let user test before saving.
- Show provider and job count.
- If provider is `custom`, explain job count may be unknown.

### `POST /api/sources`

Creates a monitored source.

### `PATCH /api/sources/{source_id}`

Use for:

- Pause/resume.
- Priority changes.
- Company name edits.

Request:

```json
{
  "status": "paused",
  "priority": "high",
  "company_name": "Company"
}
```

### `DELETE /api/sources/{source_id}`

Delete a source.

### `POST /api/sources/{source_id}/poll`

Query params:

- `score_matches=true`

Use for Poll Now. On a source's first successful poll, the backend may baseline
current postings without scoring them so old listings do not become urgent
alerts simply because the source was added today.

Response:

```json
{
  "source_id": "id",
  "job_count": 10,
  "new_count": 2,
  "changed_count": 1,
  "baseline_count": 0,
  "matched_count": 2,
  "error": null
}
```

UI behavior:

- Show polling spinner only for that row.
- Refresh jobs, matches, alerts, and source list after success.

## Jobs

### `GET /api/jobs`

Query params:

- `source_id` optional.
- `limit`
- `offset`

Use for jobs table.

### `GET /api/jobs/{job_id}`

Use for job detail panel.

### `POST /api/jobs/{job_id}/actions`

Request:

```json
{
  "action": "saved",
  "feedback": "Looks relevant"
}
```

Allowed UI actions:

- `saved`
- `dismissed`
- `applied`
- `not_relevant`

## Matches

### `GET /api/matches`

Query params:

- `decision`
- `limit`
- `offset`

Use for matches screen.

### `POST /api/matches/jobs/{job_id}`

Query params:

- `send_alerts=true`

Use for manual Score Job action.

### `GET /api/matches/{match_id}`

Use for match detail panel.

## Alerts

### `GET /api/alerts`

Query params:

- `status`
- `limit`
- `offset`

Use for alerts inbox.

### `GET /api/alerts/{alert_id}`

Use for alert detail panel.

## Error Handling

Common backend errors:

- `404 No active profile found`: show setup state.
- `404 Source not found`: refresh source list.
- `404 Job not found`: refresh job list.
- `500`: show general error toast and keep current view stable.

## Refresh Strategy

On initial load:

1. Fetch profile.
2. Fetch preferences.
3. Fetch sources.
4. Fetch jobs.
5. Fetch matches.
6. Fetch alerts.

After source poll:

1. Refresh source list.
2. Refresh jobs.
3. Refresh matches.
4. Refresh alerts.

After profile update:

1. Refresh profile.
2. Keep existing matches but show note that future scoring uses new profile.
