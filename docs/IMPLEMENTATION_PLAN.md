# Hired: map and autonomous job-agent implementation plan

This unified plan combines public startup-map browsing with shared job collection and a private recommendation agent. It preserves the implementation detail from the former map and job-agent plans.

**Status:** proposed implementation, not a claim that these features are deployed. Provider recommendations are not authorization to purchase services. See the [architecture Q&A](APP_ARCHITECTURE_AND_AUTOMATION.md) and the product-direction appendix below for broader context.

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
- [App architecture and automation](APP_ARCHITECTURE_AND_AUTOMATION.md): current ingestion, job freshness, and provider constraints.

## Appendix — Product direction (StartupMap + Jack & Jill)

### Product direction

Combine a **public startup map** with a **private career agent**, both using the same company and jobs database. They are two ways of discovering opportunities, not separate apps.

This is a proposed integration plan, not a claim that these features are already live. For implementation details and current limitations, see [App architecture and automation](APP_ARCHITECTURE_AND_AUTOMATION.md).

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
- [Hired app architecture and automation](APP_ARCHITECTURE_AND_AUTOMATION.md): current implementation, job ingestion, mapping providers, scoring, outreach and concrete blockers.

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

- [App architecture and automation](APP_ARCHITECTURE_AND_AUTOMATION.md) — current implementation and constraints.
