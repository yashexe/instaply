# Matching and Scoring

## Goal

Score each new job against the user's resume and preferences, then alert only on strong matches with clear reasons.

## Inputs

### Candidate Profile

Derived from resume and user preferences:

- Target role families.
- Current and past titles.
- Years of experience.
- Seniority level.
- Core skills.
- Secondary skills.
- Tools and technologies.
- Domains and industries.
- Education and certifications.
- Work authorization and visa needs.
- Preferred locations and remote policy.
- Salary expectations.
- Excluded companies, roles, or keywords.

### Job Posting

Derived from source ingestion:

- Title.
- Company.
- Department/team.
- Location and remote policy.
- Description.
- Responsibilities.
- Required qualifications.
- Preferred qualifications.
- Compensation, when available.
- Visa or sponsorship language, when available.
- Seniority signals.

## Matching Pipeline

1. Normalize text.
2. Extract structured job requirements.
3. Apply hard filters.
4. Score weighted fit dimensions.
5. Generate explanation.
6. Decide alert priority.
7. Store match trace.

## Hard Filter Rules

Hard filters should return one of:

- `pass`
- `fail`
- `uncertain`

Suggested rules:

- Role family mismatch: fail when clearly unrelated.
- Seniority mismatch: fail when clearly too junior or too senior.
- Location mismatch: fail when role is explicitly incompatible.
- Salary mismatch: fail when salary maximum is below user minimum.
- Visa mismatch: fail when user needs sponsorship and posting explicitly says unavailable.
- Excluded keyword/company: fail.

Uncertain should usually continue to scoring with a penalty instead of rejecting the job.

## Score Dimensions

Use a 0 to 100 score. Suggested V1 weights:

| Dimension | Weight | Description |
| --- | ---: | --- |
| Role/title fit | 20 | Target role family, title similarity, seniority alignment |
| Required skills fit | 25 | Required skills found in resume/profile |
| Experience fit | 15 | Years, scope, ownership, domain depth |
| Preferences fit | 15 | Location, remote, salary, visa, employment type |
| Domain/company fit | 10 | Industry, product area, company stage, user interest |
| Preferred skills bonus | 10 | Nice-to-have skills and tools |
| Freshness/urgency | 5 | Newly posted or newly detected |

## Alert Thresholds

Suggested initial thresholds:

- `85-100`: immediate alert, very strong match.
- `75-84`: immediate alert if source or company is high priority.
- `65-74`: save for digest or review queue.
- `<65`: do not alert.

These thresholds should become user-configurable after V1.

## Explanation Format

Each match should produce:

- `summary`: one sentence.
- `matching_reasons`: 3 to 5 bullets.
- `missing_requirements`: 0 to 5 bullets.
- `uncertainties`: facts the system could not verify.
- `score_breakdown`: dimension scores.

Example:

```json
{
  "score": 88,
  "summary": "Strong backend/product engineering fit with close alignment on TypeScript, distributed systems, and startup experience.",
  "matching_reasons": [
    "Title aligns with target Product Engineer and Full Stack Engineer roles.",
    "Required TypeScript, React, Node.js, and PostgreSQL appear in the resume.",
    "Posting asks for 4+ years and profile indicates 5 years of relevant experience."
  ],
  "missing_requirements": [
    "Kubernetes is mentioned as preferred but not found in the resume."
  ],
  "uncertainties": [
    "Visa sponsorship is not mentioned in the posting."
  ]
}
```

## Resume Parsing Guidance

The parser should produce structured facts with confidence:

```json
{
  "skills": [
    { "name": "TypeScript", "category": "language", "confidence": 0.98 },
    { "name": "PostgreSQL", "category": "database", "confidence": 0.94 }
  ],
  "roles": [
    {
      "title": "Software Engineer",
      "company": "ExampleCo",
      "start_date": "2021-06",
      "end_date": "2024-12",
      "summary": "Built backend services and product features."
    }
  ]
}
```

Avoid over-inference. If a resume says "used Kubernetes once", do not treat Kubernetes as a core skill unless the user confirms it.

## LLM Use

Use LLMs for:

- Extracting structured requirements from messy descriptions.
- Explaining fit in natural language.
- Identifying equivalent skills or adjacent experience.
- Summarizing missing requirements.

Use deterministic code for:

- Source polling.
- Deduplication.
- Hard filters.
- Threshold decisions.
- Alert idempotency.

## Match Trace

Store enough detail to debug why a job did or did not alert:

- Profile version used.
- Job version used.
- Hard filter outcomes.
- Dimension scores.
- Extracted job requirements.
- Explanation object.
- Final alert decision.

## Quality Checks

Before trusting alerts, test with:

- A perfect-fit job.
- A good job with one missing preferred skill.
- A role with similar keywords but wrong seniority.
- A remote role that excludes the user's country.
- A duplicate repost.
- A vague posting with missing salary and visa data.

