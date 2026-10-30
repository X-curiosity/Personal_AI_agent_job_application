# Map implementation plan: street-level browsing and trustworthy company locations

Planning document; no map behavior is changed by this document. Recommendations are not final user-approved provider purchases. This consolidates the discussion of StartupMap/YC locations, Google Maps free usage, Leaflet/Mapbox/MapLibre, and concrete implementation work.

## 1. Decision framework

Recommended starting point: retain **MapLibre GL JS + OpenFreeMap**, improve browsing, and enrich office locations separately. A map renderer does not discover where companies work. A company catalogue does not establish current vacancies.

Four independent components:

1. **Renderer:** draws the interactive map.
2. **Tiles/style:** roads, buildings, labels and visual appearance.
3. **Company/office data:** company identity, business addresses and location evidence.
4. **Geocoder:** converts a known address into coordinates, with varying precision.

Street-level zoom is not street photography. Street View-style imagery would be a separate integration and is not needed for the initial product.

## 2. Leaflet, MapLibre and Mapbox

| Option | What it supplies | Cost and trade-offs |
| --- | --- | --- |
| Leaflet | Open-source library, commonly using raster base-map tiles plus interactive overlays | Free library; tiles/geocoding separate. Good for straightforward maps; plugins add capabilities. No compelling reason to migrate our existing richer map. |
| MapLibre GL JS | Open-source GPU-rendered vector map library | Free library; choose tiles/geocoding independently. Supports detailed styling, clustering, terrain and building extrusion with suitable data. Current implementation. |
| Mapbox | Commercial platform including Mapbox GL JS, hosted maps, styling and additional search/navigation services | Usage-based pricing with service-specific allowances. Useful integrated tooling; licensing, limits and ongoing costs must be evaluated. |

Raster tiles are pre-rendered pictures. Vector tiles carry geometry/attributes that the browser can style and draw. Leaflet also supports vector overlays; it is not limited to images. Large datasets work best with clustering and appropriate rendering layers in any implementation, rather than thousands of HTML markers.

**Recommendation:** spend effort on source quality and interaction, not a renderer migration.

## 3. Can we reuse StartupMap and YC locations?

Yes, public location information can be a starting point **where collection and reuse are permitted**. Our project has already imported public StartupMap city/company information and YC records; it has not imported private StartupMap coordinate APIs.

- Company plus city/country: useful for city-level discovery, not an exact office.
- Public business address: geocode after checking source freshness and applicable terms.
- Coordinates attached to a marker: do not assume accuracy or permission to redistribute them. They may represent city centres, old HQs or presentation offsets.
- A crawl allowance or publicly accessible endpoint is not a redistribution license. Check current terms and request a permitted export or agreement where bulk reuse is unclear.
- The specific YC globe mentioned in discussion has not been identified/verified. Do not claim to have inspected its coordinates.
- Neither directory is an exhaustive worldwide startup registry.

Keep source URLs, collection dates and permitted uses. Deduplicate identities conservatively using verified domains and other evidence rather than names alone. Preserve multiple offices rather than overwriting a company with its latest imported location.

For a low-cost launch, group companies by city using a reusable, licensed city-coordinate dataset. Add verified offices progressively. Do not scatter companies randomly around a city to suggest street accuracy.

## 4. Google Maps: free trial versus ongoing allowance

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

## 5. Current code and why raising one number is insufficient

In [`vercel-site/app.mjs`](../vercel-site/app.mjs):

- Map creation uses `maxZoom: 10`, `minZoom: 2` and `scrollZoom: false`.
- Country card selection jumps to zoom 5; city selection jumps to zoom 8.
- `fitResults()` caps automatic bounds fitting at zoom 7.
- `renderPins()` displays country groups at zoom ≤3, city groups at zoom ≤7, and viewport-filtered individual/co-located groups above that.
- Markers are HTML elements rebuilt during rendering. Co-location groups use kind and coordinates, rather than complete office identity.
- `currentMapPoints()` currently constructs directory locations without carrying a full precision/provenance model into each point.

Changing `maxZoom` alone allows closer viewing, but does not fix ambiguous marker positions, overlapping groups, automatic zoom-out, or office accuracy.

## 6. Implementation track A: street-level browsing

### A1. Centralize camera rules

Introduce named constants for world, country, city, office and maximum zoom. Start testing a maximum of **18**, city navigation around **11–12**, and verified building selection around **16–17**. These are initial UX values to tune, not exact map-scale guarantees.

Verify the chosen style/tile coverage at those zooms; increasing camera zoom may overzoom existing tiles rather than reveal new detail. Retain a usable list if tiles fail.

Update map creation, card navigation and `fitResults()` together. Bounds fitting should depend on the action and location precision:

- Country selection: fit the relevant country/points without pretending a single country-centre point is precise.
- City selection: fit the city or a conservative city view.
- Exact office selection: allow building-scale zoom when supported by evidence.
- Routine filter changes: avoid unnecessarily resetting an intentional user camera position.

Use reduced-motion preferences. Keep navigation buttons and mobile gestures; decide explicitly whether wheel zoom should require map focus to avoid trapping page scrolling.

### A2. Preserve precision through rendering

Carry `precision`, `location_kind`, `source_url` and verification timestamps into map features. Existing `hq` denotes a location role/source category, not automatically building-level accuracy. Conservatively map legacy data to unknown/approximate precision until evidence supports a finer label.

At street zoom:

- Verified building/address: precise-looking office pin with source details.
- City/country only: clearly labelled area marker or area result, never an office entrance pin.
- Unknown coordinates: remain searchable in the list; do not invent a location.

Never invent a radius of uncertainty. Use a region outline when known, or a labelled estimate when it is not.

### A3. Cluster and select without hiding records

For the scalable implementation, build GeoJSON point sources with stable company/office/job IDs. Use MapLibre clustering for dense groups and GPU layers for most points. Keep jobs, offices and estimated locations distinguishable; use separate sources where clustering semantics differ.

- Clicking a cluster uses cluster expansion zoom while bounded by our camera limits.
- If records share the same coordinate and cannot separate, open a paginated co-located-results list.
- Preserve country-qualified city identity in selection, URLs and history.
- Cluster counts reflect the active filters; distinguish company counts from role counts.
- Use stable IDs for job-to-company associations rather than relying permanently on case-insensitive names.

Company logos should appear only for selected or a bounded number of visible unclustered companies. Avoid loading all thousands of logos into the GPU sprite atlas or DOM at once. Missing official logos must not be replaced with invented brands; count/selection markers can remain neutral UI elements rather than being presented as company logos.

A first incremental release can retain bounded DOM markers while fixing precision and co-location selection; GPU-layer migration is the next scaling step if profiling warrants it.

### A4. Accessibility and performance

Maintain a synchronized searchable list as the keyboard-accessible route to every result. Provide visible focus, descriptive labels and accessible details panels. Canvas interaction alone is insufficient.

Avoid rebuilding every marker on idle events. Update data when filters change; reconcile visible markers on settled camera changes. Profile dense cities and slower/mobile devices; set measured budgets for marker count, memory and interaction latency rather than claiming performance without testing.

## 7. Implementation track B: accurate company offices

### B1. Separate offices from companies and jobs

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

### B2. Source and geocode

1. Start with official contact/location pages and permitted directory exports.
2. Extract public business addresses with URLs and observation dates.
3. Normalize addresses without discarding floor/unit information from the displayed source record.
4. Query a provider whose terms permit our intended storage and MapLibre display, or operate our own appropriate service.
5. Store precision and ambiguous candidates; do not automatically accept a similarly named business in the wrong country.
6. Review conflicts and low-confidence results. Offer an operator correction workflow with audit history.
7. Refresh according to source/provider obligations and mark aging evidence as stale.

Public Nominatim is not an unrestricted bulk enrichment service: its policy includes a maximum of one request per second, no client autocomplete and restrictions on systematic queries. Use a suitable hosted provider or self-host for workloads beyond the public service's permitted use. Self-hosting avoids per-request provider billing, not infrastructure/operations costs.

Workers must use timeouts, bounded responses, private-network/redirect protections, caching where permitted, retries with backoff and stops on rate limits. Do not publish private/home addresses merely because they were discovered during enrichment.

### B3. Associate vacancies honestly

Link a job to an office only when the listing or employer provides evidence. Never substitute HQ for a remote job or a role in another city. Show job location as stated, company office information separately, and uncertainty prominently.

## 8. File-level delivery plan

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

## 9. Free versus paid budget model

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

## 10. Rollout and acceptance tests

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

## References

- [Leaflet](https://leafletjs.com/) and [quick start](https://leafletjs.com/examples/quick-start/).
- [MapLibre GL JS documentation](https://maplibre.org/maplibre-gl-js/docs/).
- [Mapbox GL JS pricing model](https://docs.mapbox.com/mapbox-gl-js/guides/pricing/).
- [OpenFreeMap](https://openfreemap.org/).
- [Google Maps billing FAQ](https://developers.google.com/maps/billing-and-pricing/faq) and [geocoding policies](https://developers.google.com/maps/documentation/geocoding/policies).
- [Nominatim usage policy](https://operations.osmfoundation.org/policies/nominatim/).
- [StartupMap](https://startupmap.one/) and [YC directory](https://www.ycombinator.com/companies/).

Check current provider documentation and the applicable agreement before implementation; pricing, permissions and service capabilities can change.
