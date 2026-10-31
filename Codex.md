# Hired — repository context

**Hired** = a public job/company map + a private local career app, sharing one company/jobs data model.

## Three surfaces

| Surface | What | Where |
| --- | --- | --- |
| Public map & jobs | Global company directory + source-linked roles (full-page map, country flags, per-role CV drag-drop, structured job descriptions, people-to-contact cards) | `vercel-site/` (deployed on Vercel) |
| Local app | CV analysis, role folders + deterministic agent, PDF project ideas, reviewed auto-apply | `src/tau_job_application/` |
| Hosted MVP | Supabase accounts/CV scaffold — **not live** | `supabase/`, `hosted_*.py` |

## Current numbers

- **10,247 companies** (global directory), 8,800+ self-hosted logos.
- **~1,066 roles across ~203 companies** from ~256 auto-detected ATS boards + feed + employer submissions (startups, private, and public companies).
- Coverage is bounded by which employers expose a public ATS API — see [docs/INGESTION_BOTTLENECKS.md](docs/INGESTION_BOTTLENECKS.md).

## Run / test

```bash
# public site preview
PYTHONPATH=src .venv/bin/python scripts/serve_public_site.py --port <port>
# tests
.venv/bin/python -m pytest -q
node --test tests/test_public_jobs_core.mjs tests/test_public_map_core.mjs
# local app
uv sync --no-editable --reinstall-package tau-job-application && ./run.sh
```

## Job sources

`scripts/register_job_sources.py` auto-detects ATS boards from the catalogue (`--regions`, `--only-startups`); `scripts/export_public_jobs.py --limit N` rebuilds the snapshot; `scripts/submit_job.py` adds an employer submission; `.github/workflows/refresh-jobs.yml` refreshes daily at 06:00 UTC.

## Authentication

Private features (save jobs, CV folders, reviewed applications) need an account. The hosted scaffold already implements **passwordless email + LinkedIn OIDC** sign-in (`hosted_auth.py`, `hosted_ui.py`) but is **not live** — it needs LinkedIn OIDC app credentials, email delivery, and deployment. LinkedIn sign-in is identity only; it grants **no** people-search, messaging, or profile-photo access (LinkedIn restricts those). The public site stays account-free for browsing and local matching.

## Honest limits

- Africa ≈ 0 roles; Asia/Oceania thin — most employers there don't use Greenhouse/Lever/Ashby.
- CV matching is skill overlap, not a hiring probability. Directory ≠ vacancy; HQ ≠ job location.
- No LLM in core flows, no LinkedIn scraping, no invented jobs. Auto-apply and the agent never send without explicit approval.

## Docs

- [Implementation plan](docs/IMPLEMENTATION_PLAN.md) · [Architecture Q&A](docs/APP_ARCHITECTURE_AND_AUTOMATION.md) · [Design questions](docs/DESIGN_QUESTIONS.md) · [Ingestion bottlenecks](docs/INGESTION_BOTTLENECKS.md) · [Hosted MVP](docs/HOSTED_MVP.md)
- Module context: [src/tau_job_application/codex.md](src/tau_job_application/codex.md)
