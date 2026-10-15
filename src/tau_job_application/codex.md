# Career hub feature context

See [root context](../../Codex.md) and [delivery report](../../docs/ROLE_FIRST_IMPLEMENTATION_REPORT.md).

## Modules and interfaces

- `career_hub.py`: `FIELDS` many-to-many interest graph, `Interests`, `HubStore`, `draft_documents`, `contact_searches`, `infer_email`.
- `career_hub_ui.py`: `render_portal(api, track, view)`, onboarding, role clusters, vacancy workspace, upload/document review, networking, and connection controls. `api` is the existing UI module, allowing its stores and source adapters to be injected in tests.
- `company_catalog.py`: `CatalogCompany`, `CompanyCatalogStore`, bounded CompaniesMarketCap/yc-oss parsers and fixed-host fetchers (`_fetch` takes an explicit `max_bytes` bound). Directory rows remain distinct from `VettedCompanyBoard`; a supported board is created only by the explicit reviewed mapping flow.
- `capital_atlas.py`: bounded Global Capital Atlas (capital.theojaffee.net) importer; parses the company array embedded in the fixed-host page asset into reviewed `CatalogCompany` leads with value-threshold filters. A valuation is never a vacancy signal.
- `yc_directory.py`: `YCCompany`, `YCFilters` (status/hiring/top/batch/industry/region/team/query), `filter_yc_companies`, `directory_facets`, `YCDirectoryStore` snapshot tables (`yc_directory`, `yc_directory_snapshots`). The full yc-oss `all.json` is fetched only on explicit refresh with a 24 MB bound.
- `yc_directory_ui.py`: `render_yc_browser(api)` at `?view=yc`; seeds Status/Hiring from `status`/`flags` query params, explicit refresh, tick-to-save into the company catalogue.
- `eligibility.py`: `ResidencyProfile` (self-declared, alias-normalized), rule-based `eligibility_checklist` with domestic/free_movement/existing_permit/sponsorship pathways, official-source links, mandatory not-legal-advice disclaimer; `ResidencyStore` (`residency_profiles` per career track).
- `eligibility_ui.py`: `render_eligibility(api, track)` at `?view=eligibility`.
- `agents.py`: bounded multi-agent team on `tau_agent` — `AgentSpec` registry (company_scout, eligibility_advisor, application_prep), deterministic `route_request` with visible reasons, `TeamCoordinator.run` enforcing per-spec turn limits and tool-call budgets via `before_tool_call`, and an `AgentRunResult` action trace. Provider errors surface exception types only.
- `agent_tools_extended.py`: store-backed Tau tools for the scout (search/refresh/save YC snapshot) and eligibility advisor (save/get residency profile, build checklist).
- `agents_ui.py`: `render_agents_console(api, track)` at `?view=agents`; disabled without exported credentials, per-use consent, routing preview with manual override, local run history with traces.
- `career_inbox.py`: `Reply`, `read_gmail`, `read_slack`, `classify_reply`, `InboxStore`. Only fixed official HTTPS hosts are fetched; redirects rejected, 15-second timeout, 2 MB response bound. Gmail reads a bound thread's metadata and up to ten recent snippets; Slack reads fifteen recent channel messages. Neither is a complete mailbox/history sync.
- `pipeline.analyze_texts(..., confirmed_skills=...)`: optional subset of parsed CV skills, applied before matching and tailoring, without changing the original CV text. Existing callers remain unchanged.
- `application_tracker*`: original persistent stages/history/export, now linked to the vacancy workspace and reply audit events.
- `workspace_ui.choose_scope(..., compact=True)`: portal-only career-track sidebar; persists departing legacy inputs and clears legacy widget scope to prevent old draft widgets overwriting portal edits.

## State and data flow

Onboarding persists fields/subfields/roles per career track. Opening a role creates/reuses a local discovery thread and fetches its first cluster once per session when no run exists; refresh is explicit thereafter. Registered source responses are locally ranked and stored with their provenance. No profile is sent to a job feed. The company database imports at most 100 source records on an explicit action; mappings verified against a public ATS feed join future role refreshes.

Opening a vacancy creates/reuses its preparation thread and a Saved application. Saving and assessing documents stores raw CV in the existing draft, letter/resume in `career_documents`, and analysis in the existing snapshot. Projects use `EvidenceMatchStore`; planned/unconfirmed projects remain excluded. Changed CV or selected skills suppress the fresh score until reassessment. Legacy shortlist records retain original tracker ownership while documents open in a dedicated preparation thread.

Reply binding records provider, exact conversation, expected sender and opt-in time. Reading requires UI consent and a server token. Each message is matched and deduplicated; literal outcome cues produce a review item. Only clear, future Gmail outcomes may auto-progress an already applied/contacted/interview application. A source reply event and tracker history explain the change; no email or acceptance is sent. Polling runs at 60 seconds only while the opted-in application page remains open.

## Storage and ownership

`career_interests`, `career_role_pages`, `career_documents`, `career_reply_bindings`, `career_reply_events`, `company_catalog`, `company_catalog_imports`, `company_job_boards`, `yc_directory`, `yc_directory_snapshots`, and `residency_profiles` extend the same SQLite database. Directory and atlas rows are shared public-company reference data; residency profiles are personal, track-scoped, and user-declared. Parameterized statements and server-side track/thread ownership checks are used where records are personal. Catalogue rows are shared across local career tracks and contain public company facts only. Foreign keys cascade with parent records. This is local record scoping, not multi-user authorization. Reply excerpts are retained until their application is removed; no automatic retention expiry exists.

Interests: at most 20 roles, names at most 100 characters. Documents: at most 100,000 characters each. Portal uploads: 5 MB, DOCX total expanded size 15 MB, no OCR. Existing combined workspace draft size cap also applies. Structured replies are bounded; connector errors omit secrets and response bodies.

## UI and failure states

Cream editorial two-column tiles and company marks adapt the supplied design; green calls to action preserve the product identity. At narrow widths Streamlit columns stack; CSS adds keyboard focus outlines. Missing or privacy-disabled catalogue logos use initials. Missing publication dates remain unknown. Empty catalogues/boards, missing CVs, absent connectors and ambiguous replies show explicit states; source outages preserve stored data. No fabricated demonstration vacancies are mixed into live results.

## Analytics / dependencies

No new runtime packages, JavaScript bundles, visitor events, fingerprinting or external analytics. Streamlit framework assets are unchanged. Catalogue logo loading is opt-in and retains an external browser-request boundary. Source refresh/import records are local operational data, not a visitor metric.

## Verification

`.venv/bin/python -m pytest tests/test_company_catalog.py tests/test_career_hub.py tests/test_career_hub_ui.py -q` covers catalogue parsing/bounds/persistence/board validation plus graph overlap, custom roles, ownership, document bounds, confirmation subsets, reply attribution, and mocked connector contracts. UI tests cover onboarding, automatic cluster loading, dedicated vacancy creation, document assessment and draft persistence. Run the whole suite before release.

New-feature verification: `.venv/bin/python -m pytest tests/test_yc_directory.py tests/test_yc_directory_ui.py tests/test_eligibility.py tests/test_eligibility_ui.py tests/test_agents.py tests/test_capital_atlas.py -q`. See [multi-agent delivery report](../../docs/MULTI_AGENT_FRAMEWORK.md).

## Known limits

Starter taxonomy and employer-board coverage are intentionally incomplete. CompaniesMarketCap exposes public companies, not careers; yc-oss is an unofficial daily mirror and its hiring flag is not a per-role guarantee. General Workday/custom career sites and automatic board discovery are not supported. Drafts are deterministic text outlines, not a model-written final résumé/letter or styled PDF/DOCX. Contacts are search strategies / advert-mentioned emails, not verified named-person recommendations. Email hypothesis does not verify source truth. Sender allowlists are not cryptographic identity verification; snippets/quoted text and literal cues can mislead. OAuth, continuous off-page sync, backfill pagination, mailbox account identity binding, revocation, authenticated public hosting, and browser submission are follow-up work. Role-page creation is not hardened for concurrent multi-user creation. Never publicly deploy this local prototype as-is.
