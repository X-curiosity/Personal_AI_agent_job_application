# What to use to build a custom StartupMap + Jack & Jill

Reverse-engineering-informed build-stack assessment. This uses static inspection of the public sites' shipped assets, not a completed REA MCP/CLI run.

## Method and honesty

- **REA tooling was not usable in this session.** The `rea-agents@6.8.0` diagnostic reported an unsupported Node `26.7.0` (needs 26.12.1+ or 22/24) and missing `pi` MCP registration. Native engines (Hopper/Ghidra/IDA/JADX) are irrelevant to these web targets and were not configured. I did not install or upgrade Node, register MCP servers, or attempt to run REA against these sites.
- Instead I performed **static inspection of the public homepages and StartupMap's public JavaScript bundle** (fetched with a browser User-Agent). Static bundle inspection needs no native engine.
- Every finding below is labeled **observed** (seen in shipped HTML/JS) versus **inferred** (reasonable interpretation) versus **unknown** (not verifiable from the public surface).
- I did **not** call their private APIs, bypass login, extract access tokens, or observe runtime behavior. API route strings seen in a bundle are references, not proof of behavior.

## 1. StartupMap — observed stack

| Component | Evidence | Status |
| --- | --- | --- |
| UI framework | `react`, `react-dom`, `createRoot`, `__react` markers in `/static/index-*.js` | Observed — React |
| Build tool | Hashed `/static/index-D1jAOKa0.js` + `/static/index-*.css`, `__vite` markers | Observed — Vite |
| Map | `/static/mapbox-CWlMv1cL.js` chunk, `mapboxgl-marker` | Observed — Mapbox GL JS |
| Backend/storage | Earlier logo URLs on `…supabase.co/storage/v1/object/public/startup-logos/…` | Observed — Supabase (storage at minimum) |
| Hosting | Static `/static/` asset paths; no framework server fingerprint on the public page | Inferred — static SPA likely fronted by a CDN/static host |

### Public API surface referenced in the bundle

These route strings appear in the shipped JavaScript. They reveal the product's feature surface; I have not called them:

- **Jobs/companies:** `/api/jobs`, `/api/jobs/summary`, `/api/startups`, `/api/funds/`
- **User state:** `/api/me`, `/api/me/profile`, `/api/me/preferences`, `/api/me/answers`, `/api/me/board`
- **Matching:** `/api/me/matches`, `/api/me/match-count`, `/api/me/match-emails`
- **Following/saving:** `/api/me/following`, `/api/me/follows`, `/api/me/saved-jobs`, `/api/me/org-search`
- **Email/notifications:** `/api/broadcast`, `/api/email-subscribers-count`, `/api/me/newsletter`, `/api/me/follow-emails`
- **Utilities:** `/api/logo-proxy`, `/api/me/merge`, `/api/me/share`, `/api/save-user-settings`

### What this tells us

StartupMap is a **React SPA + Mapbox GL JS + Supabase-backed API**, with company/job browsing, a saved-jobs/following system, a "Match me" onboarding (answers/board), match emails, and a logo proxy. Its map is Mapbox-based, which aligns with its stated "Mapbox" provider and with its free/paid positioning.

## 2. Jack & Jill — observed stack

| Component | Evidence | Status |
| --- | --- | --- |
| Framework | `/_next/static/immutable/chunks/*.js`, `turbopack-*.js` | Observed — Next.js App Router built with Turbopack |
| Hosting | Image URLs carry `?dpl=dpl_…` (Vercel image optimization fingerprint) | Observed — Vercel |
| Typography | Preloaded `ABCDiatype*` and `ABCMarist*` woff2 (Fontshare) | Observed — custom brand fonts |
| Two-sided product | Homepage copy describes candidate "Jack" and recruiter "Jill", direct introductions, "paid by companies only when you get hired" | Observed — marketplace positioning |

Jack & Jill is a **Next.js + Turbopack app on Vercel** with a candidate/company marketplace. Its internal matching and introduction logic is **unknown** from the public page.

## 3. What we already use vs. what each product implies

| Need | Our current choice | StartupMap uses | Jack & Jill uses |
| --- | --- | --- | --- |
| Map renderer | MapLibre GL JS + OpenFreeMap | Mapbox GL JS | n/a |
| Frontend (map site) | Vanilla JS static | React + Vite | Next.js (Turbopack) |
| Backend/data | Python + SQLite (local), Supabase (hosted scaffold) | Supabase-backed API | Unknown, on Vercel |
| Jobs | Official ATS connectors | `/api/jobs` service | "scans millions of jobs" |
| Matching | Deterministic skill coverage | `/api/me/matches` | Unknown proprietary |

We do **not** need to copy their stacks to copy their products. Our MapLibre choice is valid; our remaining gap is not the renderer but the data services and matching workflow.

## 4. Recommended stack to build the custom version

### Public map + browsing (StartupMap equivalent)

| Layer | Recommendation |
| --- | --- |
| Renderer | Keep **MapLibre GL JS** (no migration to Mapbox needed) |
| Tiles/style | Keep **OpenFreeMap** for now; evaluate a paid provider only when coverage/style demands it |
| Frontend | **React + Vite** (adopt when the static vanilla JS outgrows maintainability) or stay static until then |
| Data API | **Supabase** PostgREST/RPC for companies, jobs, offices, followers |
| Asset serving | Self-host logos (already done) with a bounded, allowlisted logo-proxy if needed |
| Hosting | Vercel static + Supabase |

### Matching + private agent (Jack & Jill equivalent)

| Layer | Recommendation |
| --- | --- |
| Frontend | **Next.js (App Router) on Vercel** for the authenticated workspace |
| Auth | Supabase Auth (magic link + optional LinkedIn OIDC) |
| Storage | Supabase private storage for CVs |
| Job ingestion | Hosted Python worker + official ATS connectors + employer self-serve (see employer plan) |
| Matching | Deterministic evidence coverage now; add a grounded LLM only for nuanced interpretation |
| Queue | Postgres-backed durable queue (or a managed queue if load justifies it) |
| Notifications | Supabase/email adapter with opt-in digests |

### Two-sided marketplace (later)

Jack & Jill's "direct introduction, paid on hire" requires a **company-side product and recruiter participation**. That is a separate employer surface (see [employer integration plan](EMPLOYER_INTEGRATION_PLAN.md)), not something the matching model alone can produce.

## 5. Observed feature surface → build items

From the StartupMap bundle and Jack & Jill homepage, the concrete features to build:

1. **Company/startup browser** with filters (city, sector, funding stage, hiring status).
2. **Open-roles list** with counts and source links.
3. **Company profile** with logo, description, website, location, stage.
4. **Follow company / save job** (requires accounts).
5. **"Match me" onboarding** (role areas, experience, work style, location, stage, industries).
6. **Match count + match email** (opt-in digest).
7. **Candidate "Jack"** — preferences, proactive discovery, explanations.
8. **Recruiter "Jill"** — employer side, mutual-interest introductions (later, gated by participation).

## 6. What remains unverified

- StartupMap's and Jack & Jill's backend architecture, data pipelines and matching models (not observable from public bundles).
- Whether StartupMap's `/api/*` routes are serverless functions, a Supabase API, or another backend (only the Supabase storage host and route strings are observed).
- The exact cost/licensing of any hosted map, geocoding or model service we might adopt — provider terms change and must be checked at decision time.
- Any access tokens, credentials, or private coordinates (deliberately not extracted).

## References

- [Unified implementation plan](IMPLEMENTATION_PLAN.md) — map details and the autonomous job agent.
- [Employer integration plan](EMPLOYER_INTEGRATION_PLAN.md) — the company-side "Jill" surface.
- [StartupMap reverse-engineering notes](STARTUPMAP_RE_NOTES.md) — prior static evidence on the seeker join flow.
- [App architecture and automation](APP_ARCHITECTURE_AND_AUTOMATION.md) — current implementation and constraints.
