# Hired: job updates, maps, the GitHub bot, and an autonomous career workspace

This document answers the product questions against the current repository. **Current** means implemented in code, not necessarily verified in production. **Proposed** means work still to build. External documentation is linked at the end.

## 1. How are jobs updated on our website today?

**They are not updated in real time.** The public website reads a saved JSON snapshot, separate from the much larger company directory. Having 10,247 companies does not mean we monitor vacancies at all of them.

Current path:

```text
Reviewed employer boards (Figma, Mistral AI, Cloudflare)
  → public ATS APIs (Greenhouse / Ashby)
  → scripts/export_public_jobs.py
  → vercel-site/data/jobs.json
  → Git commit to main
  → connected Vercel deployment
  → browser loads the snapshot
```

- `.github/workflows/refresh-jobs.yml` requests a run every day at **06:00 UTC**, and permits a manual run from GitHub Actions.
- The exporter selects European, geocodable listings; its default cap is 120, with per-company limits for diversity. This is intentionally not a comprehensive job index.
- The payload contains `exportedAt` and `live: false`. A source timestamp is not necessarily the original publication time.
- If any source fails, or the result is empty, the command exits without overwriting the old jobs JSON. This protects availability but can preserve expired jobs until a successful refresh.
- A changed snapshot is committed; an unchanged snapshot is not. Deployment and browser caching introduce additional delay.
- GitHub schedules can be delayed. A configured workflow is not proof that its latest run or deployment succeeded. This document does not claim those live checks were performed.

**Consequently:** a posting can be roughly a day old before our next scheduled collection, and longer after an outage. Keeping the page open does not itself make it a live feed.

### What we should build for near-real-time updates

Keep Vercel for the interface, but move job ingestion out of Git commits:

1. Maintain a reviewed registry of each employer's ATS, board identifier, permission/terms, pagination and rate limits.
2. Use a scheduled backend worker to poll important boards, initially every 15–60 minutes where permitted. Use slower intervals elsewhere. These are proposed targets, not current guarantees.
3. Accept signed provider webhooks where an employer or integration partner actually grants access. Public board access does **not** grant webhook subscriptions to every employer.
4. Normalize records into a database; upsert on `(source, employer_board, source_job_id)`. Keep content hashes and change history. Cross-posted jobs need conservative deduplication, not just equal titles.
5. Track `first_seen_at`, `last_seen_at`, `source_updated_at`, `last_successful_sync_at`, `status`, and `closed_at` separately.
6. Mark a role closed only after an authoritative closed event or a successful, complete source reconciliation. Failed requests, pagination gaps, and capped previews must never mean “job closed.”
7. Refresh the website through a cached API and periodic client refresh. Add server-sent events or Supabase Realtime only if immediate on-screen notifications are useful. They cannot make stale upstream data fresh.
8. Show “last checked” and stale-source warnings, plus alert on failed or delayed syncs. Recheck the employer page before applying.

Total freshness delay is **employer publication delay + collection delay + processing/cache delay + browser refresh delay**. We can reduce it; we cannot promise instant global coverage.

## 2. How do other job websites do it?

There is no single shared worldwide jobs API. Common models are:

| Website type | Where jobs come from | Main constraint |
| --- | --- | --- |
| Employer career site | Its own ATS database/API | Knows its own jobs, not everyone else's |
| Job board | Employers directly post jobs, purchase listings, or send feeds | Requires employer participation |
| Aggregator | ATS connectors, licensed feeds, partnerships, and permitted crawling | Coverage, freshness, deduplication, licensing |
| Search engine job experience | Crawling and `JobPosting` structured data | Indexing is not guaranteed or instantaneous |

Greenhouse and Lever document public listing APIs. Some ATSs offer authenticated APIs and webhooks, but access is employer-specific. Workday and other systems may require different connectors or partnerships; we should not assume one universal endpoint.

Google's Indexing API lets a site owner notify Google about eligible job-page additions/removals. It is **not** an API from which we can download all Google jobs. Structured data and sitemaps help discovery, not access to an unrestricted global feed.

A production aggregator also spends substantial effort on expired listings, duplicates, remote/hybrid meaning, multilingual locations, employer identity, fraud, and rights to republish descriptions. We should link to official applications and retain source attribution.

## 3. Is there a map API for street-level cities and exact company locations?

See the [unified implementation plan — map](IMPLEMENTATION_PLAN.md#part-i--map-implementation) for the consolidated StartupMap/YC reuse discussion, Google free allowances and restrictions, Leaflet/Mapbox/MapLibre comparison, file-level zoom/marker changes, office enrichment schema, costs and rollout tests.

**Yes, but displaying a map and knowing an office address are different problems.**

### What we use today

- **MapLibre GL JS:** browser renderer, zoom/pan, and markers.
- **OpenFreeMap:** map style/vector tiles, currently `https://tiles.openfreemap.org/styles/positron`.
- **Our company data:** supplies the marker coordinates. Tiles do not discover company addresses for us.
- **Wikidata enrichment:** 1,109 directory companies have domain-linked HQ coordinates in the current export. Other points can be city/country estimates or unmapped.
- `vercel-site/app.mjs` currently sets **`maxZoom: 10`**. This limits the interface; it is not a finished street-level experience. Raising the limit, adjusting marker grouping, and testing navigation are still needed.

Even a coordinate labeled HQ is a sourced claim, not a surveyed guarantee of the entrance, current office, or the workplace of a vacancy. A company can have several offices; remote jobs may have none.

### Three services/data layers to distinguish

| Need | Solution | What it does not establish |
| --- | --- | --- |
| Street map and building detail | MapLibre + suitable tiles, or Mapbox/Google Maps | Which office belongs to a company |
| Address → latitude/longitude | Geocoder, such as a commercial provider or hosted Nominatim | Whether the address is current or relevant to the job |
| Company → verified office | Official contact pages, licensed places data, reviewed business records | Every vacancy's actual workplace |

Street-level map zoom is also different from **street photography**. Street View/Mapillary-style imagery is a separate product with its own coverage, license, and cost.

### Recommended implementation

Keep MapLibre/OpenFreeMap; add an `offices` table. Store company ID, address, office type, source URL, verification date, coordinates, provider, and precision (`building`, `street`, `city`, `country`). Geocode public business addresses and manually review low-confidence matches. Never place a city-centre estimate as if it were an exact office entrance.

Associate a job with an office only when the listing or employer supports the association. Otherwise display its stated city/region or remote status. Do not substitute HQ coordinates for vacancy location.

For thousands of records, choose a provider whose terms allow our volume, storage, and display on this map. Google/Mapbox geocoding and Places have product-specific attribution, caching, and display restrictions; buying an API key is not permission to mix all results freely. Public Nominatim has strict usage rules, including a maximum of one request per second, no client autocomplete, and restrictions on systematic queries. It should not be our unrestricted bulk company-enrichment backend.

## 4. What is the GitHub bot used for here?

**`github-actions[bot]` is an automation identity, not an AI recruiting agent.**

Our workflow checks out `main`, installs dependencies, runs the public job exporter, and commits a changed `jobs.json` using that identity. Its `contents: write` permission lets it push that change. The GitHub-hosted runner executes the code; the bot name identifies the resulting commit.

It does not search LinkedIn, assess CVs, send applications, or continue running between scheduled jobs. Nor is it GitHub Copilot or Dependabot.

GitHub Actions is useful for tests, deployments, and low-frequency public snapshots. It is a poor permanent backend for private per-user queues, CVs, and interactive browser sessions. A bot commit also does not automatically guarantee every downstream workflow runs: events created with `GITHUB_TOKEN` have recursion restrictions. Verify the Vercel integration end to end rather than assuming publication from a green export step.

Private CVs, contact data, credentials, and application histories must never be committed into this public snapshot pipeline.

## 5. How do we build role folders with manual and autonomous modes?

See the [unified implementation plan — job agent](IMPLEMENTATION_PLAN.md#part-ii--autonomous-job-agent-implementation) for source registries, shared ingestion, private recommendation tasks, queue semantics, AI boundaries, cost controls and acceptance tests.

**This is feasible. The missing piece is a hosted, durable workflow—not an impossible AI capability.** Some building blocks already exist: CV parsing, deterministic matching, target/application storage, and a reviewed browser-application runner. They do not yet form this complete hosted product.

### User flow

1. Create a folder such as **“Junior ML — Belgium/remote.”**
2. Set role titles, seniority, locations, work authorization, salary preferences, exclusions, and a selected CV version.
3. Add jobs manually by official URL, or enable discovery from approved sources. The agent recommends additions; user-saved jobs remain distinguishable from auto-discovered ones.
4. Choose **Manual** (“Analyze selected roles now”) or **Autonomous preparation** (scheduled discovery and analysis).
5. Receive an evidence-based fit report. When a usable score is below 70%, receive exactly two targeted project proposals and contact suggestions.
6. Review suggested projects, messages, and applications. Approve each external send or final employer submission separately.
7. Add completed project evidence and rerun matching. A project proposal alone must never increase the CV score.

### Proposed architecture

```text
Authenticated user → folders, role criteria, private CV versions
                                  ↓
Approved sources → ingestion → jobs database
                                  ↓
Scheduler → durable queue → eligibility + evidence matching
                                  ↓
       ≥70%: shortlist       <70%: 2 projects + contact research
                                  ↓
                      user review / edit / approval
                                  ↓
            approved outbound adapter → result + audit trail
```

Use Supabase Postgres/private storage/auth for workspace data and a hosted worker service for background tasks. The existing Streamlit/SQLite app can remain a local tool; a static Vercel page alone cannot reliably execute long-running private workflows or browser automation.

Proposed additional tables: `role_folders`, `folder_jobs`, `cv_versions`, `analysis_runs`, `requirement_evidence`, `project_recommendations`, `contact_candidates`, `outreach_drafts`, `approvals`, and `task_runs`. Existing CV, target, and application tables can be extended rather than duplicated blindly.

Every private row needs owner-scoped authorization. Workers need retries with backoff, leases/timeouts, cancellation, quotas, and deduplication. Bind an analysis to `(user, job content hash, CV version, scoring version)` so it is reproducible. Bind an approval to the exact recipient, message, attachments, or application values; editing them invalidates approval. Unknown send outcomes require reconciliation, not blind retries.

### Manual versus autonomous is a permission boundary

| Action | Manual mode | Autonomous preparation mode |
| --- | --- | --- |
| Discover jobs | User starts search | Scheduled within folder scope and quotas |
| Analyze and match | User selects jobs | Automatically for new/changed relevant jobs |
| Propose projects and contacts | On request | Below-threshold usable results |
| Draft outreach | On request | Allowed, without sending |
| Message a person or submit an application | Explicit approval | Still explicit approval per external action |

Autonomous preparation can provide most of the benefit without turning the product into a spam sender. An optional later sending mode would need explicit, narrow consent, supported channel APIs, quotas, and jurisdiction/platform review. It is not included in the currently approved application safety model.

## 6. What should “under 70%” mean?

Current `hosted_matching.py` computes roughly:

```text
coverage = matched extracted job skills / extracted job skills × 100
```

That is **keyword/skill coverage**, not a calibrated probability of being hired or even a full suitability judgment. If no skills are extracted it returns no score, not zero. The current pipeline also truncates text and can miss evidence; scanned CVs may need OCR.

For the new workflow, first check hard eligibility separately: location, authorization, required license, and similar constraints. Do not average these away with technical skills. Then assess each job requirement against actual CV/project evidence, with source excerpts and uncertainty.

A possible initial weighted coverage formula is `100 × Σ(requirement weight × evidence coverage) / Σ(requirement weight)`, with coverage levels defined and tested. The weights and partial-credit rubric are a product proposal, not a validated hiring model. Show separate confidence and extraction quality; an unreadable CV should trigger repair, not two irrelevant projects.

Use 70% as a user-adjustable routing threshold. Exactly 70% does not satisfy “under 70%.” Validate the rubric on human-reviewed examples before calling the score reliable. A project cannot remedy work authorization or manufacture professional experience.

### Exactly two useful projects

For a usable score below 70%, cluster the highest-priority learnable gaps and propose two distinct projects, each with:

- The missing requirements and job-description evidence it addresses.
- A concrete scope, prerequisites, estimated effort, and accessible dataset/tools.
- Deliverables: repository, tests, demo, and short technical write-up.
- Acceptance criteria and a rubric for assessing completed work.
- A truthful suggested CV bullet **only after completion and evidence review**.

For example, a role missing SQL and deployment evidence could produce (1) a tested analytics pipeline and (2) a deployed model API with monitoring. That example is not a recommendation for every role. If relevant project ideas cannot be grounded, say so instead of inventing a fit benefit.

An LLM can help interpret requirements and draft projects/messages, but it needs a configured provider or local model, budgets, evaluation, and consent for private CV processing. Deterministic templates can provide a simpler first release. The existing deterministic application runner does not itself require an LLM key.

## 7. Can the agent find people and infer email addresses?

**Yes for researched suggestions and drafts; guessing is not verification, and discovery is not permission to contact.**

Prefer official team pages, public recruiting contacts in adverts, and publicly documented professional profiles. Store the source URL, observed date, person/role relevance, and confidence that the person still works there. Suggest a hiring manager, team member, or recruiter only when evidence supports that association; otherwise provide a search link rather than invent a person.

### Channel-specific constraints

- **LinkedIn:** generate relevant search/profile links and a personalized draft for the user. Do not scrape logged-in profiles or automate connections/DMs with a browser bot. LinkedIn explicitly restricts these activities. LinkedIn login/OIDC is identity linking, not a people-search or messaging permission grant.
- **X/Twitter:** use permitted public sources or an authorized API within its current tier, rate limits, and automation rules. A public profile does not guarantee DM availability. Credentials, access, and cost must be established before promising automatic outreach.
- **Email:** prefer a published recruitment/team address. For sending, use a user-authorized mailbox or configured provider, with secure token storage, recipient confirmation, quotas, suppression, and bounce handling. Sending from our domain also requires appropriate email authentication and reputation controls.

### What about guessing `firstname.lastname@company.com`?

It is technically easy to generate possible work addresses, but a domain pattern can be wrong, a person may have left, and a catch-all mail server can accept nonexistent recipients. DNS/MX records prove only mail routing exists; they do not prove a named mailbox exists or belongs to that person. Commercial verification services also return uncertain results.

If we offer inference, label it **“inferred, unverified”**, preserve its pattern evidence, and do not silently send to it. Prefer a public alternative; require explicit recipient confirmation before sending. Never attach a CV automatically to a guessed address: the wrong recipient would receive personal information. Avoid repeated SMTP probes or mass test emails.

Publicly accessible professional contact details can still be personal data. We need purpose limitation, retention/deletion, access control, and an appropriate legal basis. Rules depend on jurisdiction, recipient type, and whether the communication is legally marketing; not every job enquiry is automatically marketing, and not every B2B message is exempt. UK ICO guidance is one example, not a worldwide license. Obtain legal review before scaled outreach, handle objections, and never treat a public email as blanket consent.

## 8. What concretely prevents us from doing this now?

| Gap | Concrete work needed |
| --- | --- |
| Limited vacancy coverage | Employer-board registry, more approved connectors, reconciliation, source monitoring |
| Daily static feed | Database-backed ingestion worker and cached read API |
| Street-level UI and office accuracy | Zoom/marker changes, verified office addresses, licensed geocoding, confidence labels |
| Private hosted workspace not fully activated | Verify email login/delivery, redirects, tenant isolation, storage, deletion and deployed workers |
| No complete role-folder workflow | Folder UI/schema, selected CV version, manual triggers, schedule and task status |
| Match score is only skill coverage | Requirement/evidence model, extraction-quality checks, human calibration |
| Project/contact recommendation workflow missing | Grounded generation/templates, source tracking, review screens, evaluation |
| External channel access | Supported OAuth/API setup, user consent, platform permissions and rate limits |
| Inferred emails can be wrong | Provenance, uncertainty labels, recipient confirmation, bounce/suppression controls |
| Reliable autonomous execution | Durable queue, idempotency, safe retries, cancellation, audit logs and cost limits |
| Credential/security readiness | Rotate previously exposed credentials; verify service-role isolation and production settings |

The main barriers are **engineering integration, reliable data, provider permissions, privacy, and operational controls**—not the ability to write a bot that clicks buttons. A bot can technically perform unsafe actions; that does not make it accurate, permitted, or a product we should deploy.

## 9. Recommended delivery order

1. **Manual vertical slice:** hosted login, private CV, one role folder, manually saved official job, evidence report, two below-threshold project suggestions, sourced contact links, and editable outreach draft. No automatic sends.
2. **Autonomous preparation:** reviewed-source job ingestion, scheduled folder runs, durable tasks, deduplication, fresh/stale indicators, budgets and notifications.
3. **Reviewed execution:** connect a supported sending channel, approve exact recipients/content, record actual outcomes, and retain the existing per-application final approval. Stop on CAPTCHA, ambiguous fields, or unsupported employer flows.
4. **Coverage and quality:** expand approved sources, improve office data, calibrate scores, and monitor false matches and project usefulness.

Acceptance tests should include: a 69% score produces two proposals; 70% does not trigger the below-threshold rule; missing evidence is “unknown”; a failed source does not close jobs; repeated tasks do not duplicate messages; one user cannot access another's CV; edited messages invalidate approval; inferred contacts never auto-send; HQ and vacancy location remain distinct.

**Bottom line:** build a dependable research-and-preparation assistant first, with human approval for external actions. That delivers the proposed workflow without claiming instant worldwide jobs, exact offices everywhere, guaranteed match percentages, or verified guessed emails.

## Sources and repository references

### Repository evidence

- [`refresh-jobs.yml`](../.github/workflows/refresh-jobs.yml): schedule, bot identity and snapshot publishing.
- [`export_public_jobs.py`](../scripts/export_public_jobs.py): board collection, limits, geography and failure behavior.
- [`role_discovery.py`](../src/tau_job_application/role_discovery.py): vetted employer boards.
- [`app.mjs`](../vercel-site/app.mjs): MapLibre/OpenFreeMap and current zoom limit.
- [`export_public_map.py`](../scripts/export_public_map.py): public directory and location enrichment.
- [`hosted_matching.py`](../src/tau_job_application/hosted_matching.py): current CV extraction and coverage formula.
- [`hosted MVP migration`](../supabase/migrations/202610270001_hosted_mvp.sql): private workspace schema and policies.
- [`rule_based_apply.py`](../src/tau_job_application/rule_based_apply.py): deterministic reviewed applications.

### External documentation

1. [Greenhouse Job Board API](https://docs.greenhouse.io/job-board) and [Recruiting webhooks](https://docs.greenhouse.io/webhooks.html).
2. [Lever Postings API](https://github.com/lever/postings-api).
3. [Google JobPosting structured data](https://developers.google.com/search/docs/appearance/structured-data/job-posting) and [Indexing API](https://developers.google.com/search/apis/indexing-api/v3/quickstart).
4. [MapLibre GL JS](https://maplibre.org/maplibre-gl-js/docs/) and [OpenFreeMap](https://openfreemap.org/).
5. [Public Nominatim usage policy](https://operations.osmfoundation.org/policies/nominatim/).
6. [LinkedIn prohibited software and extensions](https://www.linkedin.com/help/linkedin/answer/a1341387/prohibition-of-scraping-software).
7. [ICO B2B marketing guidance](https://ico.org.uk/for-organisations/direct-marketing-and-privacy-and-electronic-communications/business-to-business-marketing/). UK-specific; check current guidance and local law before launch.
8. [GitHub: triggering a workflow](https://docs.github.com/en/actions/how-tos/writing-workflows/choosing-when-your-workflow-runs/triggering-a-workflow).

Provider terms, permissions, and pricing can change. Confirm them for the selected integration before implementation.
