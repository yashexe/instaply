# Product Brief

## Problem

Good roles often receive strong applicant volume shortly after posting. Manual job search is slow because users repeatedly check company career pages, ATS boards, job boards, and newsletters. Generic alerts are noisy and rarely explain why a role is relevant.

Instaply should help a user move fast by detecting new, relevant roles close to their original source, scoring them against the user's resume and preferences, and alerting only when the fit is strong.

## Target User

The initial target user is an active job seeker who already has a resume and knows the kinds of roles they want. They care about speed, signal quality, and clear reasoning.

Example profile:

- Software engineer, product engineer, data engineer, AI engineer, designer, PM, or similar knowledge worker.
- Has preferred companies or company categories.
- Wants remote, hybrid, location-specific, salary, visa, seniority, and skill filtering.
- Wants a concise alert, not a dashboard full of weak matches.

## Core User Story

As a job seeker, I want Instaply to monitor target company career pages and ATS feeds, compare new postings to my resume and preferences, and immediately notify me when a strong match appears so I can apply quickly.

## V1 User Flow

1. User creates a profile.
2. User uploads or pastes resume content.
3. System parses resume into structured skills, roles, experience, education, projects, domains, and constraints.
4. User configures job preferences.
5. User adds companies or ATS source URLs to monitor.
6. System polls or fetches sources on a schedule.
7. System normalizes postings into a common schema.
8. System detects whether each posting is new or changed.
9. System applies hard filters.
10. System scores surviving jobs.
11. System sends immediate alerts for strong matches.
12. System stores seen jobs and alert history to avoid duplicates.

## Alert Content

Each alert should include:

- Job title.
- Company.
- Location and remote policy.
- Original job URL.
- Match score from 0 to 100.
- Posted or first-seen time.
- Top matching reasons.
- Missing or uncertain requirements.
- Suggested urgency.
- Quick actions: save, dismiss, mark applied, open source.

## Hard Filters

Hard filters remove jobs before scoring:

- Role family does not match target role families.
- Seniority is outside accepted range.
- Location or remote policy is incompatible.
- Salary is below minimum when salary is available.
- Visa sponsorship is required by the user but explicitly unavailable.
- Must-have skills are explicitly absent when the job is skill-specific.

Hard filters should preserve uncertain jobs if they otherwise look promising. For example, if visa status is not mentioned, do not reject the job unless the user configured strict rejection.

## Scoring Goals

Scoring should answer:

- Does the job match the user's actual experience?
- Does it match the user's stated preferences?
- Are the strongest requirements present in the user's resume?
- Are missing requirements minor, major, or disqualifying?
- Is the posting fresh enough to deserve immediate attention?

## Success Metrics

Track these once analytics exist:

- Time from source posting to detection.
- Time from detection to alert.
- Alert open rate.
- Saved or applied rate.
- Dismissed-as-irrelevant rate.
- Duplicate alert rate.
- User-rated match quality.

## V1 Constraints

- Prefer official ATS feeds and stable public endpoints.
- Use polite request intervals and source-specific rate limits.
- Store enough raw data to debug matching, but avoid retaining unnecessary sensitive content.
- Make the scoring logic explainable.
- Keep the alert threshold conservative until user feedback exists.

