# UI Product Spec

## Purpose

The Instaply UI should make the backend usable as a fast job alert assistant. It is not a marketing site and it is not a generic job board. The first screen should help the user understand whether their job watch system is configured, healthy, and finding strong matches.

## Product Shape

Use an app-style interface with persistent navigation and dense, scannable work surfaces. Avoid a landing page, oversized hero sections, decorative marketing cards, or explanatory copy that repeats what controls already imply.

Recommended navigation:

- Dashboard
- Profile
- Preferences
- Sources
- Jobs
- Matches
- Alerts

## Primary User Goals

The UI must let the user:

1. Add or update their resume/profile.
2. Review parsed profile facts.
3. Configure job preferences.
4. Add target ATS/company sources.
5. Manually test and poll sources.
6. Review normalized jobs.
7. See match scores and reasons.
8. Open alerts quickly.
9. Save, dismiss, or mark jobs as applied.

## First-Run Flow

When the user has no active profile or preferences:

1. Show setup progress on Dashboard.
2. Prompt for resume/profile text.
3. Prompt for core preferences.
4. Prompt for first source URL.
5. Let the user test source detection.
6. Let the user poll the source.
7. Show jobs, matches, and alerts.

The user should never need to understand API routes to complete this flow.

## Dashboard

Dashboard is the operating console.

Show:

- Active profile status.
- Number of active sources.
- Number of degraded sources.
- New jobs found recently.
- Strong matches.
- Latest alerts.
- Last successful polling time.

Primary actions:

- Add resume.
- Add source.
- View alerts.

Empty state:

- If no profile exists, the main action is `Add resume`.
- If no sources exist, the main action is `Add source`.
- If profile and sources exist but no matches exist, show source health and recent job count.

## Profile Screen

Purpose: manage resume and parsed facts.

Controls:

- Large resume text input.
- Save/parse button.
- Active profile version display.
- Parsed skills list.
- Parsed roles list.
- Domains, seniority, years of experience.

States:

- No profile.
- Parsing/saving.
- Saved profile.
- Failed save.

Design guidance:

- Parsed facts should be editable later, but V1 can be read-only.
- Show compact chips for skills and domains.
- Keep raw resume text visible only on this screen.

## Preferences Screen

Purpose: define what counts as a good job.

Controls:

- Target role tags.
- Seniority multi-select.
- Location tags.
- Remote policy segmented control.
- Minimum salary input.
- Currency input/select.
- Visa sponsorship toggle.
- Must-have skills tags.
- Nice-to-have skills tags.
- Excluded keywords tags.
- Alert threshold slider or number input.

States:

- Defaults loaded.
- Unsaved changes.
- Saving.
- Saved.
- Failed save.

## Sources Screen

Purpose: manage monitored company/ATS sources.

Controls:

- Source URL input.
- Optional company name.
- Priority segmented control.
- Test source button.
- Add source button.
- Source table.

Source table columns:

- Company.
- Provider.
- Priority.
- Status.
- Jobs found or last poll summary.
- Last success.
- Last error.
- Actions.

Actions:

- Poll now.
- Pause/resume.
- Delete.
- Open source URL.

States:

- No sources.
- Testing source.
- Polling source.
- Active.
- Degraded.
- Paused.

## Jobs Screen

Purpose: inspect normalized postings.

Show:

- Title.
- Company.
- Location.
- Remote policy.
- First seen.
- Source/provider.
- Status.
- Link.

Actions:

- Score job.
- Open job.
- Save.
- Dismiss.
- Mark applied.

Filters:

- Company.
- Provider.
- Remote policy.
- Date first seen.

## Matches Screen

Purpose: evaluate fit explanations.

Show:

- Score.
- Decision.
- Title and company.
- Summary.
- Matching reasons.
- Missing requirements.
- Uncertainties.
- Score breakdown.

Filters:

- Decision: alert, digest, ignore, rejected.
- Minimum score.
- Company.

The score should be visually prominent but not decorative. A compact progress bar or colored badge is enough.

## Alerts Screen

Purpose: inbox for urgent opportunities.

Show:

- Alert status.
- Score.
- Job title and company.
- Match summary.
- Matching reasons.
- Missing requirements.
- Job link.
- Sent time.

Actions:

- Open job.
- Save.
- Dismiss.
- Mark applied.

Alert inbox should be the most polished part of V1 because it is the core product promise.

## Visual Style

Direction:

- Quiet, operational, and fast.
- Dense enough for repeated use.
- Clear hierarchy, not flashy.
- App-like, not marketing-like.

Suggested palette:

- Neutral background.
- Dark text.
- One restrained accent color for primary actions and high scores.
- Status colors for success, warning, error, and muted states.

Avoid:

- Purple/blue gradient-heavy UI.
- Giant hero sections.
- Nested cards.
- Decorative blobs or abstract backgrounds.
- Text blocks explaining obvious controls.

## Mobile

Mobile should be usable, but desktop is the primary V1 target.

Mobile priorities:

- Alerts inbox.
- Job/match detail.
- Add source.
- Resume editing can be less optimized.

