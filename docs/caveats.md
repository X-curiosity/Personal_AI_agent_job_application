# Caveats & remediation options

Generated 2026-10-31 · scope: company expansion (100+ companies) · skill: build-review-verify

| # | Severity | Location | Caveat | Simplest fix | Docs | Status |
|---|---|---|---|---|---|---|
| 1 | P2 | `scripts/export_public_jobs.py` | ~20 sources fail per export (rate limits, 404s), slightly shrinking the snapshot | add retry/backoff per source, keep partial results | https://urllib3.readthedocs.io/en/stable/reference/urllib3.util.html | defer |
| 2 | P1 | ingestion path | Public companies mostly use Workday/SuccessFactors — no public API, so ATS detection finds few | browser-rendered ingestion or employer self-serve (`submit_job.py`) | https://developers.workable.com / https://developer.workday.com | defer |
| 3 | P2 | `register_job_sources.py` | auto-detection can misattribute a partner's board | name-match guard + manual disable (already in place) | — | no action (mitigated) |
| 4 | P2 | `people_finder.py` / `people.json` | people cards use initials, not photos (LinkedIn auth-gates photos) | no reliable public source; keep monograms | https://www.linkedin.com/help/linkedin/answer/a1341387 | no action |
| 5 | P1 | `vercel-site/jobs-core.mjs` | companyType casing was inconsistent (`Public` vs `public`), breaking the type filter | normalized to title case in `readJobs` | — | fix now (done) |
| 6 | P2 | `hosted_matching.py`, `jobs-core.mjs` | snapshot outgrew the old 500-job cap | raised `MAX_JOBS`/readJobs cap to 5000 | — | fix now (done) |
| 7 | P2 | `fetch_feed_openings` | feed connector unit-tested but not yet pointed at a live regional feed | register a real `Feed` source URL | https://www.rssboard.org/rss-specification | defer |

## Notes

- Africa remains ~0 roles because African employers rarely use Greenhouse/Lever/Ashby; this is a data-access gap, not a bug (see `docs/IMPLEMENTATION_PLAN.md`).
- Scoring is skill overlap, not a hiring probability. Directory presence ≠ vacancy; HQ ≠ job location.
- No LinkedIn scraping/automation is performed; people contacts are surfaced from public web search and open the profile link only.
