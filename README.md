# Hired — global startup & job map

A free map of companies hiring now, with live roles pulled from **public career feeds**.
The ingestion backend mirrors [startupmap.one](https://startupmap.one)'s approach:
each job is tagged with a `scrape_method` — `ats:<vendor>` (structured public feed),
`httpx` (generic scraping), or `playwright` (headless browser).

## Layout

- `ingest/` — Python ingestion backend (ATS detection, feed fetchers, role classifier, SQLite store).
- `scripts/` — `seed.py` (curated seed companies), `export.py` (SQLite → public JSON).
- `vercel-site/` — static frontend (MapLibre globe, company map, role list + filters, per-role pages). Deploy root.

## Run

```bash
python3 -m venv .venv && .venv/bin/pip install httpx
.venv/bin/python scripts/seed.py      # fetch live roles from public ATS feeds
.venv/bin/python scripts/export.py    # write vercel-site/data/*.json
(cd vercel-site && python3 -m http.server 8000)   # preview
```

## Honest limits

- Only companies that expose a public ATS feed (Greenhouse / Lever / Ashby / Workable / Recruitee / Breezy / SmartRecruiters) are reachable without scraping. Workday / SuccessFactors employers have no public feed.
- Roles are public vacancies, not endorsements. A company in the directory is not necessarily hiring (we surface what the feeds return).
