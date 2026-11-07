# Implementations

A running report of changes made to Hired (the startup & job map).

## How to read this
- Latest changes are at the top.
- Each entry: what changed, why, and where.

---

## 2026-11-08 — Logo storage optimization (PNG + smaller)

- Converted all raster logos (ICO/JPEG/WEBP) to **PNG**, resized to ≤128px, and optimized.
- **Rasterized the 143 SVG logos to PNG** — some SVGs used external refs / fonts / `currentColor` and failed to render in `<img>` tags; PNG guarantees they all render.
- Result: every logo is now a **128px PNG** (606 files, **3.9 MB**, 0 broken images).
- Files: `scripts/optimize_logos.py`, `scripts/rasterize_svgs.py`.

---

## 2026-11-07 — Per-role tags: area, experience, workplace, time

- Each role now shows four tags instead of just the area:
  - **Area** (Engineering, Sales, …) — from `type`.
  - **Experience** — "1-3 years" (range) or "+3 years" (minimum), derived from the description.
  - **Workplace** — Remote / Hybrid / On-site.
  - **Time** — Full-time / Part-time / Internship.
- Removed the ATS (`scrape_method`) from the UI; cleaned the area tag ("Other" and "Internship" are no longer treated as areas — internships map to the **time** tag).
- Deleted the obsolete `synthetic-ats` Vercel project (its root directory no longer existed, failing every push).
- Files: `scripts/export.py` (`extract_requirements` + `type` cleanup), `vercel-site/app.js` (`jobTags`).

---

## 2026-11-07 — Requirements summary, complete funding-stage filter

**Filter — company type vs funding stage**
- Fixed the company filter to match the intended model:
  - **Public** → that's it (no funding stage; they IPO'd).
  - **Private** → funding stages: Pre-seed, Seed, Series A–F, Bootstrapped, Growth.
- The `stage` filter now shows the **full fixed list** of funding stages (not just those present in data).
- Files: `vercel-site/app.js` (`FUNDING_STAGES`, `STAGE_LABELS`), `scripts/export.py` (split `stage` → `company_type` + `stage`).

**Job requirements summary**
- Job descriptions are now summarized into structured **Requirements** (instead of just dumping the raw advert):
  - **Skills** — keyword-extracted (Python, React, AWS, …), shown as chips.
  - **Experience** — "X+ years".
  - **Degree** — Bachelor's / Master's / PhD.
- File: `scripts/export.py` (`extract_requirements`), `vercel-site/app.js` (`renderJob`), `vercel-site/styles.css`.

**Logo double-check**
- Audited all company logos; replaced 11 wrong ones (BambooHR/Odoo board favicons) with the real company logos from their own domains / Wikipedia.
- Result: 571 proper logos (144 SVG + 427 ≥64px); 52 remain as the company's own small favicon (correct, low-res).
- Files: `ingest/enrich.py`, `scripts/refetch_logos.py`, `vercel-site/data/logos/*`.

---

## 2026-11-07 — Employer review with AI check; jobs/map split; dashboard

**AI review check on submissions**
- When a company submits a role, the serverless function fetches the apply URL and records an auto-check note (HTTP status + whether the page references the role title).
- The note shows in the review script as `AI check: …`.
- Files: `vercel-site/api/submit.js`, `scripts/review_submissions.py`, `supabase/migrations/job_submissions.sql` (`review_note` column).

**Jobs vs Map split**
- "Jobs" → the list only (full page, no map). "Map" → the map only (full screen).
- Files: `vercel-site/app.js`, `vercel-site/index.html`, `vercel-site/styles.css` (`data-mode`).

**Applications dashboard**
- "Track this role" button on each role; `#/dashboard` lists tracked roles with status (Saved → Applied → Interview → Offer → Rejected) + remove. Stored in `localStorage`.
- Files: `vercel-site/app.js`, `vercel-site/index.html`, `vercel-site/styles.css`.

---

## 2026-11-07 — Country flags on the map

- At globe/continent zoom the map shows a **flag per country** (emoji flag + role count); clicking a flag zooms into that country, resolving to company pins.
- Files: `vercel-site/app.js` (`countryFlag`, `renderCountryFlags`), `vercel-site/styles.css`.

---

## 2026-11-06 — Employer submission form + review queue

- "Post a role" form (`#/submit`) → serverless function → Supabase `job_submissions` (status `pending`).
- Local `scripts/review_submissions.py` approves/rejects; approved roles become `scrape_method: submission`.
- Files: `vercel-site/api/submit.js`, `scripts/review_submissions.py`, `supabase/migrations/job_submissions.sql`.

---

## 2026-11-06 — Ingestion backend (rebuild from zero)

- ATS feed fetchers: Greenhouse, Lever, Ashby, Workable, Recruitee, Breezy, SmartRecruiters, Personio, Teamtailor, Welcome to the Jungle, HiBob, Join, Dover, Kula — each tagged with `scrape_method`.
- Generic `httpx` (SSR) and `playwright` (JS) scrapers for custom career pages.
- Company catalogue: 607 companies, 10,571 roles.
- Files: `ingest/ats.py`, `ingest/pipeline.py`, `ingest/store.py`, `scripts/*`.

---

## 2026-11-06 — Frontend rebuild (startupmap-style)

- MapLibre globe + paper-toned positron basemap, company map, role list + filters, per-role pages.
- Design tokens: Fraunces + DM Sans, `#fffaf3` / `#2e2922` / `#b4432f`.
- Files: `vercel-site/*`.
