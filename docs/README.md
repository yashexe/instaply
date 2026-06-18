# Instaply Job Discovery Bot Docs

This docs pack is written for an agentic AI coding assistant that will build Instaply as a fast job discovery and alerting product.

Instaply is not a full auto-application bot. The first version should learn a user's resume and job preferences, monitor near-source job feeds, score new roles against the user's background, and send immediate alerts for strong matches.

## Recommended Reading Order

1. [Product Brief](product-brief.md)
2. [System Architecture](system-architecture.md)
3. [Source Ingestion](source-ingestion.md)
4. [Matching and Scoring](matching-and-scoring.md)
5. [Data Model](data-model.md)
6. [Implementation Roadmap](implementation-roadmap.md)
7. [Agent Build Guide](agent-build-guide.md)
8. [UI Product Spec](ui-product-spec.md)
9. [UI Architecture](ui-architecture.md)
10. [UI API Contract](ui-api-contract.md)
11. [UI Implementation Plan](ui-implementation-plan.md)

## MVP Definition

The MVP is successful when a user can:

1. Add or upload a resume/profile.
2. Configure target companies, roles, locations, remote preferences, salary needs, visa needs, and must-have skills.
3. Monitor a small set of ATS-backed sources such as Greenhouse, Lever, and Ashby.
4. Detect new postings without duplicate alerts.
5. Score each posting against the user's profile.
6. Receive a notification with the job link, match score, matching reasons, missing requirements, and freshness.

## Non-Goals For V1

- Do not auto-apply to jobs.
- Do not submit forms on behalf of the user.
- Do not scrape aggressively or bypass access controls.
- Do not build a broad job board clone.
- Do not optimize for massive crawling before the matching and alert experience works.

## Product Principle

Speed matters, but relevance matters more. A user should trust that an Instaply alert is worth opening immediately.
