# StartupMap join flow — reverse-engineering notes

Target: `https://startupmap.one/join?reason=matches` (requested for pattern
analysis on 2026-10-20). Method: REA (`rea-agents` CLI, static JavaScript
analysis) over the site's own shipped bundles, plus focused reading of the
beautified chunks. No runtime execution, no account created, no private data.

## REA evidence

- `ev_ab8484b722453b95298377e2c36028caa0c2be1881e7d2027e100a611452554e` —
  analysis of `/static/index-D4HqP7dV.js` (992 KB Vite bundle). Limitation
  recorded by REA: the worker exhausted its heap on this file; graph coverage
  is incomplete and was not read as absence.
- `ev_322ee66a01ad989610c0b9d563649d87e77865d29dc889aef16c91d3d8d5c1cf` —
  analysis of the six route chunks: JoinPage, MatchesPage, useLiveMatches,
  useProfileLabels, profileSummary, FinishProfilePrompt. 295 findings,
  23,110 semantic nodes, 34,463 relations.

## How the feature works (static observations)

**Join page.** `?reason=matches` is only a telemetry/referral tag
(`join_shown {reason}`); the flow itself is identical. Two sides
(`side=hiring` → founder, otherwise seeker). The seeker path is a guided
multi-step onboarding whose steps each declare `key / valid / saves / shows`:

1. **roles** — grouped taxonomy: Join early (Early-Stage Generalist), Build
   the product (Engineering, Product, Design), Sell and grow (Sales,
   Marketing, Customer Success), Run the company (Operations, Finance,
   Recruiting & HR, People, Legal), plus Internship.
2. **experience** — `lt1 / 1_3 / 3_5 / 5_10 / 10_plus`.
3. **now** — current status.
4. **tools** — large curated tool list; only shown when a role is picked;
   CTA reads "Continue with N tools".
5. **how_where** — work styles (remote/hybrid/onsite) and relocation mode
   (everywhere / continent / country / named cities), with a conditional
   city step shown only for hybrid/onsite answers.
6. **stage** — early (pre-seed/seed), growth (Series A–B), scale-up
   (Series C+), bootstrapped.
7. **industry** — picked vs any.
8. **start** — availability. 9. **about** — identity + explicit
   `share_with_startups` consent.

**Live matching.** A sticky sidebar shows "N roles match you from M startups"
with a logo fan, recomputed client-side on every answer. The match predicate
(`useProfileLabels`) passes a job when: role type overlaps (with careful
generalist semantics), stage and industry filters pass (only once their steps
are answered), work style matches (all three selected = no filter;
hybrid/onsite jobs accept either), and a location function classifies the job
as commute / continent / country / named-city / everywhere. Ranking: actively
hiring startups first, then newest `posted_at`, deduplicated per startup.

**Persistence.** The draft saves per step to Supabase; profile status
incomplete → complete; `/matches` renders the ranked roles.

## What we took vs. what we deliberately changed

**The map (observed in the main bundle).** StartupMap's map is Mapbox GL with
per-startup `latitude/longitude` from `/api/startups` (~620 KB), supercluster
for clustering, toggles for Clustering / Show logos / Show names, filter chips
(city, industry, stage, hiring status, team size, founding year, accelerator),
a search box with match-count badge, pin click → preview card → `/startup/:id`
detail, and a `?zoomCity=` deep link that `flyTo`s the city. Pin colours encode
hiring status (`actively_hiring` / `open_to_talent` / `not_hiring`).

Taken: five-step guided flow, conditional steps, live count sidebar,
"later filters don't apply yet" semantics (our `for_step`), explicit consent
copy, honest limit notes — and for the map: signal-colored pins, stage
filters, a matched-count line, and click-for-detail via tooltip + table.

Changed on purpose:

- **Generalized beyond startups.** Their stage groups (early/growth/scale/
  bootstrapped) become early / growth / scale-up / **big company**, computed
  from the facts we actually hold (team size, funding-stage labels, public
  listing) with the deciding fact always displayed (`stage_basis`).
- **No server-side profile.** Preferences persist in the local SQLite
  (`match_preferences`, one row per career track). Nothing is shared with
  employers; there is no "share with startups" because nothing leaves.
- **Company count, not role count.** Our catalogue does not store per-company
  role inventories, so the live number counts *hiring companies* (with a
  verified-live sub-count) instead of roles.
- **No telemetry, no auth wall, no animations.**

## The map adaptation (added after the join flow)

- **No Mapbox token and no supercluster.** The map renders with pydeck on the
  same Carto basemap as the app's other maps; the bounded ~500 hiring
  companies do not need clustering.
- **Offline geocoding, never guessed.** Their `/api/startups` ships exact
  coordinates; our directories ship free-text locations, so
  `city_coordinates.py` resolves them against a curated gazetteer (~140
  cities + country centroids). Results carry a precision label: city pins are
  exact, country-level pins render as large soft discs, and remote/unplaceable
  companies are counted openly under "Not pinned" instead of being invented.
  On the current local data this pins 97.6% of hiring candidates.
- **Colour encodes the generalization.** Pins are colored by company stage
  (early/growth/scale-up/big) rather than only hiring status, keeping the
  big-company generalization visible; live-board companies get a stronger pin.
- **Match me integration.** A checkbox applies the saved Match me answers as
  the map's filter, tying the two adaptations together.
