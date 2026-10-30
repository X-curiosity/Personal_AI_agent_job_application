# What to use to build a custom StartupMap + Jack & Jill

Reverse-engineering-informed build-stack assessment using the REA browser observation provider (Chrome DevTools Protocol) plus static inspection of the shipped bundles.

## Method

- **REA MCP is now connected** in this session. I launched the Playwright-bundled headless Chromium (`chrome-headless-shell`) with `--remote-debugging-port` and inspected both targets with REA's `inspect_web_page` (CDP, passive — JavaScript is parsed/observed, not executed by REA).
- **StartupMap evidence:** REA `inspect_web_page` result `ev_6ad8eb0247683e53bfd413f4ae8e18c7545dd653eb29b40cfe271a0d79dd50eb` (origin `https://startupmap.one`).
- **Jack & Jill evidence:** REA `inspect_web_page` result for `https://www.jackandjill.ai/jack` (origin `https://www.jackandjill.ai`).
- Static bundle inspection of StartupMap's public `index-*.js` was also used to enumerate referenced API routes.
- Every finding is labeled **observed** (seen by REA/static) versus **inferred** versus **unknown**. No private APIs were called, no credentials extracted, no runtime mutations performed. The headless browser was only used for passive page observation.

## 1. StartupMap — observed stack

| Component | Evidence (REA CDP) | Status |
| --- | --- | --- |
| UI framework | Main bundle `static/index-D1jAOKa0.js` (hashed Vite output), React markers | Observed — React |
| Build tool | `index-*.js` / `index-*.css` hashed names | Observed — Vite |
| Map | `static/mapbox-CWlMv1cL.js` chunk | Observed — Mapbox GL JS |
| Analytics | `static/posthog-DlmmmYUv.js`, `cairn/array/*/config.js`, `static/analytics-DlcoREUq.js` | Observed — PostHog + custom chunk |
| Attribution/surveys | `cairn/static/surveys.js`, `web-vitals.js`, `dead-clicks-autocapture.js` | Observed — Cairn |
| Edge/CDN | `cdn-cgi/challenge-platform/scripts/jsd/main.js` | Observed — Cloudflare (challenge + CDN) |
| Backend/storage | Logo URLs on `…supabase.co/storage/v1/object/public/startup-logos/…` (earlier observation) | Observed — Supabase storage |

### Public API surface referenced in the bundle

Route strings present in the shipped JavaScript (static observation; not called):

- **Jobs/companies:** `/api/jobs`, `/api/jobs/summary`, `/api/startups`, `/api/funds/`
- **User:** `/api/me`, `/api/me/profile`, `/api/me/preferences`, `/api/me/answers`, `/api/me/board`
- **Matching:** `/api/me/matches`, `/api/me/match-count`, `/api/me/match-emails`
- **Following/saving:** `/api/me/following`, `/api/me/follows`, `/api/me/saved-jobs`, `/api/me/org-search`
- **Email:** `/api/broadcast`, `/api/email-subscribers-count`, `/api/me/newsletter`, `/api/me/follow-emails`
- **Utilities:** `/api/logo-proxy`, `/api/me/merge`, `/api/me/share`, `/api/save-user-settings`

### Interpretation

StartupMap is a **React SPA (Vite) + Mapbox GL JS**, fronted by Cloudflare, using PostHog/Cairn analytics, with a **Supabase-backed API** exposing jobs, companies, funds, saved-jobs/follows, a "Match me" onboarding, and match emails. The map is Mapbox-based (consistent with its stated "Mapbox" provider).

## 2. Jack & Jill (`/jack`) — observed stack

| Component | Evidence (REA CDP) | Status |
| --- | --- | --- |
| Framework | `/_next/static/immutable/chunks/*.js` + `turbopack-*.js` | Observed — Next.js App Router, Turbopack build |
| Hosting/analytics | `/_vercel/insights/script.js` | Observed — Vercel + Vercel Insights |
| Typography | Preloaded `ABCDiatype*`, `ABCMarist*` woff2 | Observed — Fontshare brand fonts |
| Two-sided traction | Customer logos on `/jack`: Tavus, Maze, Ramp, Corgi, Multiverse, Strala, Attio | Observed — employer/customer references |
| Page purpose | `/jack` title: "get a direct introduction to jobs you actually want" | Observed — candidate-side product |

Jack & Jill is a **Next.js + Turbopack app on Vercel** (with Vercel Insights) presenting a candidate-side "Jack" flow and company-side "Jill" marketplace. Its internal matching and introduction logic remains **unknown** from the public page.

## 3. What we already use vs. what each product implies

| Need | Our current choice | StartupMap uses | Jack & Jill uses |
| --- | --- | --- | --- |
| Map renderer | MapLibre GL JS + OpenFreeMap | Mapbox GL JS | n/a |
| Frontend (map site) | Vanilla JS static | React + Vite | Next.js (Turbopack) |
| Backend/data | Python + SQLite (local), Supabase (hosted scaffold) | Supabase-backed API | Unknown, on Vercel |
| Jobs | Official ATS connectors | `/api/jobs` service | "scans millions of jobs" |
| Matching | Deterministic skill coverage | `/api/me/matches` | Unknown proprietary |
| Analytics | None public | PostHog + Cairn + Cloudflare | Vercel Insights |

We do **not** need to copy their stacks to copy their products. Our MapLibre choice is valid; the gap is data services and the matching workflow, not the renderer.

## 4. Recommended stack to build the custom version

### Public map + browsing (StartupMap equivalent)

| Layer | Recommendation |
| --- | --- |
| Renderer | Keep **MapLibre GL JS** (no Mapbox migration needed) |
| Tiles/style | Keep **OpenFreeMap**; evaluate a paid provider only when coverage/style demands it |
| Frontend | **React + Vite** once the static vanilla JS outgrows maintainability |
| Data API | **Supabase** PostgREST/RPC for companies, jobs, offices, followers |
| Asset serving | Self-host logos (already done); a bounded, allowlisted logo-proxy only if needed |
| Hosting | Vercel static + Supabase |

### Matching + private agent (Jack & Jill equivalent)

| Layer | Recommendation |
| --- | --- |
| Frontend | **Next.js (App Router) on Vercel** for the authenticated workspace |
| Auth | Supabase Auth (magic link + optional LinkedIn OIDC) |
| Storage | Supabase private storage for CVs |
| Job ingestion | Hosted Python worker + official ATS connectors + employer self-serve (see employer plan) |
| Matching | Deterministic evidence coverage now; add grounded LLM only for nuanced interpretation |
| Queue | Postgres-backed durable queue (or managed queue if load justifies it) |
| Notifications | Supabase/email adapter with opt-in digests |

### Two-sided marketplace (later)

Jack & Jill's "direct introduction, paid on hire" requires a **company-side product and recruiter participation**. That is a separate employer surface (see [employer integration plan](EMPLOYER_INTEGRATION_PLAN.md)), not something the matching model alone can produce. The customer logos observed on `/jack` reflect that employer participation, not an automation trick.

## 5. Observed feature surface → build items

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
- Whether StartupMap's `/api/*` routes are serverless functions, a Supabase API, or another backend (only Supabase storage and route strings are observed).
- The exact cost/licensing of any hosted map, geocoding or model service we might adopt — provider terms change and must be checked at decision time.
- Any access tokens, credentials, or private coordinates (deliberately not extracted). PostHog's embedded `phc_…` value is a public analytics key, not a secret to rotate.

## References

- [Unified implementation plan](IMPLEMENTATION_PLAN.md) — map details and the autonomous job agent.
- [Employer integration plan](EMPLOYER_INTEGRATION_PLAN.md) — the company-side "Jill" surface.
- [StartupMap reverse-engineering notes](STARTUPMAP_RE_NOTES.md) — prior static evidence on the seeker join flow.
- [App architecture and automation](APP_ARCHITECTURE_AND_AUTOMATION.md) — current implementation and constraints.
