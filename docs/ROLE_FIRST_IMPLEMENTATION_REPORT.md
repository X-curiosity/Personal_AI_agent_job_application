# Role-first application workspace — implementation report

15 October 2026 · Europe/Zurich

## Outcome

The existing Streamlit application now has a role-first portal inspired by the supplied cream, two-column company list. It connects multi-interest onboarding, live official vacancy clusters, per-vacancy document/evidence workspaces, networking handoffs, and the persistent application dashboard. No repository Codex.md existed at discovery; [Codex.md](../Codex.md) and [module context](../src/tau_job_application/codex.md) now preserve the implementation context.

## Request coverage

| Requested capability | Delivered | Boundary / remaining work |
|---|---|---|
| Screenshot-inspired UI | Cream background, strong company/role typography, logo/initial marks, two-column lists, thin dividers, green controls | It adapts the layout, not the screenshot's investment facts or company claims. |
| Multi-field onboarding | Engineering, finance, marketing, business, science/research, design and other; multiple subfields and role choices; custom role entry | Starter taxonomy, not every occupation. No degree exclusion. |
| Cross-disciplinary roles | ML engineering appears under electrical engineering, software, CS/AI, neuroscience and economics/statistics | Associations are navigation suggestions, not assertions of eligibility. |
| Role → current vacancies | First-open official-feed refresh and persisted clusters; explicit refresh, company/location filters, source publication-date sorting and pagination | Figma, Mistral AI, Cloudflare and OpenAI only. Finance and other sectors need broader source coverage. Availability is an observation, not a guarantee. |
| CV and motivation intake | Per-vacancy upload/paste, editable text, local persistence | Selectable-text PDF/DOCX/TXT/MD; no OCR. Raw uploaded files are not retained. |
| Tailor missing documents | Reviewable CV targeting outline preserving original text, and role/company-specific motivation template, downloadable as text | Requires factual background. Deliberately not a fabricated CV, polished LLM output, or final PDF/DOCX document. |
| CV + project scoring | Confirmed CV requirement coverage, completed-project coverage and existing combined evidence match | Heuristic coverage, not ATS validation or hiring probability; letter style adds no points. |
| Relevant LinkedIn contacts | Role-specific people-search links and emails explicitly present in the advert | Verified named-person discovery is not implemented; no LinkedIn scraping. |
| Infer email if possible | Explicit name/domain/observed-pattern/public-source input; labelled unverified output | No verification, probing, storage of generated hypothesis, or sending. Non-ASCII naming patterns can be inaccurate. |
| Internal application dashboard | Dedicated saved application, existing stages, deadlines, notes, history and export; links back to documents/contacts/replies | Opening a form is not recorded as an application. Candidate confirms submission. |
| Gmail / Slack integration | Read-only official API adapters, bound conversation/sender, consent, server-token configuration, optional 60-second polling while page is open | No credentials supplied or real accounts read in development. No one-click OAuth, token refresh, push notifications or off-page worker. |
| Automatic reply status | Optional clear Gmail outcome progression, replay protection and audit history; manual confirmation for other proposals | Exact binding required. Old/ambiguous/Slack replies need review. Sender match is not identity verification. Literal snippets can misclassify; production auto-mode needs further validation. |
| Computer-use application | Official form handoff, reviewed documents, explicit submitted confirmation | Browser autofill/submission runner is **not implemented**. This is not an autonomous application agent. |

## Architecture and why these choices

### Keep Streamlit + SQLite rather than rewrite to a SPA

The repository already had scoped workspaces, projects, source feeds and tracker history. Reusing them avoids a second database and competing application states. The new portal adds routes and small modules, not a second frontend toolchain or new runtime packages. A future authenticated, multi-user service is a separate migration; the current local app must not be exposed publicly.

### A many-to-many interest graph rather than a degree tree

The same role is listed under several subfields. Education does not prune role choices. Users can bypass catalogue gaps with a custom role. This keeps navigation transparent and editable; it is not a model pretending to know every career path.

### Official public feeds rather than scraped LinkedIn results

The portal reuses the bounded source adapters and adds OpenAI's publicly linked Ashby board. Failed refreshes retain the last successful board. Missing publication dates are not replaced with retrieval dates, and missing jobs are not automatically called closed. A wider licensed job source is still needed for good finance/marketing coverage.

OpenAI's [official careers page](https://openai.com/careers/search/) links to [its Ashby application board](https://jobs.ashbyhq.com/openai/6d545b2c-5697-4f38-affc-aaa309f5bb26/application). Source mechanics follow the existing adapters and [Greenhouse's public Job Board API](https://docs.greenhouse.io/job-board).

### Evidence coverage rather than a black-box “chance of getting hired”

The candidate explicitly selects parsed skills they can substantiate. This selection is validated as a subset of the supplied CV before matching/tailoring; the original CV remains intact. Completed project evidence uses the existing contribution/proof/outcome checks. Proposed projects never count as completed work. The existing score limitations and English-first parsing still apply.

### Local, factual drafts rather than unrestricted generation

The draft builder adds role targeting and preserves the supplied CV verbatim. The letter includes visible places for personal motivation and a concrete example. This works without a paid model or external CV transfer. It is less polished than evidence-grounded model drafting, but avoids claiming that a finished bespoke résumé generator has been shipped. A model-assisted editor can later use approved evidence and final-claim review.

### Exact reply binding rather than whole-inbox keyword guessing

Each application binds one Gmail thread or Slack conversation plus an exact expected sender. The first sync can show old replies for review, but cannot replay them as new automatic outcomes. Automatic progression is opt-in, future-only, Gmail-only and non-regressive. Duplicate message IDs have a database uniqueness constraint. Offers are recorded as offers, never accepted. Unrecognised or conflicting phrases do not change status.

The read-only Gmail adapter uses [`users.threads.get`](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.threads/get), metadata and snippets rather than attachments/full bodies. Slack uses [`conversations.history`](https://docs.slack.dev/reference/methods/conversations.history/) with fifteen messages and at most one polling call per minute while enabled. Truncated snippets, quoted correspondence, spoofed sender headers and unsupported languages remain real classifier risks. Start in review mode.

### Manual final submission rather than generic computer-use automation

Employer forms vary, can contain legal declarations, and may prohibit automation. A safe runner needs per-site permission/contract checks, explicit reviewed fields, secure attachments, screenshot evidence, duplicate-submission protection and a final confirmation boundary. None of that is hidden behind a fake “auto apply” button. The current Apply tab opens the official source and records submission only after the candidate confirms it.

## Connection setup

1. Enable the Gmail API in a Google Cloud project and provision an OAuth token externally with `gmail.readonly` (or metadata access if suitable for your deployment). Export `GMAIL_ACCESS_TOKEN` in the server environment. There is no built-in authorization-code or refresh-token flow yet.
2. For Slack, provision a bot with only the appropriate history scope for the selected conversation and ensure it can access that conversation. Export `SLACK_BOT_TOKEN`. Public/private channels and DMs require different scopes; do not grant all scopes by default.
3. Restart the app after setting environment variables. Do not put credentials in URLs, chat, source files or SQLite. `.env.example` is documentation; `.env` is not automatically loaded.
4. Open an application's **Replies & status** tab. Bind its API conversation ID and exact recruiter email / Slack member ID. The Gmail API thread ID is not necessarily the same representation shown in the Gmail web address.
5. Save the binding, then grant read consent. Use **Check for replies** first. Leave automatic updates off until you have checked attribution and classifier behaviour. Enable page-open polling separately if wanted.
6. Revoke access at the provider and remove the environment token to disconnect. There is no product-level account revocation UI yet. No Gmail/Slack messages are sent or modified by these adapters.

## Security, privacy and operations

Private inputs remain in the local SQLite database. New SQL is parameterized, and track/thread ownership is checked server-side. User/company/ad text in custom HTML is escaped. Portal files are capped at 5 MB with a 15 MB DOCX expansion check and 100,000 extracted characters; existing draft caps remain in force. Connector HTTP requests have fixed official hosts, no redirects, a 15-second timeout and a 2 MB cap; credentials are authorization headers and connector errors do not echo response bodies.

No visitor analytics, fingerprinting or additional browser script was added. Existing local source-refresh events are operational logs, not visitor counts. Logo URLs still cause browser requests to their image providers. The skill's privacy guidance favoured no additional measurement because none was requested.

There is no public deployment in this change. HTTPS, production security headers, authentication, account isolation, encrypted credential storage, retention policy, rate-limit coordination and service monitoring remain deployment gates. Back up the local SQLite file with the app stopped, protect it as personal data, and test restoration before destructive changes. Deleting a workspace/application cascades its associated new records; there is no trash/undo UI.

## Verification and remaining gaps

- `.venv/bin/python -m pytest -q --tb=short`: **135 passed**. `.venv/bin/python -m compileall -q src/tau_job_application` and `git diff --check`: passed.
- New tests use synthetic data and mocked providers; no real CV, credential or mailbox message is committed.
- Checked live onboarding and Hardware Engineer cluster in the local browser. The official-feed refresh returned 23 related observations on 15 October 2026; this is a transient local check, not a promised inventory.
- Real Gmail/Slack access, OAuth consent, token refresh, final employer form submission and production security controls have **not** been verified.
- No dependency was added. No standalone dependency-vulnerability or full repository security audit was run; the checks here do not certify security.
- Browser payload/latency benchmarks are not established. New tiles are paginated at twelve, connector reads bounded, polling optional, and the framework bundle unchanged.

Recommended next delivery: wider official/licensed role sources and secure OAuth first; then validated reply attribution/classification; then source-backed named contacts and a carefully supervised browser application adapter.

### Inspection / handoff record

Inspected the README, package manifest, source registry/adapters, UI routing, workspace persistence/sidebar, tracker/store, candidate parsing, analysis pipeline, evidence/project contracts, branding and environment example. No repository-local AGENTS.md, Codex.md, security policy, contribution guide or hosting configuration was found by the scoped inventory. Existing unrelated/uncommitted landing, branding and tracker work was preserved. No dependency installation, commit, push or deployment was performed. Re-run the whole suite after changing scoring or persistence contracts; restart the Streamlit process after changing imported modules.
