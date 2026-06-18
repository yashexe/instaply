# UI Implementation Plan

## Goal

Build the smallest useful UI on top of the existing FastAPI backend. A user should be able to set up their profile, preferences, sources, and inspect alerts without using Swagger.

## Phase 1: App Shell

Tasks:

- Add `src/web/router.py`.
- Add `src/web/static/index.html`.
- Add `src/web/static/styles.css`.
- Add `src/web/static/app.js`.
- Mount static files in FastAPI.
- Serve UI at `/app`.
- Redirect `/` to `/app`.

Acceptance criteria:

- `http://127.0.0.1:8000/` opens the app.
- `/docs` still works.
- Navigation shows Dashboard, Profile, Preferences, Sources, Jobs, Matches, Alerts.

## Phase 2: API Client And Dashboard

Tasks:

- Implement `api()` helper.
- Load profile, preferences, sources, jobs, matches, alerts.
- Render setup status.
- Render recent alerts and source health.

Acceptance criteria:

- Dashboard loads without console errors.
- Missing profile appears as setup action, not as a crash.
- Source and alert counts display correctly.

## Phase 3: Profile And Preferences

Tasks:

- Build resume textarea and save button.
- Render parsed skills, roles, domains, seniority, years.
- Build preferences form.
- Save preferences through `PUT /api/preferences`.

Acceptance criteria:

- User can paste resume and see parsed facts.
- User can edit preferences and see saved state.
- Forms show loading and error states.

## Phase 4: Sources

Tasks:

- Build source URL form.
- Add Test Source action.
- Add Save Source action.
- Render source table.
- Add Poll Now action.
- Add pause/resume and delete actions.

Acceptance criteria:

- User can test a Greenhouse, Lever, or Ashby URL.
- User can add the source.
- Poll Now updates source and job data.
- Degraded or failing sources are visible.

## Phase 5: Jobs, Matches, Alerts

Tasks:

- Render jobs table.
- Add Score Job action.
- Render match list with score, reasons, gaps, uncertainties.
- Render alert inbox.
- Add job actions: save, dismiss, applied, not relevant.

Acceptance criteria:

- New jobs are visible after polling.
- Manual score creates or returns a match.
- Alerts are readable and link to the job source.
- User feedback actions persist.

## Phase 6: Polish

Tasks:

- Add responsive layout.
- Add toasts.
- Add loading skeletons or spinners.
- Add empty states.
- Improve table filtering.
- Add basic keyboard/focus checks.

Acceptance criteria:

- No obvious text overflow at mobile or desktop sizes.
- No overlapping UI elements.
- Main workflows are usable without Swagger.

## Initial UI Build Order For An Agent

1. Create app shell and FastAPI web router.
2. Build API client.
3. Build Dashboard with read-only data.
4. Build Profile form.
5. Build Preferences form.
6. Build Sources form/table.
7. Build Jobs table.
8. Build Matches and Alerts views.

## Design Acceptance Checklist

- The first screen is the product UI, not a landing page.
- Navigation is persistent.
- Tables are scannable.
- Primary actions have icons or clear labels.
- Statuses are visible and textual.
- No nested cards.
- No decorative hero.
- Alerts are easy to open and act on.

## Future UI Enhancements

- Editable parsed profile facts.
- Company watchlist import.
- Alert digest preferences.
- Match feedback tuning.
- Resume tailoring assistant.
- Application draft assistant.
- Browser notifications.
- OAuth/login for multi-user use.

