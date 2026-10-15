# Multi-agent team, YC explorer, work eligibility — delivery report

15 October 2026 (Europe/Zurich). Implements three requested capabilities on the
existing stack (Python 3.12, Streamlit, Pydantic, SQLite, `tau-ai`): a bounded
multi-agent framework, a YC company explorer with vclense-style filters, and a
rule-based cross-border work-eligibility checklist. No new runtime dependencies.

## Multi-agent framework (`agents.py`, `agent_tools_extended.py`, `agents_ui.py`)

Design follows the README's ReAct/τ-bench direction: narrow typed tools, with
scores, rules, and canonical state kept in application code.

- One **deterministic coordinator** (`TeamCoordinator`) routes each request to
  exactly one specialist. Routing is keyword-based, explained to the user
  (`RoutingDecision.reason`), and can be overridden manually. Specialists never
  spawn other agents.
- Three specialists, each an ordinary tau `AgentHarness` with its own tools,
  system prompt, turn limit, and tool-call budget enforced via the tau
  `before_tool_call` hook (blocked calls return a visible error result):
  - **Company scout** — `search_yc_directory` (local snapshot only),
    `refresh_yc_directory` (one fixed endpoint), `save_yc_companies_to_catalog`.
  - **Eligibility advisor** — `save_residency_profile`, `get_residency_profile`,
    `build_eligibility_checklist`.
  - **Application prep** — the existing `tools.py` domain tools.
- Every run returns an `AgentRunResult` with the final answer, turn count, and
  a full action trace (tool, arguments, ok/error, message); blocked calls are
  counted. Provider failures surface only the exception type, never details
  that could contain credentials.
- Entry points: `?view=agents` console (requires `OPENAI_API_KEY` +
  `MODEL_NAME`, explicit per-use consent, routing preview, trace display) and
  the `tau-job-application agent-team "request" [--specialist …]` CLI.

Boundaries kept: no autonomous research subagents, no messaging, no application
submission, no LinkedIn/X scraping; model context is limited to the request and
its tool results.

## YC explorer (`yc_directory.py`, `yc_directory_ui.py`)

- `YCDirectoryStore` keeps a local snapshot of the public yc-oss mirror
  (`all.json`, ~6,300 records, 24 MB fetch bound, fixed host, redirects
  rejected). Refresh is an explicit button/agent tool; filters never touch the
  network.
- `YCFilters` mirrors the ycglobe query style: `statuses`
  (Active/Acquired/Public/Inactive), `hiring_only` / `top_only` flags, batches,
  industries, regions, team-size range, text query, bounded limit.
  `filter_yc_companies` is pure and deterministic; `directory_facets` lists the
  snapshot's distinct filter values.
- The `?view=yc` view syncs the two headline filters to the URL
  (`?view=yc&status=Active&flags=hiring`), shows snapshot age, empty/error
  states, and lets the user tick companies and save them as local research
  leads into the existing company database. A directory entry — even flagged
  hiring — is never presented as an open vacancy.

## Work eligibility (`eligibility.py`, `eligibility_ui.py`)

- `ResidencyProfile` is self-declared (citizenships, residence country,
  existing work permits), validated against a known-country list with common
  aliases, and stored per career track in SQLite (`ResidencyStore`). It is
  never inferred from a CV and never sent to a feed.
- `eligibility_checklist(profile, job_country)` is a deterministic rule engine
  with four pathways: `domestic` (citizen vs resident-without-citizenship),
  `free_movement` (EU/EEA + Switzerland bloc), `existing_permit`, and
  `sponsorship` (country-specific notes for US/UK/Canada, generic otherwise).
  Each item lists documents to prepare and an official source link. Every
  result carries the "preparation aid, not legal advice" disclaimer.
- The `?view=eligibility` view edits the profile and renders the checklist.

## Company database: Global Capital Atlas (`capital_atlas.py`)

- `capital.theojaffee.net` ships its 2,429 company records ($10B+ public and
  private) inside its page JavaScript. The importer fetches only the fixed
  homepage and the referenced `/assets/page-*.js` on the same host (8 MB
  bound), tolerantly parses the embedded record array (minified JS literals,
  nested history arrays), and converts a bounded subset into `CatalogCompany`
  leads with rank, formatted valuation, ticker, country, address, industry, and
  provenance URL.
- The companies view gains a third import ("Global Capital Atlas majors") with
  the same value thresholds as the atlas ($10B+ … $1T+), and the source filter
  accepts the new `Global Capital Atlas` catalogue source. `company_catalog`'s
  fetcher now takes an explicit `max_bytes` bound instead of a hard-coded one.

## Verification

- `.venv/bin/python -m pytest -q` — 172 passed (24 new tests: directory
  parsing/filters/store, eligibility rules/store, coordinator routing/budget/
  trace/provider-failure with a scripted fake provider, atlas parser/fetcher,
  Streamlit AppTest coverage of both new views).
- `.venv/bin/python -m compileall -q src/tau_job_application` — clean.
- `git diff --check` — clean.
- Live checks: `fetch_yc_directory()` returned 6,300 records and the
  Active+hiring filter produced expected companies; the atlas parser was run
  against the real 6.2 MB page asset (2,429 records parsed).
- Not verified: real `OPENAI_API_KEY` agent runs (no credentials used in
  testing — the fake provider covers orchestration only), and the Streamlit
  server was not exercised outside AppTest.

## Known limits

- yc-oss is an unofficial daily mirror; its hiring flag is not a per-role
  vacancy guarantee. Batch names are free text from the source.
- Eligibility rules are coarse and cover common cases only; US/UK/CA notes are
  pointers, not determinations. Regulated-profession recognition is flagged,
  not resolved. Country list is finite; unknown countries are rejected rather
  than guessed.
- The atlas bundle layout can change on redeploy (parse fails honestly, never
  silently partial). Valuations are the atlas's own compiled figures.
- Keyword routing can misroute ambiguous requests; the manual override and the
  visible routing reason are the mitigation. Agents do not yet share memory
  across runs.
