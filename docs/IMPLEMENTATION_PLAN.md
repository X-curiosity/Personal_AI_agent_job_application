# Hired: map and autonomous job-agent implementation plan

This unified plan combines public startup-map browsing with shared job collection and a private recommendation agent. It preserves the implementation detail from the former map and job-agent plans.

**Status:** proposed implementation, not a claim that these features are deployed. Provider recommendations are not authorization to purchase services. See the architecture Q&A appendix and the product-direction appendix below for broader context.

## Contents

- [Part I — Map implementation](#part-i--map-implementation)
- [Part II — Autonomous job-agent implementation](#part-ii--autonomous-job-agent-implementation)
- [Part III — Employer integration](#part-iii--employer-integration)
- [Integrated delivery order](#integrated-delivery-order)

## Shared architecture

The map and agent use the same company, office and job identities. Public location evidence remains separate from private CVs, preferences and analyses. Saving a map result into a role folder should reference the existing job, not create a disconnected copy.

Street-level zoom does not establish office accuracy; directory coverage does not establish live vacancy coverage. Both tracks must preserve source provenance, uncertainty and freshness.

## Part I — Map implementation

### 1. Decision framework

Recommended starting point: retain **MapLibre GL JS + OpenFreeMap**, improve browsing, and enrich office locations separately. A map renderer does not discover where companies work. A company catalogue does not establish current vacancies.

Four independent components:

1. **Renderer:** draws the interactive map.
2. **Tiles/style:** roads, buildings, labels and visual appearance.
3. **Company/office data:** company identity, business addresses and location evidence.
4. **Geocoder:** converts a known address into coordinates, with varying precision.

Street-level zoom is not street photography. Street View-style imagery would be a separate integration and is not needed for the initial product.

### 2. Leaflet, MapLibre and Mapbox

| Option | What it supplies | Cost and trade-offs |
| --- | --- | --- |
| Leaflet | Open-source library, commonly using raster base-map tiles plus interactive overlays | Free library; tiles/geocoding separate. Good for straightforward maps; plugins add capabilities. No compelling reason to migrate our existing richer map. |
| MapLibre GL JS | Open-source GPU-rendered vector map library | Free library; choose tiles/geocoding independently. Supports detailed styling, clustering, terrain and building extrusion with suitable data. Current implementation. |
| Mapbox | Commercial platform including Mapbox GL JS, hosted maps, styling and additional search/navigation services | Usage-based pricing with service-specific allowances. Useful integrated tooling; licensing, limits and ongoing costs must be evaluated. |

Raster tiles are pre-rendered pictures. Vector tiles carry geometry/attributes that the browser can style and draw. Leaflet also supports vector overlays; it is not limited to images. Large datasets work best with clustering and appropriate rendering layers in any implementation, rather than thousands of HTML markers.

**Recommendation:** spend effort on source quality and interaction, not a renderer migration.

### 3. Can we reuse StartupMap and YC locations?

Yes, public location information can be a starting point **where collection and reuse are permitted**. Our project has already imported public StartupMap city/company information and YC records; it has not imported private StartupMap coordinate APIs.

- Company plus city/country: useful for city-level discovery, not an exact office.
- Public business address: geocode after checking source freshness and applicable terms.
- Coordinates attached to a marker: do not assume accuracy or permission to redistribute them. They may represent city centres, old HQs or presentation offsets.
- A crawl allowance or publicly accessible endpoint is not a redistribution license. Check current terms and request a permitted export or agreement where bulk reuse is unclear.
- The specific YC globe mentioned in discussion has not been identified/verified. Do not claim to have inspected its coordinates.
- Neither directory is an exhaustive worldwide startup registry.

Keep source URLs, collection dates and permitted uses. Deduplicate identities conservatively using verified domains and other evidence rather than names alone. Preserve multiple offices rather than overwriting a company with its latest imported location.

For a low-cost launch, group companies by city using a reusable, licensed city-coordinate dataset. Add verified offices progressively. Do not scatter companies randomly around a city to suggest street accuracy.

### 4. Google Maps: free trial versus ongoing allowance

Google Cloud has advertised an eligible new-customer trial of approximately **$300 for 90 days**, not a general year of unlimited free Maps. Eligibility and applicable products must be checked at signup.

Google Maps Platform separately offers monthly per-service free usage caps. The former $200 monthly Maps credit was replaced by per-SKU caps in March 2025. Many Essentials services have a 10,000-event monthly allowance, but exceptions exist; check the exact map, Places and Geocoding SKU before budgeting. These figures are discussion context, not a guaranteed current quote or eligibility confirmation.

Maps, business lookup and address geocoding are different billable operations. Finding and locating 10,247 companies can require multiple calls each and still leave unresolved companies. No API promises every startup's current office.

Before choosing Google:

- Verify the applicable agreement, including regional differences.
- Check display, caching, storage and attribution rules. Standard geocoding policies restrict using Google content on non-Google maps and permanent storage, subject to exceptions. Do not assume Google can populate a permanent MapLibre coordinate database.
- Restrict browser keys by origin/API; keep server credentials on the server.
- Set enforceable quotas and alerts. Budget alerts alone do not stop charges.
- Confirm trial expiry behavior and require explicit approval before enabling paid expansion.

Google is an option if its business lookup quality warrants its ecosystem and cost. It is not required for street-level map display.

### 5. Current code and why raising one number is insufficient

In [`vercel-site/app.mjs`](../vercel-site/app.mjs):

- Map creation uses `maxZoom: 10`, `minZoom: 2` and `scrollZoom: false`.
- Country card selection jumps to zoom 5; city selection jumps to zoom 8.
- `fitResults()` caps automatic bounds fitting at zoom 7.
- `renderPins()` displays country groups at zoom ≤3, city groups at zoom ≤7, and viewport-filtered individual/co-located groups above that.
- Markers are HTML elements rebuilt during rendering. Co-location groups use kind and coordinates, rather than complete office identity.
- `currentMapPoints()` currently constructs directory locations without carrying a full precision/provenance model into each point.

Changing `maxZoom` alone allows closer viewing, but does not fix ambiguous marker positions, overlapping groups, automatic zoom-out, or office accuracy.

### 6. Implementation track A: street-level browsing

#### A1. Centralize camera rules

Introduce named constants for world, country, city, office and maximum zoom. Start testing a maximum of **18**, city navigation around **11–12**, and verified building selection around **16–17**. These are initial UX values to tune, not exact map-scale guarantees.

Verify the chosen style/tile coverage at those zooms; increasing camera zoom may overzoom existing tiles rather than reveal new detail. Retain a usable list if tiles fail.

Update map creation, card navigation and `fitResults()` together. Bounds fitting should depend on the action and location precision:

- Country selection: fit the relevant country/points without pretending a single country-centre point is precise.
- City selection: fit the city or a conservative city view.
- Exact office selection: allow building-scale zoom when supported by evidence.
- Routine filter changes: avoid unnecessarily resetting an intentional user camera position.

Use reduced-motion preferences. Keep navigation buttons and mobile gestures; decide explicitly whether wheel zoom should require map focus to avoid trapping page scrolling.

#### A2. Preserve precision through rendering

Carry `precision`, `location_kind`, `source_url` and verification timestamps into map features. Existing `hq` denotes a location role/source category, not automatically building-level accuracy. Conservatively map legacy data to unknown/approximate precision until evidence supports a finer label.

At street zoom:

- Verified building/address: precise-looking office pin with source details.
- City/country only: clearly labelled area marker or area result, never an office entrance pin.
- Unknown coordinates: remain searchable in the list; do not invent a location.

Never invent a radius of uncertainty. Use a region outline when known, or a labelled estimate when it is not.

#### A3. Cluster and select without hiding records

For the scalable implementation, build GeoJSON point sources with stable company/office/job IDs. Use MapLibre clustering for dense groups and GPU layers for most points. Keep jobs, offices and estimated locations distinguishable; use separate sources where clustering semantics differ.

- Clicking a cluster uses cluster expansion zoom while bounded by our camera limits.
- If records share the same coordinate and cannot separate, open a paginated co-located-results list.
- Preserve country-qualified city identity in selection, URLs and history.
- Cluster counts reflect the active filters; distinguish company counts from role counts.
- Use stable IDs for job-to-company associations rather than relying permanently on case-insensitive names.

Company logos should appear only for selected or a bounded number of visible unclustered companies. Avoid loading all thousands of logos into the GPU sprite atlas or DOM at once. Missing official logos must not be replaced with invented brands; count/selection markers can remain neutral UI elements rather than being presented as company logos.

A first incremental release can retain bounded DOM markers while fixing precision and co-location selection; GPU-layer migration is the next scaling step if profiling warrants it.

#### A4. Accessibility and performance

Maintain a synchronized searchable list as the keyboard-accessible route to every result. Provide visible focus, descriptive labels and accessible details panels. Canvas interaction alone is insufficient.

Avoid rebuilding every marker on idle events. Update data when filters change; reconcile visible markers on settled camera changes. Profile dense cities and slower/mobile devices; set measured budgets for marker count, memory and interaction latency rather than claiming performance without testing.

### 7. Implementation track B: accurate company offices

#### B1. Separate offices from companies and jobs

Proposed schema:

```text
company_offices
  id, company_id
  office_kind                 # HQ, branch, coworking, unknown
  address_text, city, country_code
  latitude, longitude
  precision                   # building, street, city, country, unknown
  coordinate_source, source_url
  geocoding_provider, provider_record_id
  observed_at, verified_at
  verification_status         # unreviewed, supported, conflicting, stale
  permitted_storage_until     # nullable; driven by applicable provider terms

job_offices
  job_id, office_id, evidence_url, observed_at
```

Separate extraction confidence from geocoder confidence and verified address ownership. A geocoder resolving an address successfully does not prove the company occupies it.

No exact coordinate is required for a company to appear in city browsing. A job may be remote, multi-location, or restricted to a country without a named office.

#### B2. Source and geocode

1. Start with official contact/location pages and permitted directory exports.
2. Extract public business addresses with URLs and observation dates.
3. Normalize addresses without discarding floor/unit information from the displayed source record.
4. Query a provider whose terms permit our intended storage and MapLibre display, or operate our own appropriate service.
5. Store precision and ambiguous candidates; do not automatically accept a similarly named business in the wrong country.
6. Review conflicts and low-confidence results. Offer an operator correction workflow with audit history.
7. Refresh according to source/provider obligations and mark aging evidence as stale.

Public Nominatim is not an unrestricted bulk enrichment service: its policy includes a maximum of one request per second, no client autocomplete and restrictions on systematic queries. Use a suitable hosted provider or self-host for workloads beyond the public service's permitted use. Self-hosting avoids per-request provider billing, not infrastructure/operations costs.

Workers must use timeouts, bounded responses, private-network/redirect protections, caching where permitted, retries with backoff and stops on rate limits. Do not publish private/home addresses merely because they were discovered during enrichment.

#### B3. Associate vacancies honestly

Link a job to an office only when the listing or employer provides evidence. Never substitute HQ for a remote job or a role in another city. Show job location as stated, company office information separately, and uncertainty prominently.

### 8. File-level delivery plan

| File/component | Proposed work |
| --- | --- |
| `vercel-site/app.mjs` | Camera policy, precision-aware points, cluster/co-location selection, bounded logos and accessible list integration |
| `vercel-site/jobs-core.mjs` | Pure helpers for precision grouping, company/role counts and country-qualified identity |
| `vercel-site/map-core.mjs` | Validate expanded office/location schema, safe links and coordinate ranges |
| `vercel-site/styles.css` | Distinct office/estimate/job markers, focus and mobile styles |
| `scripts/export_public_map.py` | Export precision/provenance and multiple offices without converting legacy HQ claims to exact addresses |
| New office enrichment worker | Permitted source fetching, geocoding, uncertainty and review queue |
| New database migration | Office/evidence tables, indexes and protected correction/audit operations |
| Python/Node/browser tests | Export/schema tests, grouping and geographic interaction regressions |

Changes should preserve existing public routes and static export compatibility during migration. Where the schema changes, version it and handle older snapshots deliberately. No database/provider deployment is authorized merely by documenting this plan.

### 9. Free versus paid budget model

| Item | Initial approach | Possible cost |
| --- | --- | --- |
| Renderer | Keep MapLibre | No renderer license fee |
| Base map | Continue OpenFreeMap subject to current service terms | Alternative hosted provider/support or self-hosting if needed; no assumed SLA |
| City coordinates | Reusable licensed dataset with attribution | Maintenance and hosting |
| Directory locations | Permitted public information or agreed export | Licensing/access may require negotiation |
| Exact address geocoding | Evaluate compatible providers and allowances | Requests, storage rights, or self-hosted infrastructure |
| Address verification | Source checks and operator review | Engineering and human time |
| Google alternative | Trial/allowances only after checking eligibility | Separate map loads, searches, details and geocoding charges |

Estimate monthly cost from **map usage + new/changed addresses × requests per address + source access + workers/storage + review effort**. Do not equate 10,247 companies with 10,247 API calls or assume a one-time free trial funds ongoing refreshes.

### 10. Rollout and acceptance tests

1. **First release:** camera changes, honest location labels, co-located lists and desktop/mobile navigation tests. No paid geocoder needed.
2. **Second release:** office schema, a small reviewed sample of exact addresses and an enrichment queue. Measure match quality and request cost before bulk execution.
3. **Scale:** expand approved sources, add GPU clustering where needed and monitor data staleness, provider usage and errors.

Required checks:

- Reach zoom 17–18 where supported without breaking lists or map controls.
- A city-centre estimate never appears as a verified office at higher zoom.
- A legacy HQ coordinate is not automatically upgraded to building precision.
- Multiple companies at one address remain individually selectable.
- Same-name cities in different countries remain separate; back/forward preserves selection.
- Job counts respect filters and job locations, not directory HQ location.
- Exact office selection and ordinary filters follow the intended camera policy.
- Mobile, keyboard, reduced motion, empty results and tile failures remain usable.
- Rate-limited/failed enrichment does not overwrite previously supported locations.
- Provider quotas, credentials and storage/display terms are checked before activation.

### References

- [Leaflet](https://leafletjs.com/) and [quick start](https://leafletjs.com/examples/quick-start/).
- [MapLibre GL JS documentation](https://maplibre.org/maplibre-gl-js/docs/).
- [Mapbox GL JS pricing model](https://docs.mapbox.com/mapbox-gl-js/guides/pricing/).
- [OpenFreeMap](https://openfreemap.org/).
- [Google Maps billing FAQ](https://developers.google.com/maps/billing-and-pricing/faq) and [geocoding policies](https://developers.google.com/maps/documentation/geocoding/policies).
- [Nominatim usage policy](https://operations.osmfoundation.org/policies/nominatim/).
- [StartupMap](https://startupmap.one/) and [YC directory](https://www.ycombinator.com/companies/).

Check current provider documentation and the applicable agreement before implementation; pricing, permissions and service capabilities can change.

## Part II — Autonomous job-agent implementation

### 1. What we know about StartupMap

StartupMap's public site describes curated company records and daily collection from career pages. A plausible system is a company/location database feeding the map, alongside job collectors feeding listings and hiring status. We have not verified its internal backend, collection methods, coordinate sources or office-level accuracy. Its markers could come from public profiles, geocoding or manual review; those are possibilities, not findings.

We should implement the visible product outcome using our own permitted sources, not assume access to a competitor's internal dataset.

### 2. Two separate systems

**Shared collection:** discover and maintain reliable public job records once for all users.

**Private recommendation:** assess those records against each user's role folders, preferences and selected CV, then propose relevant opportunities.

This avoids repeatedly crawling the same employers for every user. The autonomous agent is a controlled workflow with persistent state—not necessarily an LLM freely operating a browser.

### 3. Source registry and collection

Maintain `job_sources` with company ID, official careers URL, source/ATS type, board identifier, region, enabled status, permitted access notes, polling interval, last success, next check, failure count and cursor where applicable. Verify that the careers source belongs to the company; domain identity alone can require review after mergers or rebrands.

A scheduled worker:

1. Claims a due source task.
2. Uses the official public ATS API where available. Existing connectors are reusable, but coverage is currently limited.
3. Otherwise reads permitted public career pages and structured job data. Uses browser rendering only when necessary and permitted.
4. Follows pagination with explicit completeness tracking.
5. Normalizes title, employer, description, location, workplace mode, salary/currency, employment type and official application URL. Unknown values remain unknown.
6. Upserts by `(source, board, source_job_id)`, with content hashes and source provenance.
7. Tracks `first_seen_at`, `last_seen_at`, source timestamps, last successful synchronization and job status separately.
8. Reconciles closures only after a complete successful check or authoritative source event. Rate limits, failures and capped previews never imply closures.
9. Emits new/changed-job events for downstream matching.

Use conditional requests where supported, bounded responses, timeouts, backoff, source-specific concurrency and rate-limit handling. Public pages and redirects need SSRF/private-network protection. No CAPTCHA bypass, login-wall circumvention or private LinkedIn scraping.

Cross-source deduplication should retain provenance and avoid collapsing distinct roles sharing a title. Define separate company, office and vacancy identities. A company HQ must never silently become a vacancy's workplace.

### 4. Private role-folder workflow

A user creates a folder such as “Junior ML — Belgium/remote”, selects a CV version, and specifies title interests, seniority, location, authorization constraints, exclusions and notification preferences.

New or changed jobs flow through:

```text
Shared job event
  → find potentially relevant folders
  → hard eligibility filters
  → evidence extraction and CV comparison
  → ranked shortlist with explanations and uncertainty
  → saved private recommendation
  → opt-in daily digest or in-app notification
```

Cheap rules run before expensive analysis. Unknown eligibility should be marked for clarification, not assumed satisfied. Feedback such as interested/not interested refines ranking; it must not silently relax a hard constraint.

Cache an analysis against user ID, job content hash, CV version, preference version and scoring version. Track previously shown recommendations so unchanged jobs do not repeatedly notify users. Reanalysis is appropriate when relevant inputs change. A closed job can remain in history, but should not be proposed as currently open.

### 5. Where AI belongs

| Work | Recommended mechanism |
| --- | --- |
| Fetch known ATS feeds | Ordinary connector code |
| Schedule, claim, retry and cancel tasks | Durable queue and worker |
| Detect unchanged jobs | Source IDs, hashes and reconciliation |
| Apply explicit exclusions/authorization constraints | Deterministic rules with unknown states |
| Interpret nuanced preferences | Optional LLM producing validated structured fields |
| Compare requirements with evidence | Defined rubric, rules and optionally grounded LLM analysis |
| Draft explanations, projects and messages | Optional LLM or structured templates |
| Authorize external actions | Explicit server-side permission and approval checks |

An LLM is not required for ingestion. It can improve nuanced analysis but introduces provider/local-model configuration, cost, latency, evaluation and CV privacy requirements.

Treat job descriptions, websites and retrieved documents as untrusted data. Their content must never become authority to expose a CV, change permissions, execute commands or contact somebody. Give analysis tasks read-only tools and validated output schemas. Do not put outbound sending credentials into the analysis context.

### 6. Matching and two-project recommendations

Current deterministic matching is extracted skill coverage, not a calibrated hiring probability. The new scorer should assess explicit requirements against CV/project evidence, show citations and uncertainty, and report extraction quality separately.

For usable coverage below 70%, propose two distinct projects targeting the highest-priority learnable gaps, with deliverables, effort assumptions and acceptance criteria. Exactly 70% is not below threshold. Unreadable CVs, missing requirements and hard authorization failures need clarification or eligibility guidance—not fabricated project recommendations.

Do not raise a score simply because a project was proposed. Reassess only after the user supplies completed work and truthful evidence. Contact suggestions need public professional-source evidence and clear uncertainty; inferred email addresses remain unverified.

### 7. Runtime architecture

- **Vercel:** public map/search and private workspace interface.
- **Supabase Postgres:** company/source/job records, folders, task state and private analysis metadata.
- **Supabase Auth/private storage:** identity and CV versions, with tenant-scoped access and deletion controls.
- **Hosted Python worker:** connectors, parsing, scoring and optional model calls.
- **Scheduler:** enqueues source and folder tasks; it does not run a permanent browser session.
- **Notification adapter:** user-authorized digests with delivery status and unsubscribe/preferences.

Start with a Postgres-backed queue to avoid another service. Claim tasks atomically (for example, a transaction using `FOR UPDATE SKIP LOCKED`), use leases/heartbeats, bounded attempts and backoff. Expired leases permit recovery; task deduplication prevents repeated side effects. Track task state, attempt count, timestamps, cancellation and sanitized errors.

Use unique task keys for source refresh windows and analysis input versions. Record an outbox event transactionally with a saved recommendation, then deliver it idempotently. Sending failures with uncertain outcomes require provider reconciliation rather than blind retries. A notification provider's idempotency support must be verified rather than assumed.

Service-role credentials stay on the backend. Workers must enforce ownership even where privileged credentials bypass row-level policies. Minimize CV text in logs, configure retention and support deletion/cancellation of queued work.

### 8. Autonomy and human control

Automatic: collection, filtering, analysis, explanations, projects and opt-in opportunity notifications to the user.

Approval required: messages to third parties, sharing a CV and submitting employer applications. Bind approval to exact recipient/content/attachments or form values; edits invalidate it. Do not interpret “run my folder daily” as permission to send applications or cold emails.

Support pause, cancel, rerun and clear task status. The worker must continue preparation without an open user browser, but stop processing private data when authorization is revoked or the account is deleted.

### 9. Costs and limits

Potential costs include worker compute, network traffic, database/storage, notification delivery, model usage and licensed job feeds. Connector maintenance also costs time. A small pilot may fit provider free allowances; an always-running production service is not guaranteed free.

Reduce cost by collecting once, filtering before model calls, analyzing only relevant changed inputs, batching notifications, bounding job/CV text and applying per-user/source budgets. Show failures or deferred tasks rather than silently exceeding quotas.

Do not quote a monthly price without choosing providers and measuring: monitored sources × check frequency, jobs changed per day, users/folders, eligible analyses, model tokens per analysis and notification volume.

### 10. First release and testing

First deliver: **a bounded set of reviewed employers → scheduled shared collection → one private role folder → daily ranked shortlist with evidence**. Start with manual analysis as a verified vertical slice, then enable scheduling. Add project suggestions, contact research and reviewed applications after recommendation quality is established.

Tests and operational checks:

- Complete versus partial pagination, empty feeds, malformed records, timeouts and 429 responses.
- No false closures after source failures; legitimate closures disappear from active recommendations.
- Repeated events do not duplicate jobs, analyses or digests.
- Two-user isolation and account-deletion cancellation.
- CV/preference/job version changes invalidate the right cached analyses.
- 69%/70% threshold behavior and no-score behavior.
- Prompt injection in a job description cannot invoke external actions or disclose private data.
- Worker crashes/lease expiry recover without duplicate side effects.
- Manual triggers and background tasks produce consistent results.
- Users can pause autonomous preparation and control notification frequency.

Monitor source freshness, parse failures, closure anomalies, queue lag, analysis cost and recommendation feedback. A green scheduler alone is not proof of fresh jobs or useful recommendations.

## Part III — Employer integration

Startups submit jobs automatically through a self-serve onboarding flow. See the dedicated the employer-integration appendix below. Employer-submitted jobs share the same database as collected jobs, with domain verification, provenance, sync status and abuse controls.

## Integrated delivery order

1. **Shared data contracts:** stable company/job IDs, office precision and provenance, job freshness and ownership boundaries.
2. **Map browsing improvements:** camera policy, honest location markers, co-located selection and accessible lists.
3. **Manual private workflow:** verified hosted authentication/storage, role folders, a selected CV version, saved map roles and evidence-based analysis.
4. **Scheduled preparation:** reviewed-source ingestion, durable queue, versioned matching and opt-in shortlists.
5. **Enrichment and execution:** reviewed office enrichment, grounded projects/contact research, and separately approved external actions.
6. **Scale only after measurement:** broader coverage, rendering optimization, recommendation evaluation and monitored provider budgets.

Each track retains its detailed rollout and acceptance tests above. Verify the final integrated version before enabling production services or increasing paid usage.

## Appendix — Employer integration (self-serve job submission)

This is a proposed employer-facing plan, not a deployed feature. It complements the [unified implementation plan](IMPLEMENTATION_PLAN.md) (map + job agent), which covers the candidate-facing map, collection, and recommendation agent.

### 1. Two meanings of "automatic"

1. **Employers push jobs to us** — a company signs up, connects a source, and jobs flow in automatically. This is self-serve onboarding.
2. **We pull jobs automatically** — reading official ATS boards on a schedule, which the project already does for a bounded set of employers.

A real "startup enters its jobs automatically" product is mostly the first, with the second as a fallback for companies that do not sign up. The two feeds share the same job records.

### 2. Recommended employer flow

```text
Company signs up → proves it owns the company → connects a source → we verify → jobs sync on a schedule → jobs go live
```

#### Step 1 — Claim and verify the company

- Employer creates an account, then finds or creates their company record (already in the catalogue, or new).
- Verify control. Cheapest reliable checks:
  - Email at the company domain (`person@company.com`) plus a one-time confirmation token.
  - DNS TXT record, or sign-in through the ATS owner account.
- Verification is required; otherwise anyone could post fake jobs under a real startup's name.

#### Step 2 — Connect a source

| Connection | Effort for the company | Our work |
| --- | --- | --- |
| Official ATS API (Greenhouse, Lever, Ashby, Workable, Recruitee, …) | Paste board token / company subdomain | Read the public board API already supported |
| ATS owner webhook | Enable webhooks where their plan allows | Receive signed created/updated/closed events |
| `JobPosting` structured data + sitemap | Nothing — already on their careers site | Crawl the careers sitemap on a schedule |
| Feed (XML / RSS / JSON) | Provide a feed URL | Poll it |
| Manual form | Type/paste job details | Review before publish |

Best path: **auto-detect the ATS from the careers URL** and default to the official API — least work for the startup, most reliable for us.

#### Step 3 — Automatic sync

- A worker checks connected sources on a schedule and on webhook events.
- New jobs appear; changed jobs update; closed jobs drop out.
- Store `first_seen`, `last_seen`, `source_timestamp`, and `status`. A failed sync must never silently close jobs.
- Jobs go live after automated checks (valid URL, title, location, description). Human review is an escalation for first-time posters or flagged content.

#### Step 4 — Trust and abuse controls

- Rate-limit job creation per company; flag suspicious volume.
- Preserve provenance: every job shows its source and submitter.
- Companies edit/close only their own jobs; users can report stale or fake ones.
- Never let a company overwrite another company's records.

### 3. Employer dashboard

- See and edit their own live jobs.
- Close filled roles, which removes them from active recommendations without deleting history.
- View source sync status, last success and errors.
- Review reported listings.

### 4. Free versus paid

| Item | Cost |
| --- | --- |
| Employer account + self-serve portal | Free to offer; build cost is time |
| Official ATS board APIs (Greenhouse / Lever / Ashby) | Free public endpoints in most cases |
| Webhooks | Depends on the ATS plan; many require an API/integration tier |
| Structured-data crawling | Compute plus polite rate limits |
| Hosted worker + database + auth | Ongoing infrastructure cost |
| Optional human job review | People time; scale only if needed |

### 5. Relationship to the job agent

Employer-submitted jobs flow into the same shared job database the candidate-facing agent reads:

```text
Self-serve employers ─┐
Official board APIs ──┼──→ shared jobs database ──→ public map + private agent
Structured-data crawl ┘
```

One job identity feeds both surfaces. A job submitted by an employer is not inherently more trustworthy than one collected from their official ATS; both carry provenance and freshness. An employer marking a job closed is authoritative for that record.

### 6. First version and acceptance tests

First deliver:

1. Employer sign-up and company verification (domain email/DNS).
2. ATS auto-detection from a pasted careers URL.
3. Scheduled sync plus webhook where available.
4. Employer dashboard for editing and closing jobs.
5. Automated quality checks before publish.

Acceptance checks:

- An employer cannot claim a company without domain/DNS verification.
- Connecting a supported ATS imports jobs without manual entry.
- A closed job disappears from active search and recommendations but stays in history.
- A failed sync preserves existing jobs with a stale indicator.
- A company cannot edit or close another company's jobs.
- Abusive volume is rate-limited and flagged.
- Every live job shows its source and provenance.

### References

- [Unified implementation plan](IMPLEMENTATION_PLAN.md): map, office accuracy, and the autonomous job agent.
- Architecture Q&A appendix: current ingestion, job freshness, and provider constraints.

## Appendix — Product direction (StartupMap + Jack & Jill)

### Product direction

Combine a **public startup map** with a **private career agent**, both using the same company and jobs database. They are two ways of discovering opportunities, not separate apps.

This is a proposed integration plan, not a claim that these features are already live. For implementation details and current limitations, see the architecture Q&A appendix.

### 1. What to take from each product

| Inspiration | Features to build |
| --- | --- |
| StartupMap | Browse companies geographically; filter by sector, stage and hiring status; open company profiles and current vacancies. |
| Jack & Jill | Understand candidate preferences, proactively discover roles, explain matches, notify the candidate and support next steps. |

The public [StartupMap](https://startupmap.one/) page describes a curated European company directory with roles pulled daily from company career pages. [Jack & Jill](https://www.jackandjill.ai/) advertises proactive discovery, direct introductions and interview/negotiation support.

These are their public product descriptions, not an independent verification of coverage or insight into their internal architecture. In particular, **direct introductions require participating employers—not just an AI model**.

### 2. How it would work in Hired

#### Public experience: Explore

Anyone can browse the map without an account:

- Company profiles, verified locations, logos and source links.
- Filters for city, industry, funding stage and available roles.
- Clear distinction between offices and estimated city locations.
- Actions to **follow this company** or **add this role to my folder**, with sign-in when saving private preferences.

#### Private experience: My agent

The user signs in, uploads a CV and sets preferences. For example:

> Find junior ML roles in Belgium or remote in Europe. Prefer small startups. Exclude unpaid internships.

The agent then:

1. Checks approved job sources on a schedule.
2. Filters out incompatible roles.
3. Compares relevant roles with the selected CV version.
4. Proposes a short, ranked list with supporting evidence, gaps and freshness information.
5. Learns from **interested / not interested** feedback without silently changing hard requirements.
6. For usable matches below 70%, suggests two projects addressing learnable gaps.
7. Prepares sourced contact research, outreach drafts or applications for approval.

The agent keeps running when the user closes the website. That requires a hosted background worker, not an open browser tab.

### 3. Existing foundations and missing integration

| Existing foundation | Integration still needed |
| --- | --- |
| Public map and company catalogue | Better location accuracy, street-level navigation and verified startup classification |
| Official job-source connectors | Broader employer coverage and reliable refresh/closure handling |
| CV extraction and deterministic skill matching | Evidence-based ranking beyond keyword coverage |
| Hosted account/storage foundation | Production activation and end-to-end isolation checks |
| Reviewed application runner | Hosted execution, task tracking and secure approval handoff |
| Targets and application records | Role folders, saved searches, preferences and feedback |

These foundations exist in the repository; that does not mean every hosted feature has been activated or verified in production.

**The company catalogue is not a live vacancy feed.** Monitoring thousands of companies means discovering and maintaining their official career sources. Directory presence or a hiring flag must not be presented as proof of a current vacancy.

### 4. Recommended architecture

Keep the existing stack where practical:

```text
Official employer sources
          ↓
Scheduled ingestion workers
          ↓
Shared companies + offices + jobs database
          ├── Public map and search
          └── Private agent
                 ↓
          CV + preferences + role folders
                 ↓
          Ranked recommendations
                 ↓
          In-app/email notifications
                 ↓
          User-approved next actions
```

#### Responsibilities

- **Vercel:** public interface and authenticated workspace.
- **Supabase:** accounts, private CV storage, database and owner-scoped access policies.
- **Hosted Python worker:** source collection, analysis and scheduled tasks.
- **Durable task queue:** retries, cancellation, duplicate prevention and visible task status.
- **Optional LLM:** interpret preferences and draft explanations/projects. Deterministic rules enforce eligibility, permissions and approval boundaries.

#### Efficient execution

The agent should analyze new or changed jobs—not repeatedly process the whole internet for every user. Shared ingestion and cached analyses keep costs manageable.

Keep job identities and source history stable. Bind private analyses to the user, job content version, CV version and scoring version. Recompute when relevant inputs change. A failed source request must not mark all its vacancies closed.

The map and agent should share the same job records, so a role discovered on the map can be saved into a folder and analyzed without a second import or inconsistent vacancy status.

### 5. What autonomous should mean initially

| Automatic preparation | Requires approval |
| --- | --- |
| Job discovery and filtering | Sending a message |
| CV matching and explanations | Sharing a CV |
| Two-project suggestions | Submitting an application |
| Relevant opportunity notifications | Other external actions on the user's behalf |

Most value comes from finding a few genuinely relevant opportunities and explaining why they matter. A useful product does not need unrestricted browser automation.

Approval must cover the actual recipient, message, attachments or application values. Changes invalidate approval. An uncertain submission outcome must not cause a blind retry.

**70% must mean a defined evidence-coverage score**, not a 70% probability of being hired. Missing or unreadable CV evidence should produce uncertainty, not misleading precision. Exactly 70% is not below the threshold. Project proposals alone must not increase a match score; completed work needs evidence.

### 6. The hardest parts

#### Job coverage and freshness

Identify sources, respect access rules and rate limits, remove closed jobs, avoid duplicates and make stale data visible. Broad company coverage does not automatically produce broad vacancy coverage.

#### Recommendation quality

Seniority, work authorization, location and candidate intent matter more than shared keywords. Explain recommendations using job requirements and actual CV evidence. Treat unknown information explicitly.

#### Reliable private execution

Implement tenant isolation, secure storage, retries, audit trails, notifications, cancellation and cost controls. Keep private CVs and contact data out of the public catalogue and GitHub snapshot pipeline.

#### Employer relationships

Direct introductions like those advertised by Jack & Jill need an employer-facing product and participating recruiters. Generating a contact suggestion or an email draft is not equivalent to arranging an introduction.

LinkedIn sign-in does not grant unrestricted people-search or messaging permissions. Contact research and outreach must use supported sources/channels and preserve uncertainty about inferred email addresses.

#### Geographic completeness

“All startups” is not a dataset whose completeness we can guarantee. Publish measured coverage and clear unknowns. A sourced HQ coordinate is not necessarily the workplace of a vacancy; an estimated city centre is not an exact office.

### 7. Recommended delivery sequence

#### Phase 1: complete manual workflow

- Activate and verify hosted sign-in and private CV storage.
- Create role folders with explicit criteria and a selected CV version.
- Save companies and roles from the public map.
- Analyze selected roles and show evidence, gaps and uncertainty.
- Propose two grounded projects for usable below-threshold results.
- Prepare sourced contact suggestions and editable drafts, without sending.

#### Phase 2: autonomous preparation

- Expand the reviewed employer-source registry.
- Add durable ingestion and per-folder scheduled analysis.
- Rank new or changed opportunities and collect feedback.
- Send opt-in daily shortlists with links to the private workspace.
- Add freshness monitoring, budgets, cancellation and failure alerts.

#### Phase 3: reviewed execution

- Connect supported outbound channels with user authorization.
- Approve exact recipients/content and individual applications.
- Record actual outcomes and prevent duplicate submissions.
- Stop on CAPTCHA, ambiguous questions, restrictions or unsupported flows.

#### Phase 4: coverage and employer participation

- Expand regions and role categories based on measured source quality.
- Improve office verification and map navigation.
- Evaluate recommendation usefulness with users.
- Build employer onboarding and mutual-interest introductions if demand supports it.

### 8. First experience to deliver

> Browse the map → save a role/company → create a folder → activate the agent → receive a daily shortlist → approve the next step.

Start with a well-covered region and role category, then expand. **Finish this connected workflow before adding voice conversations, mass outreach or employer-side recruiting agents.** It delivers both discovery modes without rebuilding everything.

#### Minimum acceptance criteria

- A map role can be saved and analyzed in the same user's folder.
- User A cannot access user B's CV, preferences or analyses.
- Scheduled preparation runs without an open browser session.
- A new relevant job generates at most one notification per configured policy.
- Failed ingestion preserves known jobs with a stale indicator rather than falsely closing them.
- Every recommendation explains its evidence and important unknowns.
- Below-threshold project suggestions are grounded in learnable gaps.
- No message, CV share or employer submission occurs without the required approval.

### References

- [StartupMap](https://startupmap.one/): public geographic browsing inspiration.
- [Jack & Jill](https://www.jackandjill.ai/): public proactive discovery/introduction inspiration.
- Architecture Q&A appendix: current implementation, job ingestion, mapping providers, scoring, outreach and concrete blockers.

## Appendix — Build stack from reverse-engineering findings

Reverse-engineering-informed build-stack assessment using the REA browser observation provider (Chrome DevTools Protocol) plus static inspection of the shipped bundles.

### Method

- **REA MCP is now connected** in this session. I launched the Playwright-bundled headless Chromium (`chrome-headless-shell`) with `--remote-debugging-port` and inspected both targets with REA's `inspect_web_page` (CDP, passive — JavaScript is parsed/observed, not executed by REA).
- **StartupMap evidence:** REA `inspect_web_page` result `ev_6ad8eb0247683e53bfd413f4ae8e18c7545dd653eb29b40cfe271a0d79dd50eb` (origin `https://startupmap.one`).
- **Jack & Jill evidence:** REA `inspect_web_page` result for `https://www.jackandjill.ai/jack` (origin `https://www.jackandjill.ai`).
- Static bundle inspection of StartupMap's public `index-*.js` was also used to enumerate referenced API routes.
- Every finding is labeled **observed** (seen by REA/static) versus **inferred** versus **unknown**. No private APIs were called, no credentials extracted, no runtime mutations performed. The headless browser was only used for passive page observation.

### 1. StartupMap — observed stack

| Component | Evidence (REA CDP) | Status |
| --- | --- | --- |
| UI framework | Main bundle `static/index-D1jAOKa0.js` (hashed Vite output), React markers | Observed — React |
| Build tool | `index-*.js` / `index-*.css` hashed names | Observed — Vite |
| Map | `static/mapbox-CWlMv1cL.js` chunk | Observed — Mapbox GL JS |
| Analytics | `static/posthog-DlmmmYUv.js`, `cairn/array/*/config.js`, `static/analytics-DlcoREUq.js` | Observed — PostHog + custom chunk |
| Attribution/surveys | `cairn/static/surveys.js`, `web-vitals.js`, `dead-clicks-autocapture.js` | Observed — Cairn |
| Edge/CDN | `cdn-cgi/challenge-platform/scripts/jsd/main.js` | Observed — Cloudflare (challenge + CDN) |
| Backend/storage | Logo URLs on `…supabase.co/storage/v1/object/public/startup-logos/…` (earlier observation) | Observed — Supabase storage |

#### Public API surface referenced in the bundle

Route strings present in the shipped JavaScript (static observation; not called):

- **Jobs/companies:** `/api/jobs`, `/api/jobs/summary`, `/api/startups`, `/api/funds/`
- **User:** `/api/me`, `/api/me/profile`, `/api/me/preferences`, `/api/me/answers`, `/api/me/board`
- **Matching:** `/api/me/matches`, `/api/me/match-count`, `/api/me/match-emails`
- **Following/saving:** `/api/me/following`, `/api/me/follows`, `/api/me/saved-jobs`, `/api/me/org-search`
- **Email:** `/api/broadcast`, `/api/email-subscribers-count`, `/api/me/newsletter`, `/api/me/follow-emails`
- **Utilities:** `/api/logo-proxy`, `/api/me/merge`, `/api/me/share`, `/api/save-user-settings`

#### Interpretation

StartupMap is a **React SPA (Vite) + Mapbox GL JS**, fronted by Cloudflare, using PostHog/Cairn analytics, with a **Supabase-backed API** exposing jobs, companies, funds, saved-jobs/follows, a "Match me" onboarding, and match emails. The map is Mapbox-based (consistent with its stated "Mapbox" provider).

### 2. Jack & Jill (`/jack`) — observed stack

| Component | Evidence (REA CDP) | Status |
| --- | --- | --- |
| Framework | `/_next/static/immutable/chunks/*.js` + `turbopack-*.js` | Observed — Next.js App Router, Turbopack build |
| Hosting/analytics | `/_vercel/insights/script.js` | Observed — Vercel + Vercel Insights |
| Typography | Preloaded `ABCDiatype*`, `ABCMarist*` woff2 | Observed — Fontshare brand fonts |
| Two-sided traction | Customer logos on `/jack`: Tavus, Maze, Ramp, Corgi, Multiverse, Strala, Attio | Observed — employer/customer references |
| Page purpose | `/jack` title: "get a direct introduction to jobs you actually want" | Observed — candidate-side product |

Jack & Jill is a **Next.js + Turbopack app on Vercel** (with Vercel Insights) presenting a candidate-side "Jack" flow and company-side "Jill" marketplace. Its internal matching and introduction logic remains **unknown** from the public page.

### 3. What we already use vs. what each product implies

| Need | Our current choice | StartupMap uses | Jack & Jill uses |
| --- | --- | --- | --- |
| Map renderer | MapLibre GL JS + OpenFreeMap | Mapbox GL JS | n/a |
| Frontend (map site) | Vanilla JS static | React + Vite | Next.js (Turbopack) |
| Backend/data | Python + SQLite (local), Supabase (hosted scaffold) | Supabase-backed API | Unknown, on Vercel |
| Jobs | Official ATS connectors | `/api/jobs` service | "scans millions of jobs" |
| Matching | Deterministic skill coverage | `/api/me/matches` | Unknown proprietary |
| Analytics | None public | PostHog + Cairn + Cloudflare | Vercel Insights |

We do **not** need to copy their stacks to copy their products. Our MapLibre choice is valid; the gap is data services and the matching workflow, not the renderer.

### 4. Recommended stack to build the custom version

#### Public map + browsing (StartupMap equivalent)

| Layer | Recommendation |
| --- | --- |
| Renderer | Keep **MapLibre GL JS** (no Mapbox migration needed) |
| Tiles/style | Keep **OpenFreeMap**; evaluate a paid provider only when coverage/style demands it |
| Frontend | **React + Vite** once the static vanilla JS outgrows maintainability |
| Data API | **Supabase** PostgREST/RPC for companies, jobs, offices, followers |
| Asset serving | Self-host logos (already done); a bounded, allowlisted logo-proxy only if needed |
| Hosting | Vercel static + Supabase |

#### Matching + private agent (Jack & Jill equivalent)

| Layer | Recommendation |
| --- | --- |
| Frontend | **Next.js (App Router) on Vercel** for the authenticated workspace |
| Auth | Supabase Auth (magic link + optional LinkedIn OIDC) |
| Storage | Supabase private storage for CVs |
| Job ingestion | Hosted Python worker + official ATS connectors + employer self-serve (see employer plan) |
| Matching | Deterministic evidence coverage now; add grounded LLM only for nuanced interpretation |
| Queue | Postgres-backed durable queue (or managed queue if load justifies it) |
| Notifications | Supabase/email adapter with opt-in digests |

#### Two-sided marketplace (later)

Jack & Jill's "direct introduction, paid on hire" requires a **company-side product and recruiter participation**. That is a separate employer surface (see the employer-integration appendix below), not something the matching model alone can produce. The customer logos observed on `/jack` reflect that employer participation, not an automation trick.

### 5. Observed feature surface → build items

1. **Company/startup browser** with filters (city, sector, funding stage, hiring status).
2. **Open-roles list** with counts and source links.
3. **Company profile** with logo, description, website, location, stage.
4. **Follow company / save job** (requires accounts).
5. **"Match me" onboarding** (role areas, experience, work style, location, stage, industries).
6. **Match count + match email** (opt-in digest).
7. **Candidate "Jack"** — preferences, proactive discovery, explanations.
8. **Recruiter "Jill"** — employer side, mutual-interest introductions (later, gated by participation).

### 6. What remains unverified

- StartupMap's and Jack & Jill's backend architecture, data pipelines and matching models (not observable from public bundles).
- Whether StartupMap's `/api/*` routes are serverless functions, a Supabase API, or another backend (only Supabase storage and route strings are observed).
- The exact cost/licensing of any hosted map, geocoding or model service we might adopt — provider terms change and must be checked at decision time.
- Any access tokens, credentials, or private coordinates (deliberately not extracted). PostHog's embedded `phc_…` value is a public analytics key, not a secret to rotate.

### References

- [Unified implementation plan](IMPLEMENTATION_PLAN.md) — map details and the autonomous job agent.

- Architecture Q&A appendix — current implementation and constraints.

## Appendix — App architecture & automation (Q&A)

This document answers the product questions against the current repository. **Current** means implemented in code, not necessarily verified in production. **Proposed** means work still to build. External documentation is linked at the end.

### 1. How are jobs updated on our website today?

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

#### What we should build for near-real-time updates

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

### 2. How do other job websites do it?

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

### 3. Is there a map API for street-level cities and exact company locations?

See the [unified implementation plan — map](IMPLEMENTATION_PLAN.md#part-i--map-implementation) for the consolidated StartupMap/YC reuse discussion, Google free allowances and restrictions, Leaflet/Mapbox/MapLibre comparison, file-level zoom/marker changes, office enrichment schema, costs and rollout tests.

**Yes, but displaying a map and knowing an office address are different problems.**

#### What we use today

- **MapLibre GL JS:** browser renderer, zoom/pan, and markers.
- **OpenFreeMap:** map style/vector tiles, currently `https://tiles.openfreemap.org/styles/positron`.
- **Our company data:** supplies the marker coordinates. Tiles do not discover company addresses for us.
- **Wikidata enrichment:** 1,109 directory companies have domain-linked HQ coordinates in the current export. Other points can be city/country estimates or unmapped.
- `vercel-site/app.mjs` currently sets **`maxZoom: 10`**. This limits the interface; it is not a finished street-level experience. Raising the limit, adjusting marker grouping, and testing navigation are still needed.

Even a coordinate labeled HQ is a sourced claim, not a surveyed guarantee of the entrance, current office, or the workplace of a vacancy. A company can have several offices; remote jobs may have none.

#### Three services/data layers to distinguish

| Need | Solution | What it does not establish |
| --- | --- | --- |
| Street map and building detail | MapLibre + suitable tiles, or Mapbox/Google Maps | Which office belongs to a company |
| Address → latitude/longitude | Geocoder, such as a commercial provider or hosted Nominatim | Whether the address is current or relevant to the job |
| Company → verified office | Official contact pages, licensed places data, reviewed business records | Every vacancy's actual workplace |

Street-level map zoom is also different from **street photography**. Street View/Mapillary-style imagery is a separate product with its own coverage, license, and cost.

#### Recommended implementation

Keep MapLibre/OpenFreeMap; add an `offices` table. Store company ID, address, office type, source URL, verification date, coordinates, provider, and precision (`building`, `street`, `city`, `country`). Geocode public business addresses and manually review low-confidence matches. Never place a city-centre estimate as if it were an exact office entrance.

Associate a job with an office only when the listing or employer supports the association. Otherwise display its stated city/region or remote status. Do not substitute HQ coordinates for vacancy location.

For thousands of records, choose a provider whose terms allow our volume, storage, and display on this map. Google/Mapbox geocoding and Places have product-specific attribution, caching, and display restrictions; buying an API key is not permission to mix all results freely. Public Nominatim has strict usage rules, including a maximum of one request per second, no client autocomplete, and restrictions on systematic queries. It should not be our unrestricted bulk company-enrichment backend.

### 4. What is the GitHub bot used for here?

**`github-actions[bot]` is an automation identity, not an AI recruiting agent.**

Our workflow checks out `main`, installs dependencies, runs the public job exporter, and commits a changed `jobs.json` using that identity. Its `contents: write` permission lets it push that change. The GitHub-hosted runner executes the code; the bot name identifies the resulting commit.

It does not search LinkedIn, assess CVs, send applications, or continue running between scheduled jobs. Nor is it GitHub Copilot or Dependabot.

GitHub Actions is useful for tests, deployments, and low-frequency public snapshots. It is a poor permanent backend for private per-user queues, CVs, and interactive browser sessions. A bot commit also does not automatically guarantee every downstream workflow runs: events created with `GITHUB_TOKEN` have recursion restrictions. Verify the Vercel integration end to end rather than assuming publication from a green export step.

Private CVs, contact data, credentials, and application histories must never be committed into this public snapshot pipeline.

### 5. How do we build role folders with manual and autonomous modes?

See the [unified implementation plan — job agent](IMPLEMENTATION_PLAN.md#part-ii--autonomous-job-agent-implementation) for source registries, shared ingestion, private recommendation tasks, queue semantics, AI boundaries, cost controls and acceptance tests.

**This is feasible. The missing piece is a hosted, durable workflow—not an impossible AI capability.** Some building blocks already exist: CV parsing, deterministic matching, target/application storage, and a reviewed browser-application runner. They do not yet form this complete hosted product.

#### User flow

1. Create a folder such as **“Junior ML — Belgium/remote.”**
2. Set role titles, seniority, locations, work authorization, salary preferences, exclusions, and a selected CV version.
3. Add jobs manually by official URL, or enable discovery from approved sources. The agent recommends additions; user-saved jobs remain distinguishable from auto-discovered ones.
4. Choose **Manual** (“Analyze selected roles now”) or **Autonomous preparation** (scheduled discovery and analysis).
5. Receive an evidence-based fit report. When a usable score is below 70%, receive exactly two targeted project proposals and contact suggestions.
6. Review suggested projects, messages, and applications. Approve each external send or final employer submission separately.
7. Add completed project evidence and rerun matching. A project proposal alone must never increase the CV score.

#### Proposed architecture

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

#### Manual versus autonomous is a permission boundary

| Action | Manual mode | Autonomous preparation mode |
| --- | --- | --- |
| Discover jobs | User starts search | Scheduled within folder scope and quotas |
| Analyze and match | User selects jobs | Automatically for new/changed relevant jobs |
| Propose projects and contacts | On request | Below-threshold usable results |
| Draft outreach | On request | Allowed, without sending |
| Message a person or submit an application | Explicit approval | Still explicit approval per external action |

Autonomous preparation can provide most of the benefit without turning the product into a spam sender. An optional later sending mode would need explicit, narrow consent, supported channel APIs, quotas, and jurisdiction/platform review. It is not included in the currently approved application safety model.

### 6. What should “under 70%” mean?

Current `hosted_matching.py` computes roughly:

```text
coverage = matched extracted job skills / extracted job skills × 100
```

That is **keyword/skill coverage**, not a calibrated probability of being hired or even a full suitability judgment. If no skills are extracted it returns no score, not zero. The current pipeline also truncates text and can miss evidence; scanned CVs may need OCR.

For the new workflow, first check hard eligibility separately: location, authorization, required license, and similar constraints. Do not average these away with technical skills. Then assess each job requirement against actual CV/project evidence, with source excerpts and uncertainty.

A possible initial weighted coverage formula is `100 × Σ(requirement weight × evidence coverage) / Σ(requirement weight)`, with coverage levels defined and tested. The weights and partial-credit rubric are a product proposal, not a validated hiring model. Show separate confidence and extraction quality; an unreadable CV should trigger repair, not two irrelevant projects.

Use 70% as a user-adjustable routing threshold. Exactly 70% does not satisfy “under 70%.” Validate the rubric on human-reviewed examples before calling the score reliable. A project cannot remedy work authorization or manufacture professional experience.

#### Exactly two useful projects

For a usable score below 70%, cluster the highest-priority learnable gaps and propose two distinct projects, each with:

- The missing requirements and job-description evidence it addresses.
- A concrete scope, prerequisites, estimated effort, and accessible dataset/tools.
- Deliverables: repository, tests, demo, and short technical write-up.
- Acceptance criteria and a rubric for assessing completed work.
- A truthful suggested CV bullet **only after completion and evidence review**.

For example, a role missing SQL and deployment evidence could produce (1) a tested analytics pipeline and (2) a deployed model API with monitoring. That example is not a recommendation for every role. If relevant project ideas cannot be grounded, say so instead of inventing a fit benefit.

An LLM can help interpret requirements and draft projects/messages, but it needs a configured provider or local model, budgets, evaluation, and consent for private CV processing. Deterministic templates can provide a simpler first release. The existing deterministic application runner does not itself require an LLM key.

### 7. Can the agent find people and infer email addresses?

**Yes for researched suggestions and drafts; guessing is not verification, and discovery is not permission to contact.**

Prefer official team pages, public recruiting contacts in adverts, and publicly documented professional profiles. Store the source URL, observed date, person/role relevance, and confidence that the person still works there. Suggest a hiring manager, team member, or recruiter only when evidence supports that association; otherwise provide a search link rather than invent a person.

#### Channel-specific constraints

- **LinkedIn:** generate relevant search/profile links and a personalized draft for the user. Do not scrape logged-in profiles or automate connections/DMs with a browser bot. LinkedIn explicitly restricts these activities. LinkedIn login/OIDC is identity linking, not a people-search or messaging permission grant.
- **X/Twitter:** use permitted public sources or an authorized API within its current tier, rate limits, and automation rules. A public profile does not guarantee DM availability. Credentials, access, and cost must be established before promising automatic outreach.
- **Email:** prefer a published recruitment/team address. For sending, use a user-authorized mailbox or configured provider, with secure token storage, recipient confirmation, quotas, suppression, and bounce handling. Sending from our domain also requires appropriate email authentication and reputation controls.

#### What about guessing `firstname.lastname@company.com`?

It is technically easy to generate possible work addresses, but a domain pattern can be wrong, a person may have left, and a catch-all mail server can accept nonexistent recipients. DNS/MX records prove only mail routing exists; they do not prove a named mailbox exists or belongs to that person. Commercial verification services also return uncertain results.

If we offer inference, label it **“inferred, unverified”**, preserve its pattern evidence, and do not silently send to it. Prefer a public alternative; require explicit recipient confirmation before sending. Never attach a CV automatically to a guessed address: the wrong recipient would receive personal information. Avoid repeated SMTP probes or mass test emails.

Publicly accessible professional contact details can still be personal data. We need purpose limitation, retention/deletion, access control, and an appropriate legal basis. Rules depend on jurisdiction, recipient type, and whether the communication is legally marketing; not every job enquiry is automatically marketing, and not every B2B message is exempt. UK ICO guidance is one example, not a worldwide license. Obtain legal review before scaled outreach, handle objections, and never treat a public email as blanket consent.

### 8. What concretely prevents us from doing this now?

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

### 9. Recommended delivery order

1. **Manual vertical slice:** hosted login, private CV, one role folder, manually saved official job, evidence report, two below-threshold project suggestions, sourced contact links, and editable outreach draft. No automatic sends.
2. **Autonomous preparation:** reviewed-source job ingestion, scheduled folder runs, durable tasks, deduplication, fresh/stale indicators, budgets and notifications.
3. **Reviewed execution:** connect a supported sending channel, approve exact recipients/content, record actual outcomes, and retain the existing per-application final approval. Stop on CAPTCHA, ambiguous fields, or unsupported employer flows.
4. **Coverage and quality:** expand approved sources, improve office data, calibrate scores, and monitor false matches and project usefulness.

Acceptance tests should include: a 69% score produces two proposals; 70% does not trigger the below-threshold rule; missing evidence is “unknown”; a failed source does not close jobs; repeated tasks do not duplicate messages; one user cannot access another's CV; edited messages invalidate approval; inferred contacts never auto-send; HQ and vacancy location remain distinct.

**Bottom line:** build a dependable research-and-preparation assistant first, with human approval for external actions. That delivers the proposed workflow without claiming instant worldwide jobs, exact offices everywhere, guaranteed match percentages, or verified guessed emails.

### Sources and repository references

#### Repository evidence

- [`refresh-jobs.yml`](../.github/workflows/refresh-jobs.yml): schedule, bot identity and snapshot publishing.
- [`export_public_jobs.py`](../scripts/export_public_jobs.py): board collection, limits, geography and failure behavior.
- [`role_discovery.py`](../src/tau_job_application/role_discovery.py): vetted employer boards.
- [`app.mjs`](../vercel-site/app.mjs): MapLibre/OpenFreeMap and current zoom limit.
- [`export_public_map.py`](../scripts/export_public_map.py): public directory and location enrichment.
- [`hosted_matching.py`](../src/tau_job_application/hosted_matching.py): current CV extraction and coverage formula.
- [`hosted MVP migration`](../supabase/migrations/202610270001_hosted_mvp.sql): private workspace schema and policies.
- [`rule_based_apply.py`](../src/tau_job_application/rule_based_apply.py): deterministic reviewed applications.

#### External documentation

1. [Greenhouse Job Board API](https://docs.greenhouse.io/job-board) and [Recruiting webhooks](https://docs.greenhouse.io/webhooks.html).
2. [Lever Postings API](https://github.com/lever/postings-api).
3. [Google JobPosting structured data](https://developers.google.com/search/docs/appearance/structured-data/job-posting) and [Indexing API](https://developers.google.com/search/apis/indexing-api/v3/quickstart).
4. [MapLibre GL JS](https://maplibre.org/maplibre-gl-js/docs/) and [OpenFreeMap](https://openfreemap.org/).
5. [Public Nominatim usage policy](https://operations.osmfoundation.org/policies/nominatim/).
6. [LinkedIn prohibited software and extensions](https://www.linkedin.com/help/linkedin/answer/a1341387/prohibition-of-scraping-software).
7. [ICO B2B marketing guidance](https://ico.org.uk/for-organisations/direct-marketing-and-privacy-and-electronic-communications/business-to-business-marketing/). UK-specific; check current guidance and local law before launch.
8. [GitHub: triggering a workflow](https://docs.github.com/en/actions/how-tos/writing-workflows/choosing-when-your-workflow-runs/triggering-a-workflow).

Provider terms, permissions, and pricing can change. Confirm them for the selected integration before implementation.

## Appendix — Ingestion bottlenecks

Answers to "why can't we just grab every startup and every public company's roles?"

### Short answer

**Storage is not the bottleneck. Data access is.** The ceiling is set by which employers expose a machine-readable public job feed, plus how fast and accurately we can discover and refresh those feeds.

### Current state

- Company directory: 10,247 companies with websites and locations.
- Job sources: ~99 registered ATS boards (Greenhouse/Lever/Ashby/Workable/Recruitee/Feed), mostly auto-detected from the catalogue.
- Public snapshot: ~454 roles across ~67 companies (the rest of the detected companies currently have no geocodable roles in scope).

### Bottleneck 1 — which ATS a company uses (the real ceiling)

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

### Bottleneck 2 — discovering which ATS a company uses

`register_job_sources.py` fetches a company's homepage + `/careers` + `/jobs` and pattern-matches ATS board URLs. Constraints:

- **Time/rate limits:** thousands of companies × ~4 fetches each, with politeness and timeouts.
- **Blocks:** Cloudflare challenges, robots.txt, JS-only pages that return no ATS link in the raw HTML.
- **False positives:** a partner's board link (e.g. "built on Benchling") can be misattributed; mitigated by the name-match guard and manual disabling.

### Bottleneck 3 — refresh and freshness

Once registered, each source is fetched on the daily schedule. Hundreds of boards means hundreds of API calls; failures, closures, and stale data need reconciliation. This is operational cost, not storage.

### Why storage is a non-issue

Rough upper bound:

```text
10,000 companies × ~50 roles × ~3 KB per role ≈ 1.5 GB worst case
```

In practice the bounded public snapshot is a few hundred KB to a few MB, and the private local app stores CVs and targets in a small SQLite file. Postgres/Supabase would handle the full job table with room to spare. **Storage does not limit us.**

### What would actually raise coverage

1. **Scan more companies (already running):** `register_job_sources.py --regions Europe,UnitedStates,Asia,... --limit N` — detects more Greenhouse/Lever/Ashby boards, including public companies. Cheap; hit the ATS ceiling quickly.
2. **Feed sources:** point `Feed` rows at public RSS/Atom/JSON feeds (regional boards, Workable/Recruitee feeds).
3. **Employer self-serve:** startups/companies submit jobs directly (`submit_job.py` / a hosted form) — bypasses the ATS problem entirely.
4. **Browser-rendered ingestion (Workday etc.):** highest coverage, highest cost/risk; requires a headless worker, consent, and careful rate limiting. Not currently done.

### Recommendation

Treat the ATS registry + feed + self-serve as the production path. Add browser-rendered Workday/SuccessFactors ingestion only if the measured gap justifies the operational cost and the terms of service allow it.
