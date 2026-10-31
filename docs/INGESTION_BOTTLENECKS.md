# Job ingestion bottlenecks: why coverage is bounded

Answers to "why can't we just grab every startup and every public company's roles?"

## Short answer

**Storage is not the bottleneck. Data access is.** The ceiling is set by which employers expose a machine-readable public job feed, plus how fast and accurately we can discover and refresh those feeds.

## Current state

- Company directory: 10,247 companies with websites and locations.
- Job sources: ~99 registered ATS boards (Greenhouse/Lever/Ashby/Workable/Recruitee/Feed), mostly auto-detected from the catalogue.
- Public snapshot: ~454 roles across ~67 companies (the rest of the detected companies currently have no geocodable roles in scope).

## Bottleneck 1 — which ATS a company uses (the real ceiling)

We only ingest from ATS platforms that expose a **clean public API**:

| Platform | Public API? | Notes |
| --- | --- | --- |
| Greenhouse | Yes | `boards-api.greenhouse.io/v1/boards/<token>/jobs` |
| Lever | Yes | `api.lever.co/v0/postings/<site>` |
| Ashby | Yes | `api.ashbyhq.com/posting-api/job-board/<board>` |
| Workable / Recruitee | Yes (feeds/partial) | Workable via pages/feeds; Recruitee via feed |
| Workday | **No** | HTML app; no public JSON API — needs browser rendering or scraping (we avoid) |
| SuccessFactors / iCIMS / Taleo | **No** | Same: JS-heavy, no public API |

**Many public companies (and plenty of startups) run Workday or SuccessFactors.** Those can't be ingested through the current ATS-only path without either (a) browser-rendered scraping we've deliberately avoided, or (b) an employer-provided feed/self-serve submission. This — not storage — is why coverage stops.

## Bottleneck 2 — discovering which ATS a company uses

`register_job_sources.py` fetches a company's homepage + `/careers` + `/jobs` and pattern-matches ATS board URLs. Constraints:

- **Time/rate limits:** thousands of companies × ~4 fetches each, with politeness and timeouts.
- **Blocks:** Cloudflare challenges, robots.txt, JS-only pages that return no ATS link in the raw HTML.
- **False positives:** a partner's board link (e.g. "built on Benchling") can be misattributed; mitigated by the name-match guard and manual disabling.

## Bottleneck 3 — refresh and freshness

Once registered, each source is fetched on the daily schedule. Hundreds of boards means hundreds of API calls; failures, closures, and stale data need reconciliation. This is operational cost, not storage.

## Why storage is a non-issue

Rough upper bound:

```text
10,000 companies × ~50 roles × ~3 KB per role ≈ 1.5 GB worst case
```

In practice the bounded public snapshot is a few hundred KB to a few MB, and the private local app stores CVs and targets in a small SQLite file. Postgres/Supabase would handle the full job table with room to spare. **Storage does not limit us.**

## What would actually raise coverage

1. **Scan more companies (already running):** `register_job_sources.py --regions Europe,UnitedStates,Asia,... --limit N` — detects more Greenhouse/Lever/Ashby boards, including public companies. Cheap; hit the ATS ceiling quickly.
2. **Feed sources:** point `Feed` rows at public RSS/Atom/JSON feeds (regional boards, Workable/Recruitee feeds).
3. **Employer self-serve:** startups/companies submit jobs directly (`submit_job.py` / a hosted form) — bypasses the ATS problem entirely.
4. **Browser-rendered ingestion (Workday etc.):** highest coverage, highest cost/risk; requires a headless worker, consent, and careful rate limiting. Not currently done.

## Recommendation

Treat the ATS registry + feed + self-serve as the production path. Add browser-rendered Workday/SuccessFactors ingestion only if the measured gap justifies the operational cost and the terms of service allow it.
