# Co-Apply GPT — Job Readiness and Learning Assistant

**Goal: help applicants become stronger candidates, not just produce better-looking applications.**

The product organizes a broad career direction into related target jobs, connecting their requirements to knowledge, projects, evidence, and interview practice. It does not restrict applicants to one exact job title. Its initial audience is students and early-career applicants targeting Europe.

**Status: local prototype, not a production hiring platform or validated tutor.** The current full application remains local-only. A separate, incomplete hosted MVP scaffold is documented in [docs/HOSTED_MVP.md](docs/HOSTED_MVP.md); it is not deployed and does not yet migrate local workspaces. The current application implements a deterministic assessment workflow, a Streamlit interface, source connectors, and optional model access. Several important capabilities remain templates or heuristics. The research-based learning system below is a proposed next stage, not a description of features already shipped.

**15 October 2026 — role-first portal:** start at `?view=career` or **Find my roles**. Multi-interest onboarding leads to role clusters and per-vacancy CV/letter, project-evidence, contact-search and reply-review workspaces. The portal adds OpenAI's official Ashby board to the existing sources. Gmail/Slack readers require external token setup; there is no one-click account login or autonomous application submission. See [implementation report and decisions](docs/ROLE_FIRST_IMPLEMENTATION_REPORT.md), [Codex context](Codex.md), and [module context](src/tau_job_application/codex.md).

## Contents

- [1. Run locally](#1-run-locally)
- [2. What works today](#2-what-works-today)
- [3. How to use the interface](#3-how-to-use-the-interface)
- [4. Scores, evidence, and known limitations](#4-scores-evidence-and-known-limitations)
- [5. Architecture and data flow](#5-architecture-and-data-flow)
- [6. Job sources and European coverage](#6-job-sources-and-european-coverage)
- [7. Privacy and review boundaries](#7-privacy-and-review-boundaries)
- [8. Proposed learning system](#8-proposed-learning-system)
- [9. Research papers and implementation ideas](#9-research-papers-and-implementation-ideas)
- [10. Experiments and evaluation](#10-experiments-and-evaluation)
- [11. Implementation roadmap](#11-implementation-roadmap)
- [12. Testing and troubleshooting](#12-testing-and-troubleshooting)

## 1. Run locally

### What you need

| Requirement | Check with | Install |
|---|---|---|
| Python 3.12 or newer | `python3 --version` | uv installs a managed one automatically (below) |
| [uv](https://docs.astral.sh/uv/) | `uv --version` | `curl -LsSf https://astral.sh/uv/install.sh \| sh` (macOS/Linux) or `brew install uv` |
| A browser | — | any modern browser |

No API key is needed for the core app: CV analysis, role pages, the company browser, work-eligibility checklists, and interview practice all work offline-deterministically. Model credentials only unlock the optional agent team and AI coach.

### Install once

```bash
git clone https://github.com/X-curiosity/Personal_AI_agent_job_application.git
cd Personal_AI_agent_job_application

# Regular install avoids an editable-install pointer issue seen on macOS.
# If your shell has an old conda/pyenv active (e.g. Python 3.9), deactivate it
# first or pin the interpreter:
uv sync --python 3.12 --no-editable --reinstall-package tau-job-application
```

> **`Package 'tau-job-application' requires a different Python: 3.9.x not in '>=3.12'`?**
> Your terminal activated an old environment (conda `(base)` is the usual suspect). Run `conda deactivate`, then repeat the command above — or permanently stop auto-activation with `conda config --set auto_activate_base false`.

### Run it (every time)

The easiest way — one script, opens the browser for you:

```bash
./run.sh
```

or double-click **`Start Co-Apply GPT.command`** in Finder (macOS). The script always uses the project's own Python 3.12 environment, restarts any previous instance, and opens http://127.0.0.1:8506. Press `Ctrl+C` in the terminal to stop.

Manual alternative:

```bash
uv run --no-sync tau-job-application ui
# or directly:
.venv/bin/python -m streamlit run src/tau_job_application/ui.py --server.port 8506
```

### Where things are in the app

| Screen | How to open |
|---|---|
| Product home | `?view=landing` (sidebar: Product home) |
| Role pages (listings + company browser) | sidebar: Find my roles → pick a role; the Startups / Big companies browser is at the bottom of each role page |
| Company database | sidebar: Company database |
| Work eligibility checklists | top bar: Eligibility |
| Connected accounts (GitHub, LinkedIn, Gmail) | top bar: Accounts |
| Agent team (optional, needs credentials) | sidebar: Agent team |
| Application dashboard | sidebar: My applications |

First use of the company browser: click **Refresh startups** / **Refresh big companies** once on a role page to load the local snapshots; filters are instant afterwards. Remote company logos stay off until you tick **Load remote company logos**.

### Optional credentials and network access

| Setting | Purpose | Required for basic analysis? |
|---|---|---|
| `OPENAI_API_KEY` | Optional Tau provider and explicitly requested audio transcription | No |
| `MODEL_NAME` | Model used by the optional Tau CLI command, agent team, and read-only UI coach | No |
| `LINKEDIN_CLIENT_ID` / `LINKEDIN_CLIENT_SECRET` / `LINKEDIN_REDIRECT_URI` | Your own registered LinkedIn app, for the official OpenID Connect sign-in on the Accounts screen | No |
| `X_BEARER_TOKEN` | Official X recent-post search, subject to account access and limits | No |
| `JEV_API_KEY` / `JEV_API_URL` | Optional Jev decision model, used only to settle **ambiguous** skill pairs behind an opt-in checkbox on Overview. Only the two skill labels are sent; canonical scores never depend on it. See [Jev notes](docs/JEV_NOTES.md) | No |
| SmartRecruiters token | Entered in the UI for the current connector | No |

```bash
export OPENAI_API_KEY="your-key"
export MODEL_NAME="a-model-supported-by-your-provider"
./run.sh   # the agent team view is now enabled

# or one-shot from the terminal:
uv run --no-sync tau-job-application agent fixtures/candidate.txt fixtures/job.txt
uv run --no-sync tau-job-application agent-team "Do I need a visa to apply in Canada?"
```

`.env.example` documents configuration; the application does **not** automatically load a `.env` file. Export variables in the shell that launches the app. Never commit real credentials. External API access may require approval, an eligible plan, or payment.

### After changing code or pulling updates

A regular install does not pick up source edits automatically. Repeat once, then restart the server (a browser refresh is not enough):

```bash
uv sync --no-editable --reinstall-package tau-job-application
./run.sh
```

Run from the repository directory: the demo expects `fixtures/`, and the app keeps its local data in `.job_assistant/` (git-ignored, never uploaded).

### Verify the install

```bash
uv run --no-sync tau-job-application demo    # deterministic demo report
uv run --no-sync pytest -q                   # full test suite
```

### Troubleshooting

| Symptom | Fix |
|---|---|
| `requires a different Python: 3.9.x` | Old conda/pyenv active → `conda deactivate`, reinstall with `--python 3.12` |
| `ModuleNotFoundError: tau_job_application` in the browser | Broken editable pointer → rerun the `uv sync --no-editable …` install |
| Port already in use | `./run.sh` stops the old instance automatically; or `lsof -ti :8506 \| xargs kill` |
| Browser shows a stale UI after code changes | Reinstall (above) **and** restart Streamlit, then hard-refresh (`Cmd+Shift+R`) |
| Nothing fetched in company browser | Expected: snapshots load only on the explicit Refresh buttons |

| Setting | Purpose | Required for basic analysis? |
|---|---|---|
| `OPENAI_API_KEY` | Optional Tau provider and explicitly requested audio transcription | No |
| `MODEL_NAME` | Model used by the optional Tau CLI command and read-only UI coach | No |
| `LINKEDIN_CLIENT_ID` / `LINKEDIN_CLIENT_SECRET` / `LINKEDIN_REDIRECT_URI` | Your own registered LinkedIn app, for the official OpenID Connect sign-in on the Accounts screen | No |
| `X_BEARER_TOKEN` | Official X recent-post search, subject to account access and limits | No |
| SmartRecruiters token | Entered in the UI for the current connector | No |
| `JEV_API_KEY` | Optional Jev decision model for ambiguous skill pairs; see [docs/JEV_NOTES.md](docs/JEV_NOTES.md) | No |

```bash
export OPENAI_API_KEY="your-key"
export MODEL_NAME="a-model-supported-by-your-provider"
uv run --no-sync tau-job-application agent fixtures/candidate.txt fixtures/job.txt
```

`.env.example` documents configuration; the application does **not** automatically load a `.env` file. Export variables in the shell that launches the app. Never commit real credentials. External API access may require approval, an eligible plan, or payment.

## Public Hired explorer

`vercel-site/` is a separate static **Jobs / Map** preview. It contains no accounts, CV uploads, personal workspace data, or automatic applications. `PYTHONPATH=src .venv/bin/python scripts/export_public_jobs.py` refreshes its bounded European vacancy snapshot from the reviewed public Greenhouse/Ashby employer boards. Each pin is a vacancy's stated city or country estimate, never a headquarters substitute. `.github/workflows/refresh-jobs.yml` defines a daily 06:00 UTC refresh on `main`; it becomes active only after the workflow is committed/pushed and Actions are enabled. The public site still serves a saved snapshot rather than a live feed; verify roles on their official adverts. Browser-typed skill overlap stays in the page, and LinkedIn links are searches rather than scraped or verified people recommendations.

### Local reviewed rule-based auto-apply

After `uv sync` and `.venv/bin/playwright install chromium`, run `uv run --no-sync tau-job-application auto-apply path/to/cv.pdf https://employer.example/job --application-id my-application-1 --full-name "Your Name" --email you@example.com`. No LLM, provider key, model charge, or screenshot sharing is used. The local app exposes the same runner under Accounts → Open local auto-apply. Deterministic rules fill recognized fields, attach the exact CV, and stop for CAPTCHA, consent, restrictions, ambiguous labels, or unknown required questions. Every application requires the displayed one-time `SUBMIT …` confirmation. URL-encoded, verified multipart CV, and explicitly enabled JSON submissions are supported; ambiguous forms fail closed. It is not a hosted/unattended bot and cannot guarantee compatibility with every employer form.

## Hosted MVP status

A separate hosted entrypoint and Supabase schema are being prepared for a focused multi-user preview. The hosted scope is account sign-in, private CV files, private company targets, and a reviewable application queue; it is not the full local app and does not automatically submit applications. See [Hosted MVP setup and limitations](docs/HOSTED_MVP.md). No hosted account service is live yet.

## 2. What works today

| Area | Implemented behavior | Important boundary |
|---|---|---|
| CV intake | TXT, Markdown, selectable-text PDF, and DOCX extraction | No OCR; ordinary CV extraction uses a small English-oriented skill vocabulary |
| CV link inference | Recognizes GitHub, LinkedIn, X/Twitter, and one likely portfolio URL from CV text; shows them for verification | A detected URL is not proof of ownership or relevance; explicit UI edits override inferred values |
| Profile links | GitHub, portfolio, LinkedIn, and X fields | Portfolio/social links alone do not retrieve or validate a person's work |
| GitHub enrichment | Optional public API lookup of profile/repository language signals | No repository code review; languages are unconfirmed signals, not proof of proficiency |
| Job intake | Natural-language descriptions, one explicitly submitted public HTTPS job URL, server-rendered/JSON-LD extraction, contextual skill/capability extraction, requirement review, company-board connectors, CSV/JSON imports | No crawling; JavaScript-only/authenticated pages may fail; English-first skill heuristics need review |
| Role market | User-triggered refresh of registered Greenhouse, Lever, and Ashby public employer feeds; compact source-truthful role cards, editable role-family aliases, deterministic local CV-skill overlap ranking, local saved/tracking/hidden shortlist states, source provenance, a listing-location map, and managed company marks | A reviewed employer-board registry, not a web-wide job search, hiring prediction, eligibility check, automatic application, automatic outreach, or alert service. Company marks are a small named visual catalog, a candidate-managed public HTTPS image, or initials—not automatic company enrichment. |
| Company database | Manual, capped imports from CompaniesMarketCap and the yc-oss hiring-company dataset; local filters, source links, opt-in logo loading, and reviewed employer-board registration | Directory membership is not a vacancy. The app does not crawl arbitrary company sites; jobs appear only after a Greenhouse, Lever, or Ashby public board is verified. YC data is a community mirror, not an official YC API. |
| Product home | Separate dynamic landing route with a local snapshot of job workspaces, the newest role market, shortlist choices, and a small opening preview | It never refreshes a feed, uploads profile data, applies, or contacts anyone; counters are saved local observations and availability must be verified on the official listing. |
| My applications | Saved roles across the selected career track, editable stages, deadlines, next steps, notes, retained adverts, history and JSON export; per-vacancy document/reply workspace | User-confirmed progress by default; optional bound Gmail replies can record clear future outcomes after setup/consent. Opening an employer page never marks a role Applied; missing feed results never mark it Expired. |
| Extraction memory | Saved per-description corrections and explicitly approved phrase-to-skill mappings | Local Quick start memory, not LLM fine-tuning; repetition alone never confirms a mapping |
| Role comparison | Deterministic required/preferred skill coverage | Not a probability of being hired; no comprehensive European eligibility filtering |
| Evidence match | A transparent role-and-project evidence view: confirmed CV coverage plus user-confirmed completed projects with a proof reference and observable outcome/test | Not a prediction of an interview, offer, or hiring outcome; never derives a score from employee profiles, historic hires, LinkedIn, or unconfirmed GitHub language signals |
| CV readiness | Heuristic structure/contact/outcome checks plus role coverage | Not a validated ATS score or assessment of intelligence/ability |
| CV tailoring | Summary, relevant skill ordering, and section-editing advice | **Not a complete rewritten résumé or PDF/DOCX export** |
| Authenticity review | Generic-phrase and claim/outcome heuristics | Cannot establish authorship or factual truth; known false-acceptance cases exist |
| Learning plan | Missing-skill list, selected prerequisites, small static resource catalog | Not yet an adaptive knowledge model or interactive dependency graph |
| Standout project plan | One focused proof project and, only when useful, one sequenced integration project for unmet, evidence-backed role gaps, with milestones, deliverables, and acceptance checks | No live project research or company-specific project design; proposed work is never counted as completed evidence |
| Job monitoring | User-triggered refreshes of individual permitted boards, local snapshots, and newly observed fingerprints | No scheduled alerts, reliable closure detection, or cross-source deduplication |
| LinkedIn handoff | Opens role searches or role-specific people-search suggestions on LinkedIn | No automated listing/profile retrieval, verified named-person recommendations, scraping or outreach |
| Interview practice | Role-specific questions, typed responses, keyword-based feedback, and a saved practice history inside each Job Workspace | Measures answer structure heuristically, not technical correctness |
| Voice input | Recording plus explicitly requested OpenAI transcription | Audio leaves the machine when transcription is requested |
| Career tracks | Optional folders containing multiple Job Workspaces, skill overlap, and merged learning priorities | Manual organization; not automatic role clustering or a complete semantic job search |
| Profile company explorer | A small curated world map, locally ranked from skills detected in the selected CV, regional overview filters, and a company drill-down with selected source-linked HQ/research/engineering hubs and their public focus | Not a live vacancy feed, hiring prediction, eligibility check, complete office directory, or assertion that every pin is a headquarters |
| Coach | Separate persistent chat history per Job Workspace; local report guide or optional read-only AI coach | Local mode is templated; AI mode needs credentials and explicit context-sharing consent |
| Optional agent | Bounded Tau CLI harness with domain tools; one-turn, tool-free UI coaching | Quick start scoring remains deterministic; no autonomous research subagents |
| Persistence | Shared profile, job-workspace inputs, analysis/CV guidance, chats, interview practice, application progress and history, plus legacy snapshots, audit events, and source-watch records in SQLite | The full application remains local; the separate hosted MVP scaffold is not deployed and has not migrated these records |

The [Jobright comparison](docs/JOBRIGHT_IMPROVEMENT_REPORT.md) contains the detailed code review and product backlog. It distinguishes Jobright's advertised features from independently verified behavior; marketing performance claims are not benchmarks for this project. The [Whali-inspired Role-market direction](docs/WHALI_INSPIRED_PRODUCT_DIRECTION.md) separately records which job-board interaction patterns fit this product and which outreach-automation patterns are intentionally excluded. The [Jev notes](docs/JEV_NOTES.md) document the implemented decision-model skill matching: a deterministic local model (always on, advisory) plus an optional Jev escalation for ambiguous skill pairs, with the canonical evidence score left untouched. The [StartupMap reverse-engineering notes](docs/STARTUPMAP_RE_NOTES.md) record how startupmap.one's seeker join flow works (REA evidence included) and how the **Match me · 5 answers** guided flow adapts it: role areas, experience, work style and location, company stage (early/growth/scale-up/big — generalized beyond startups), and industries, with a live, deterministic count of hiring companies that fit. The Companies view also has the map adaptation: an offline-geocoded hiring-company map (city-exact pins, country-level soft discs, stage colours, Match me filter) that covers 97.6% of local hiring candidates without ever guessing a coordinate.

## 3. How to use the interface

### Role-first portal

1. Open **Find my roles** or `?view=career`. Select multiple fields and subfields, choose suggested roles, or enter custom titles. Cross-disciplinary roles appear in several branches; education is not an eligibility gate.
2. Open a role page. Its first cluster loads from official public feeds; **Refresh positions** checks again. Company/location filters, source publication dates and pagination keep the two-column list manageable. Current portal coverage is Figma, Mistral AI, Cloudflare and OpenAI—not a comprehensive job index. Finance and other sectors need additional sources.
3. Open a vacancy's **application workspace**. This saves it at **Saved**, not Applied. Upload or paste a CV/background and motivation letter, review extracted skills and select **Save documents & assess fit**. Review CV coverage and completed-project coverage separately.
4. Add real project proof under **Project evidence**. Generate reviewable text CV/letter drafts when useful; placeholders need your edits. Missing background is never fabricated. The letter does not earn fit-score points.
5. **People to contact** offers LinkedIn search strategies and emails explicitly mentioned in the advert. Optional pattern-based email output is marked unverified; it is not a verified contact, stored hypothesis or send action.
6. **Replies & status** supports read-only Gmail/Slack adapters after external token setup, conversation/sender binding and read consent. Manual checks and optional page-open 60-second polling are available. Gmail auto-progression is separately opt-in; ambiguous/old/Slack replies remain review items. Provider credentials, limitations and setup are in the [report](docs/ROLE_FIRST_IMPLEMENTATION_REPORT.md#connection-setup).
7. Use **Apply** to open the official form and confirm a real submission. A separate local rule-based runner can fill supported forms, but only with explicit final approval. **Application dashboard** retains the application's history and links back to its documents and replies.
8. Open **Company database** to import a bounded public-company or hiring-YC set. Review source records, then connect a company's public Greenhouse, Lever, or Ashby identifier. Verified boards automatically join later role-page refreshes.

The original workspace tabs remain available for existing workflows. With no saved interests, the base route also places onboarding above them.

### Career tracks and Job Workspaces

Use the **sidebar** to select a Career track and a Job Workspace. A Job Workspace is the main unit: one target role/company gets its own evidence, CV guidance, projects, interview practice, and coaching history. Career tracks are optional folders for comparing related jobs. The first launch creates a neutral **My applications** track, not a demo career path. You can add tracks and rename, move, or delete individual Job Workspaces. **Move workspace (keep its history)** lets you regroup jobs later without losing their drafts, plans, conversations, or rehearsal history.

```text
Product design
├── Product Designer — company A
└── UX Designer — company B

Data platforms
├── Data Engineer — company C
└── Analytics Engineer — company D
```

These are organizational examples, not title-matching rules. A Career track can include several related titles, and a shared skill does not make two roles equivalent. Choosing a track does not automatically search every related job title or transfer a CV claim between jobs.

**Nine contextual windows:** Overview, Job brief, CV studio, Evidence match, Proof projects, Interview lab, Career track, Role market, and Coach.

- **Each Job Workspace owns:** editable CV/job input snapshots, its latest analysis and CV guidance, candidate-confirmed completed-project evidence, a role-specific project plan, a conversation history, and scored interview rehearsals. Text inputs auto-save locally across reruns and switching; analyses, conversations, rehearsal history, and project evidence survive restarting the app.
- **Overview:** shows requirement evidence coverage (not a hiring prediction), the next best move, proof gaps, a short role-specific preparation route, and an Evidence match card when there is completed project proof.
- **Shared profile:** select **Save as shared profile for new workspaces** to reuse a CV and links. Existing workspaces retain their own input snapshots; **Use latest shared profile in this workspace** explicitly updates one. Old results are not silently recomputed.
- **Career track:** compares current analyzed jobs by extracted skills and responsibilities rather than exact titles, shows shared/unique requirements, and merges gap-driven learning priorities. Missing required coverage across multiple jobs is prioritized over a gap unique to one optional requirement. You do not need every skill from every job.
- **Across tracks:** the overview can show overlapping extracted requirements, without merging conversations or implying identical roles. Learning completion/proficiency tracking is still future work.
- **Changed inputs:** old snapshots remain stored but become stale; they are excluded from comparisons and coaching until **Refresh this job workspace** is run again. Saved requirement corrections also invalidate snapshots using that exact job text.
- **Deletion:** deleting a workspace removes its inputs, latest result, completed-project evidence, chat, and interview rehearsal history. It does not delete the separate shared profile, approved extraction memory, or legacy analysis records.

The local database is `.job_assistant/assistant.sqlite`. Workspace/profile tables include `career_workspaces`, `career_threads`, `career_messages`, `career_interview_attempts`, `career_shared_profile`, and `career_project_evidence`. Discovery uses `role_discovery_runs`, `role_discovery_results`, `role_market_states`, and `company_brand_assets`; source-aware company intake uses `company_catalog`, `company_catalog_imports`, and `company_job_boards`; application tracking uses `tracked_applications`, `application_events`, and `application_shortlist_imports`. Pre-workspace entries in the legacy `analyses` table are preserved but not automatically assigned to a Career track.

### Track your applications

Select **Save for review** on a role card to keep it in **My applications**, accessible from the sidebar or the Role market. **Start tracking** opens this page. It collects applications across the job workspaces in the selected career track; change the career track in the sidebar to switch the collection. Existing Saved/Tracking shortlist entries carry over once as Saved.

- The stages are **Saved, Preparing, Applied, Contacted, Interview, Offer, and Closed**. Use **I applied** after submitting on the employer's website, or edit the status under **Update progress & notes**. Each save records your changes in the application's history.
- Add an application deadline, next action and date, application date, and notes. **Your next seven days** surfaces overdue actions and upcoming deadlines first; **Closing soon** and **Next action** sorting show the full queue. Deadlines are currently entered by you, not extracted automatically from adverts; date cues use Europe/Zurich.
- Click a stage in the pipeline to filter its applications, or enable **Needs attention in the next seven days** to focus on due actions and upcoming deadlines. The interface uses green and white; overdue next steps also have a red **Overdue action** label, so urgency is not communicated by colour alone.
- Choose **Closed** with Rejected, Withdrawn, or another reason to archive an application. Select **Closed** or **All stages** to revisit it. You can reopen it by changing its stage.
- Mark a listing Open or Expired after checking it yourself. Its original advert and progress remain available. Disappearance from a refresh is not treated as proof of expiry.
- **Prepare this role** opens or creates its preparation workspace using the official listing URL. It does not change the application stage. Hiding a role or removing its feed status also keeps the application record.
- **History & saved advert** retains the source snapshot and change history. **Export your application history** downloads the selected career track as JSON. Removing an application removes its history; deleting its owning job workspace also deletes the associated application records. A removed record is not recreated by shortlist migration, but you can explicitly save the role again.

This flow adapts application-management patterns described in [Whali's job-board documentation](https://whali.com/docs/job-board). The new vacancy workspace adds optional, bound Gmail outcome updates; sending emails, calendar events, off-page scheduled reminders and automatic listing-expiry detection remain unimplemented.

### Build a Job Workspace

1. Select a Career track and a Job Workspace in the sidebar.
2. Drag in a CV or paste text. New uploads populate the editable CV text field; analysis and the profile company explorer use the text shown there.
3. Add your GitHub profile and/or portfolio when available. The UI also detects recognizable GitHub, LinkedIn, X/Twitter, and portfolio URLs in the CV; verify or edit them before they are used in the profile. Links are optional and never treated as proof of ownership or competence.
4. Paste a target job URL and select **Read job URL**. The app fetches only that explicit public HTTPS URL, follows only public HTTPS redirects, reads server-rendered text and Schema.org `JobPosting` JSON-LD, and populates title, company, description, and source URL. You can edit the extracted fields before analysis. If the page is blocked, JavaScript-only, authenticated, too large, unsafe, or lacks inferable requirements, paste the description manually.
5. Alternatively paste a job description directly. Title/company can be entered separately.
6. Requirement review is optional and collapsed by default. Open it to inspect inferred capability phrases, source quotes, required/preferred/uncertain labels, and heuristic confidence; leave feedback or save corrections only if you want to help improve extraction.
7. Select **Analyze this job**. The Overview becomes the role-specific preparation home.
8. Act in the contextual windows:
   - **CV studio:** evidence-aware, copy-ready CV guidance and a claim-safety review.
   - **Evidence match:** an evidence-only score for this role. Add completed work you can substantiate with your contribution, skills, a non-confidential proof reference, and an observable outcome/test. It retains CV coverage separately, and never treats a missing or unrelated project as a zero.
   - **Proof projects:** separates your finished evidence from one or two gap-driven standout projects. The first makes the highest-priority unmet skill visible; an optional second integrates the first few remaining gaps into a stronger portfolio case. When eligible completed project proof already covers the gap, the suggestion disappears rather than creating redundant work. A proposed project does not earn Evidence match credit until it is actually complete and you explicitly add its proof.
   - **Interview lab:** role-specific questions, structured feedback, and saved rehearsal history.
   - **Role market:** a role-first opportunity board built only when you choose to refresh registered Greenhouse or Ashby public feeds. It offers editable title aliases, local CV-skill ranking, source-aware filters, listing-location pins, a separate company-research view, and lawful manual-source options. Cards use a small named visual catalog where available and initials elsewhere. Open **Manage company marks** to replace a mark with a public HTTPS image you are allowed to use, force initials, or remove a local override. The browser loads those images directly; the app does not scrape company sites or fetch logo files server-side.
   - **Product home:** select **Product home** in the sidebar, or open `?view=landing`, for a separate dynamic view of your latest local role market. It is a summary and entry point; use **See live role markets** to return with that view placed first.
   - **Coach:** job-scoped local guidance or optional consented AI coaching.
9. Download the Markdown planning report if desired. The current UI blocks this download when the heuristic authenticity status is `blocked`; this is a prototype behavior, not a reliable factual-verification gate.

A simple synthetic input for testing:

```text
Name: Alex Example
Headline: Junior backend developer
Skills: Python, SQL
Experience: Built a Python service with automated tests.
```

```text
Title: Backend Engineer
Company: Example Systems
Required skills: Python, Docker
Preferred skills: SQL
```

Inspect candidate skills yourself: there is not yet a candidate-profile confirmation editor. Job requirements now have the review editor below. Updating input fields does not automatically recompute an existing result: select **Refresh this job workspace** again.

### Natural-language requirement extraction and learning

You do **not** need `Skills:` or `Required skills:` fields in a job description. For example:

```text
You are experienced with Python and SQL.
You are comfortable building APIs.
Projects involving Docker are a plus.
You have worked with ClickHouse.
No experience with Kubernetes required.
```

The extractor proposes Python, SQL, API development, Docker (preferred), and ClickHouse (a new phrase needing review). It excludes the negated Kubernetes requirement. It also considers headings such as `Requirements`, `Responsibilities`, and `Nice to have`, and phrases such as `familiar with`, `knowledge of`, `background in`, and `proficient in`.

- **Source grounding:** each suggestion includes the exact source clause, character location, extraction method, and a heuristic confidence value. These values are not calibrated probabilities.
- **Feedback:** the optional rating/comment is stored locally against the job-description hash. It is product feedback, not silent model training; only explicitly reviewed phrase mappings can affect future extraction.
- **Capabilities rather than invented tools:** “building APIs” can suggest API development; “relational databases” does not prove the employer specifically requires PostgreSQL.
- **Importance:** required/preferred status comes from the local clause and section. Standalone stack mentions can remain `uncertain`; uncertain requirements are excluded from scored coverage and missing-skill project plans.
- **Unknown vocabulary:** short phrases after experience/project cues are proposed even when the term is outside the built-in skill list. They remain reviewable; this is not a guarantee that every phrase is a useful skill.
- **Compatibility:** explicit required/preferred lists still work and are combined with prose rather than replacing it.

Under the target job, open **Review inferred requirements / leave parsing feedback (optional)**:

1. Edit skill names and required/preferred/uncertain labels, remove false positives, or add a missed requirement with a quote copied exactly from the job.
2. Confirm your review and select **Save corrections for this description**. Select **Refresh this job workspace** to recalculate the assessment. Exact copies of this description reuse the saved correction; changed descriptions are parsed afresh.
3. To generalize a correction, enter a short source phrase and its reviewed skill label, opt into reuse, and select **Remember mapping**. For example, review “event-driven services” as “Event-driven architecture” and remember that mapping.
4. On a future job, that phrase maps to the reviewed skill. Importance is determined again from the new job: the old required/preferred label is not blindly copied.
5. **Forget mapping** and **Forget corrections for this description** remove those respective memory entries. They are separate controls; removing an alias does not erase an independently saved job review.

Memory is stored in the local SQLite tables `skill_alias_memory`, `requirement_reviews`, and `requirement_feedback` under `.job_assistant/`. It contains reviewed job quotations and labels, not CV-derived training records or credentials. It is supplied to Job Workspace analyses; standalone Python callers can opt in through `parse_job_text(..., memory=...)` or `analyze_texts(..., requirement_memory=...)`. CLI tools and source-board fetchers use stateless extraction unless a caller explicitly provides memory.

**What “learning” means here:** accumulating user-approved, reversible extraction corrections—not silently training on every upload or updating an external model. Precision can improve for reviewed phrases, but incorrect corrections can also reduce it; keep testing on unseen descriptions. Complex negation, alternatives (“Python or Java”), unfamiliar wording, and non-English descriptions still require human review. The built-in capability rules do not replace a general semantic model.

### Visual design

The app uses a calm, high-contrast workspace layout: a warm paper surface, forest-green job header, compact Career-track rail, and nine contextual role windows. The Job Workspace—not the generic chat—is the primary unit. Overview foregrounds a next-best action; deeper detail stays in Job brief, CV studio, Evidence match, Proof projects, Interview lab, Career track, Role market, and Coach. Cards and expanders provide progressive disclosure so source review does not interrupt a first pass. The layout is optimized for desktop; Streamlit provides basic responsive behavior, but a narrow-mobile visual review remains future work.

### Role market and lawful sources

The **Role market** replaces the prior manual-contact-research entry point with a role-first local opportunity board. It does not discover people, create contacts, submit applications, or send messages.

- Enter the role to explore, inspect the suggested lookalike titles, and edit the comma-separated aliases before refreshing. Suggestions come from a small, inspectable local rule set; they are not an opaque relevance claim.
- Select one or more **registered public feeds** and choose **Discover matching openings**. The current registered market uses only vetted Greenhouse and Ashby employer-board feeds, and makes no request until that button is selected. It is not a provider-wide or internet-wide crawler. Lever remains available for a user-entered official board in **Bring a lawful source**.
- The ranking is deterministic and explainable: title/alias similarity plus overlap with skills detected locally from the selected CV. CV text stays local for this ranking and is never sent to a board. A listing card shows why it appeared; the score is not a suitability, hiring, or qualification assessment.
- Opening provenance is retained through deduplication: provider, board identifier, external listing ID, listing URL, and retrieval time remain available for each observed source. Company-type, size, and funding filters are shown as **Unknown** unless a linked company-facts source supports a value; leaving a filter empty includes all values, while selecting **Unknown** deliberately includes unsourced records.
- The role-location map uses only locations stated on matching listings. It never substitutes a company HQ, office footprint, or inferred geography. A listed location without local coordinates is shown without a pin, and a listing with no location stays unlocated.
- **Search this role on LinkedIn** is an outbound handoff only: it opens LinkedIn with the chosen query. The app does not scrape LinkedIn, import a LinkedIn job feed, or search people/profiles.
- **Bring a lawful source** is separate from the registered role market: enter an official employer board you know (Greenhouse, Lever, or Recruitee), use a permitted SmartRecruiters employer token, or import a CSV/JSON job export you personally exported or obtained with permission. These inputs remain reviewable and are not silently added to the registered-feed market.
- Registered-feed role cards distinguish **Open official application** from **Prepare this application**. The first opens the supplied employer page; the second creates (or reopens) a local preparation workspace. Manual-board and imported jobs retain **Create job workspace** buttons. The workspace pre-fills title, company, URL, and description in the current Career track, with the shared CV as a starting point. Review the new workspace and analyze the job; opening, saving, tracking, or preparing a listing does not record an application as submitted.
- **Profile company explorer** is a separate research view, using a small local catalogue and skill overlap from the selected Job Workspace's CV (or the saved shared profile if this workspace has no CV). Its source-linked HQ/research/engineering-hub footprint is not the role-location map and never supplies locations for an opening.

The separate **Company database** route (`?view=companies`) adds company discovery without weakening these source rules. CompaniesMarketCap is read from one ranking page and the YC import reads the yc-oss `companies/hiring.json` snapshot; each request is fixed-host, HTTPS-only, 15-second bounded, capped at 8 MB and stores at most 100 companies. The initial local catalogue contains 10 public companies and 10 hiring YC hardware startups; refreshes are manual and idempotent. Remote YC logos load only after the user opts in because the image host otherwise receives the browser's IP address. A directory record produces no jobs until its supported official ATS board is tested and saved.

Example CSV schema for a lawful job export:

```csv
title,company,required_skills,preferred_skills,url
Backend Engineer,Example Systems,"Python, Docker",SQL,https://example.com/careers/backend
```

JSON accepts a list of objects with equivalent fields, or an object containing a `data` or `items` list. Preserve provenance; imported data is not independently verified simply because it is present.

### Coach

Each Job Workspace has an independent **Coach** window. History is saved locally and can be downloaded as text. Switching workspaces restores the chosen history, not a global chat.

- **Local report guide (default):** no API key or model call. Ask for `skill gaps`, `CV suggestions`, `project roadmap`, or `compare roles`. It navigates saved results through templates; it is not an open-ended tutor.
- **Optional AI coach:** enable the model toggle and explicitly consent to sending context. `OPENAI_API_KEY` and `MODEL_NAME` must be available. Preview the exact context before submitting: the current non-stale analysis (including candidate/job data), up to 12 messages from this Job Workspace, and job/skill summaries from its Career track. Other tracks and other workspaces' conversations are not sent.
- **Boundaries:** coaching is read-only, with no tools, a one-turn limit, a 60-second timeout, and bounded input size. It cannot change official scores, submit applications, or create evidence. Model responses may still be wrong; review advice before acting. Failed requests do not save partial turns.

### Interview lab

Complete a current assessment in the active Job Workspace first, select a question, and type an answer. Interview inputs/transcripts are keyed by workspace and question to avoid mixing them. **Score and save this rehearsal** records the question, answer, structural feedback, and score only inside that selected workspace; the lab shows a compact history and average practice-evidence score. Recording is optional. Selecting transcription sends the recording to OpenAI. Feedback currently checks expressions associated with context, action, validation, and reflection. It does not assess whether an engineering explanation is correct.

## 4. Scores, evidence, and known limitations

### Current scoring rules

`matching.py` calculates:

```text
role coverage = round(100 × (0.8 × required coverage + 0.2 × preferred coverage))
```

A requirement matches when a skill mapping resolves to evidence marked `confirmed`. That flag currently reflects parser rules, not an independent fact check.

`career.py` combines four heuristic components:

| Component | Weight |
|---|---:|
| Target-role coverage | 55% |
| CV structure | 20% |
| Contact/portfolio presence | 10% |
| Outcome wording/numbers | 15% |

These weights are design choices, not scientifically calibrated hiring predictors. A 90/100 score is neither a promise of interviews nor proof that the candidate understands a subject.

### Known issues to fix first

1. **Absent requirements receive automatic credit.** An empty preferred list contributes full preferred credit: a candidate with no matching skills can receive 20/100. Normalize weights over groups actually present.
2. **Confirmation is inconsistent.** An explicit `Skills:` list is marked confirmed automatically; keywords extracted from prose are not. Introduce explicit user confirmation and distinguish self-report from demonstrated competence.
3. **Skill aliases can overstate evidence.** `unit testing` currently maps to `pytest`, although the former does not imply experience with that specific tool.
4. **Authenticity is not verified.** Numbers or overlapping skill words can exempt unsupported statements. A diagnostic claim, “Managed 200 hospitals worldwide,” returned `ready` without supporting evidence. Generic wording cannot reveal whether AI wrote a CV.
5. **Source provenance is incomplete.** Some evidence quotes are summaries or clipped document text, not exact claim spans. Evidence IDs alone do not establish entailment.
6. **Final-draft review is missing.** The authenticity module checks the source CV, not a complete final résumé against approved claims. Disclosure suggestions should depend on actual AI assistance, not a style heuristic.
7. **Monitoring confuses identity with content.** Its fingerprint includes requirements, so an edited role can appear new. A failed/partial fetch must not be interpreted as closure.
8. **Adapters and imports can silently omit data.** Add schema fixtures, pagination/detail retrieval where needed, source completeness indicators, and explicit error reporting.

Treat `ready`, `needs_review`, and `blocked` as current heuristic labels, not certifications. Do not inflate metrics to satisfy the checks. Qualitative outcomes, reproducible tests, and a truthful account of personal contribution can all be useful evidence.

## 5. Architecture and data flow

```mermaid
flowchart TD
    CV[CV text or document] --> Parse[Deterministic parsing]
    Job[Target job text] --> Parse
    Parse --> Models[Candidate and job models]
    Models --> Match[Skill coverage and CV heuristics]
    Match --> Plan[Static learning and project templates]
    Models --> Draft[CV editing suggestions]
    Models --> Review[Source-CV review heuristics]
    Plan --> UI[Streamlit results and Markdown report]
    Draft --> UI
    Review --> UI
    UI --> DB[Local SQLite snapshots]
    CLI[Optional Tau CLI agent] --> Tools[Domain tools]
    Tools --> Parse
```

```text
src/tau_job_application/
├── agent.py             # optional Tau harness, instructions, turn limit
├── tools.py             # typed tool adapters for domain functions
├── models.py            # Pydantic candidate/job/evidence/report contracts
├── parsing.py           # local file extraction and candidate/job parsing
├── job_pages.py         # safe one-URL HTML/JSON-LD job-page extraction
├── requirements.py      # contextual job requirements and sourced review validation
├── requirement_memory.py # local approved phrase mappings and job corrections
├── matching.py          # deterministic skill coverage
├── hiring_match.py      # candidate-owned CV/project evidence matching and safe aggregate-benchmark contract
├── evidence_match_store.py # scoped SQLite storage for completed project proof
├── career.py            # CV heuristics, template tailoring, contact queries
├── company_explorer.py  # local, profile-skill company / selected-hub catalogue and ranking
├── company_catalog.py   # bounded public/YC company imports and reviewed ATS mappings
├── authenticity.py      # source-CV wording/claim heuristics
├── planning.py          # static skill resources and project templates
├── sources.py           # company-board APIs, registered-board raw openings, and GitHub signals
├── role_discovery.py    # role-market records, aliases, local ranking/filtering, provenance, and run storage
├── official_sources.py  # official-platform reads and CSV/JSON imports
├── monitoring.py        # local source/job snapshots
├── interview.py         # questions, structure checks, audio transcription
├── pipeline.py          # analysis orchestration and Markdown rendering
├── storage.py           # legacy analysis/audit SQLite storage
├── workspaces.py        # Career track, workspace/profile/chat storage, skill aggregation
├── workspace_ui.py      # sidebar, Career track overview, conversations
├── workspace_chat.py    # scoped local guide and optional read-only model coach
├── cli.py               # demo, analyze, agent, ui commands
└── ui.py                # Streamlit interface
```

Dependencies are pinned/bounded in `pyproject.toml` and resolved in `uv.lock`. The `tau-ai` distribution supplies both `tau_ai` and `tau_agent`; the application does not modify Tau internals.

## 6. Job sources and European coverage

The **Role market** is a user-triggered, role-first view over a small registered set of Greenhouse and Ashby public employer feeds. It is not a comprehensive European job index: it does not search arbitrary boards, crawl aggregators, or infer whether a person can work in a location. Its suggested aliases are editable, and CV-skill overlap is calculated locally after listings are retrieved. A separate **Bring a lawful source** panel remains available for an official board, authorized integration, or permitted export that the user supplies.

| Connector | Current scope | Reference |
|---|---|---|
| Greenhouse | Registered public feeds power the Role market; a user can also read a known official employer board in the separate lawful-source panel | [Job Board API](https://developers.greenhouse.io/job-board.html) |
| Lever | A user can read a known official employer board in the separate lawful-source panel; it is not currently in the small registered Role-market set | [Postings API](https://github.com/lever/postings-api) |
| Ashby | Registered public feeds can use Ashby's documented public job-postings API | [Job Postings API](https://developers.ashbyhq.com/docs/public-job-posting-api) |
| Recruitee | Official careers-site board entered by the user in the lawful-source panel; not a registered Role-market feed | [Careers Site API](https://docs.recruitee.com/reference/intro-to-careers-site-api) |
| SmartRecruiters | Official employer integration only with a permitted company token; not a registered Role-market feed | [Posting API](https://developers.smartrecruiters.com/docs/posting-api) |
| LinkedIn | Outbound handoff to a user-selected role search; authorized-user OIDC identity is separate | No listing feed/import, résumé extraction, people search, or scraping |
| X | Explicit official recent-post search; posts are signals, not verified vacancies or Role-market results | [X API documentation](https://docs.x.com/) |
| User job URL | One explicit public HTTPS fetch; no crawler/search, response cap, public DNS/redirect checks, readable text + JSON-LD | [Schema.org JobPosting](https://schema.org/JobPosting) |
| CSV/JSON | User-provided or licensed job records, reviewed separately from the registered Role market | Import formats above |

Each Role-market result retains its provider/board/listing provenance. Company type, employee band, and funding stage are filterable only as source-backed values; a missing fact is displayed as **Unknown**, rather than inferred from a company name. Its map reflects only locations written on the job listing, never a company headquarters or office catalogue.

EURES, Welcome to the Jungle, XING, StepStone, and national employment-service integrations are **not implemented**. Their current access/usage terms need individual review; this is not a claim that all require the same commercial arrangement.

See [European source strategy](docs/EU_JOB_SOURCE_STRATEGY.md) for research context. Validate its assumptions against current official documentation before adding a connector. A funding round or product release can motivate research but does not prove hiring.

## 7. Privacy and review boundaries

- The product has no application-submission, bulk-email, automated follow-up, person-enrichment, or messaging tools. Its current social-platform integrations are explicit official API reads, not browser scraping.
- A submitted job URL is fetched only on the user's explicit button press. The fetcher rejects non-HTTPS URLs, embedded credentials, local/private/reserved addresses, unsupported content types, oversized responses, and non-public redirects. It does not crawl linked pages.
- Analysis snapshots contain CV text and personal data in `.job_assistant/assistant.sqlite`. Git ignores this directory, but **Git exclusion is not encryption**.
- The UI is a local prototype without multi-user authentication/isolation. Do not expose it publicly without additional security work.
- API tokens are not deliberately written to SQLite. However, password widgets can retain values in server-side session memory; “used once and immediately erased” is not a guarantee.
- The optional Tau CLI sends supplied CV/job text to the configured provider. The optional UI coach sends the explicitly previewed thread/direction context after consent. Transcription sends audio to OpenAI. Public-source requests send the identifiers/queries required by those services.
- A Role-market refresh sends the selected registered board identifiers and retrieves their published listings only after the user presses refresh. CV-derived skills rank returned listings locally; CV text is not sent to a job board. The LinkedIn control only opens an outbound search URL and does not retrieve LinkedIn listings.
- The profile company explorer compares CV skills to its local catalogue in-process. Its map basemap is fetched by the browser from Carto; map requests do not include CV text, profile links, or the company-match list. Company-footprint source and career links open only after an explicit user action. Site descriptions are source-linked research prompts, not live role data or a comprehensive office directory.
- Portfolio/social URLs, imported records, and generated text must be reviewed. A URL's presence or an email's format does not verify a person's role or address.
- Data-retention, selective deletion, consent records, credential clearing, and error-redaction tests remain necessary improvements.
- New portal reply data is read only after conversation-level consent; connector errors are redacted and tokens are supplied through the server environment. Reply excerpts persist locally until application deletion. Exact sender matching is not cryptographic identity verification; start with manual review. Auto-mode is a prototype literal classifier, not a reliable universal email-understanding system.
- No AI-authorship percentage, ATS-pass guarantee, hiring probability, or independently verified CV claim is produced by the current system.

## 8. Proposed learning system

**Everything in this section is a proposed design.** The current resource list and interview prompts are only starting points.

### Separate three things

| Record | What it means | What it does not mean |
|---|---|---|
| Job requirement | An employer requests a capability | The requirement is necessarily essential or correctly extracted |
| Learner state | Evidence from attempts, explanations, hints, and later tests | A CV keyword proves mastery |
| Application evidence | A reviewable project, contribution, or achievement | Completing a course automatically creates work experience |

The product should track these separately. Better writing can improve clarity without improving knowledge; studying can improve knowledge before it creates publishable project evidence.

### Learning loop

```mermaid
flowchart TD
    Goal[Target role and learner goals] --> Map[Concepts and prerequisite graph]
    Map --> Diagnose[Short diagnostic and practical task]
    Diagnose --> Teach[Targeted explanation or worked example]
    Teach --> Attempt[Independent attempt with optional hints]
    Attempt --> Feedback[Specific feedback and self-explanation]
    Feedback --> Project[Small realistic project]
    Project --> Transfer[Unseen task and delayed retest without AI]
    Transfer --> State[Update evidence and uncertainty]
    State --> Diagnose
    State --> CV[Candidate-reviewed application evidence]
```

For each concept, record its definition, prerequisites, example, common misconceptions, assessment rubric, source resources, and review history. Attempts should store whether assistance was used; assisted success and independent success must not be treated as equivalent.

### Example: preparing for a backend role requiring Docker

1. **Diagnose:** ask the learner to distinguish images, containers, processes, ports, and persistent storage; include a small debugging task.
2. **Explain:** use one worked example, with an explanation of why each configuration choice is necessary.
3. **Practice:** let the learner containerize a small API. Offer hints before a complete solution, without trapping them in endless questioning.
4. **Explain back:** ask why an application binding to localhost inside a container may not be reachable through a published port.
5. **Transfer:** give a different application's broken container/network configuration to diagnose without AI help.
6. **Retain:** revisit the concept later with a different task, not the same memorized answer.
7. **Publish evidence:** retain the repository, tests, reproducible run instructions, limitations, and the candidate's actual contribution.
8. **Update the application:** only after review, describe the completed project accurately. Do not turn it into invented employment experience.

The same structure can serve other fields: an analyst can critique a model on a new dataset; a designer can defend a decision under changed constraints. Field-specific tasks and rubrics need domain-expert review.

### Resource selection

For each gap, recommend a small sequence: prerequisite explanation → official reference or textbook chapter → practice task → applied project → deeper paper. Record the author's/source authority, assumed prerequisites, language, access cost, estimated effort, and why the material is relevant. Avoid assigning an advanced research paper before the learner has its foundations. A link list is not a curriculum.

## 9. Research papers and implementation ideas

The references below separate **published findings** from **our proposed application**. They do not establish that this product improves hiring outcomes. Findings from prose recall, programming tutors, or school mathematics must be tested before being generalized to European job applicants.

Suggested first reads: **Dunlosky → Roediger & Karpicke → Chi → Bastani → RAG → τ-bench**. Add the others when implementing the corresponding feature.

### A. Helping applicants actually learn

#### 1. Dunlosky et al. (2013) — learning techniques

**John Dunlosky, Katherine A. Rawson, Elizabeth J. Marsh, Mitchell J. Nathan, and Daniel T. Willingham.** *Improving Students' Learning With Effective Learning Techniques: Promising Directions From Cognitive and Educational Psychology.* Psychological Science in the Public Interest.

[Paper / DOI](https://doi.org/10.1177/1529100612453266) · [Accessible overview](https://www.psychologicalscience.org/publications/journals/pspi/learning-techniques.html)

- **Read for:** evidence comparing techniques, especially practice testing and distributed practice, rather than relying on rereading/highlighting alone.
- **Proposed change:** add retrieval tasks and spaced reviews to `planning.py`; record responses instead of checking off “read this resource.”
- **Experiment:** equal study time with a resource list versus a resource list plus spaced retrieval; measure delayed independent performance.
- **Boundary:** a review of learning techniques does not specify the best schedule or curriculum for every learner and field.

#### 2. Roediger & Karpicke (2006) — retrieval practice

**Henry L. Roediger III and Jeffrey D. Karpicke.** *Test-Enhanced Learning: Taking Memory Tests Improves Long-Term Retention.* Psychological Science.

[Paper / DOI](https://doi.org/10.1111/j.1467-9280.2006.01693.x)

- **Read for:** the difference between immediate familiarity and later recall; retrieval can contribute to learning, not merely measure it.
- **Proposed change:** ask for an explanation or solution before revealing the reference answer; revisit concepts using new prompts.
- **Experiment:** compare rereading with retrieval practice on a delayed, no-AI assessment.
- **Boundary:** the experiments used prose-learning tasks; do not assume recall gains alone demonstrate engineering competence or transfer.

#### 3. Chi et al. (1989) — self-explanation

**Michelene T. H. Chi, Miriam Bassok, Matthew W. Lewis, Peter Reimann, and Robert Glaser.** *Self-Explanations: How Students Study and Use Examples in Learning to Solve Problems.* Cognitive Science.

[Paper / DOI](https://doi.org/10.1207/s15516709cog1302_1) · [Author-hosted PDF](https://education.asu.edu/sites/g/files/litvpz656/files/lcl/chibassoklewisreimannglaser_0.pdf)

- **Read for:** how learners connect example steps to principles and identify gaps in their own understanding.
- **Proposed change:** add “why does this step work?”, “what assumption is necessary?”, and “what changes if this condition changes?” prompts after worked examples and projects.
- **Experiment:** grade novel transfer tasks after example-only versus example-plus-explanation practice.
- **Boundary:** fluent explanations can be wrong. Grade their reasoning against a domain rubric, not word count or confidence.

#### 4. Collins, Brown & Newman (1987 technical report) — cognitive apprenticeship

**Allan Collins, John Seely Brown, and Susan E. Newman.** *Cognitive Apprenticeship: Teaching the Craft of Reading, Writing, and Mathematics.* Technical Report No. 403.

[ERIC record and full-text access](https://eric.ed.gov/?id=ED284181)

- **Read for:** modeling, coaching, scaffolding, articulation, reflection, and exploration. This is a design framework, not a randomized evaluation of our workflow.
- **Proposed change:** sequence projects from a worked example to a partly supported task and then an independent task. Gradually remove assistance; ask learners to explain decisions and compare alternatives.
- **Experiment:** compare scaffolding that fades with constant answer assistance, using a new independent project as the outcome.
- **Boundary:** software that completes every project for the learner may improve artifacts without improving the learner's ability.

#### 5. Corbett & Anderson (1994) — knowledge tracing

**Albert T. Corbett and John R. Anderson.** *Knowledge Tracing: Modeling the Acquisition of Procedural Knowledge.* User Modeling and User-Adapted Interaction.

[Paper / DOI](https://doi.org/10.1007/BF01099821)

- **Read for:** estimating a learner's changing skill state from sequences of responses, including uncertainty about guesses and slips.
- **Proposed change:** add a separate learner-state store; begin with transparent rules, then compare a Bayesian knowledge-tracing model when enough concept-labeled response data exists.
- **Experiment:** predict later independent answers and evaluate calibration on held-out learners. Compare with a simple recent-performance baseline.
- **Boundary:** inferred mastery depends on task labels and model assumptions. It is neither a CV score nor proof of broad professional competence.

#### 6. Bastani et al. (2025) — AI assistance versus learning

**Hamsa Bastani, Osbert Bastani, Alp Sungu, Haosen Ge, Özge Kabakcı, and Rei Mariman.** *Generative AI without guardrails can harm learning: Evidence from high school mathematics.* PNAS.

[Paper / DOI](https://doi.org/10.1073/pnas.2422633122) · [Data and code](https://github.com/obastani/GenAICanHarmLearning)

- **Read for:** the distinction between doing well while using AI and learning to perform after the assistance is removed; tutor design matters.
- **Proposed change:** separate practice mode from independent assessment. Use graduated hints, record assistance, and include no-AI follow-up tasks.
- **Experiment:** compare answer-first and hint-first tutoring, measuring later unaided performance rather than only supported task completion.
- **Boundary:** the field experiment concerns high-school mathematics, not CV preparation or professional hiring. It motivates local evaluation, not a universal claim that AI harms learning.

#### 7. Wang et al. (2024; revised 2025) — Tutor CoPilot

**Rose E. Wang et al.** *Tutor CoPilot: A Human-AI Approach for Scaling Real-Time Expertise.* Research preprint.

[Paper, arXiv:2410.03017](https://arxiv.org/abs/2410.03017) · [Demonstration code](https://github.com/rosewang2008/tutor-copilot/)

- **Read for:** supporting human tutors with pedagogical suggestions instead of replacing them with unrestricted answer generation.
- **Proposed change:** prototype a mentor view where a human can review suggested questions, hints, and feedback before the learner receives them.
- **Experiment:** compare mentor-only and mentor-plus-assistant sessions, tracking independently assessed learning and mentor workload.
- **Boundary:** this is evidence about a human–AI tutoring system in a specific educational setting, not evidence for fully autonomous career coaching. Results vary by paper version; do not mix reported samples.

### B. Improving the agent's technical reliability

#### 8. Lewis et al. (2020) — retrieval-augmented generation

**Patrick Lewis et al.** *Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks.* NeurIPS.

[Paper, arXiv:2005.11401](https://arxiv.org/abs/2005.11401)

- **Read for:** conditioning generation on retrieved material instead of relying only on model parameters.
- **Proposed change:** give explanations and résumé drafts a bounded evidence pack containing approved CV spans, role requirements, and vetted educational sources. Require source references for material claims.
- **Experiment:** compare generation without retrieval against retrieval-assisted drafting on unsupported-claim rate, citation correctness, and human usefulness.
- **Boundary:** retrieval and citations do not guarantee entailment or truth. Start with exact evidence lookup; a vector database is not automatically necessary. Our adapter would borrow the pattern, not reproduce the paper's trained architecture.

#### 9. Reimers & Gurevych (2019) — semantic matching

**Nils Reimers and Iryna Gurevych.** *Sentence-BERT: Sentence Embeddings using Siamese BERT-Networks.* EMNLP-IJCNLP.

[Paper, arXiv:1908.10084](https://arxiv.org/abs/1908.10084)

- **Read for:** efficient sentence representations for similarity and retrieval.
- **Proposed change:** compare explicit skill aliases with embedding-based candidate mappings for differently worded job requirements; keep original text and require review for uncertain mappings.
- **Experiment:** evaluate precision/recall on human-labeled equivalents and deliberately related-but-not-equivalent pairs; test relevant languages separately.
- **Boundary:** similarity is not proof of competency or semantic equivalence. “Studied cloud computing” must not automatically become “operated AWS infrastructure.” European languages require appropriate models and evaluation data.

#### 10. Yao et al. (2022 preprint; ICLR 2023) — ReAct

**Shunyu Yao et al.** *ReAct: Synergizing Reasoning and Acting in Language Models.*

[Paper, arXiv:2210.03629](https://arxiv.org/abs/2210.03629)

- **Read for:** interleaving model decisions with tool observations rather than generating an entire plan without checking external state.
- **Proposed change:** extend the existing Tau harness with narrow tools for approved evidence retrieval, diagnostic tasks, and learning-plan updates. Keep scores, permissions, and canonical state changes in application code.
- **Experiment:** compare a fixed workflow with a bounded tool-using agent on missing information, source failures, and invalid tool inputs. Measure correctness, cost, and latency.
- **Boundary:** additional agent turns do not guarantee better output. Expose concise action/results logs, not private internal reasoning; keep tool and cost limits.

#### 11. Yao et al. (2024) — τ-bench

**Shunyu Yao et al.** *τ-bench: A Benchmark for Tool-Agent-User Interaction in Real-World Domains.*

[Paper, arXiv:2406.12045](https://arxiv.org/abs/2406.12045)

- **Read for:** evaluating stateful agent tasks, policy compliance, and consistency over repeated runs rather than judging only plausible prose.
- **Proposed change:** build scenario tests such as “candidate rejects a CV claim,” “job source is unavailable,” and “a learner's project is incomplete.” Check final records and allowed actions.
- **Experiment:** repeat tasks with fake and live providers, measuring correct final state, unauthorized actions, and consistency across runs.
- **Boundary:** original benchmark domains are not this application. Borrow the evaluation method and create our own domain fixtures. The benchmark and the installed Tau library are distinct projects.

### Reading notes template

For each paper, write a short engineering note:

1. What problem did the authors study, with which participants/data/tasks?
2. What did they actually measure, and what remains uncertain?
3. Which single product change does this suggest?
4. What simple baseline should it beat?
5. What would count as failure or negative evidence?
6. What domain/language differences make direct transfer uncertain?

Read methods and limitations, not just abstracts. These links identify the source papers; the proposed implementations are our design hypotheses, not author endorsements.

## 10. Experiments and evaluation

### Compare approaches before adding complexity

| Approach | Suitable starting point | Compare against | Main outcome |
|---|---|---|---|
| Static prerequisite map + retrieval practice | Low-data MVP | Existing resource list | Delayed recall and task performance |
| Worked examples + self-explanation + fading hints | Project preparation | Complete-solution assistance | Independent transfer task |
| Retrieval-grounded adaptive tutor | Vetted source library available | Same tutor without retrieval | Correct feedback and supported explanations |
| Bayesian knowledge tracing | Enough reliable concept-labeled attempts | Simple recent-performance rules | Calibration on later independent attempts |
| Human mentor + AI suggestions | High-stakes or ambiguous topics | Mentor alone | Learning improvement and mentor effort |
| Multi-agent research | Only after a single workflow shows a measurable bottleneck | One bounded agent | Evidence quality, latency, cost, and failure rate |

Do not assume multiple agents are better. The product currently has none; splitting a workflow adds coordination and error-propagation risks.

### Small pilot protocol

1. Choose one field and a narrow concept set, such as backend fundamentals. Have a domain expert review tasks and rubrics.
2. Give participants a baseline task and collect prior experience; keep learning data separate from application claims.
3. Randomly assign comparable practice conditions where feasible, with equal time/resources and informed consent. Offer delayed access to useful materials to comparison participants.
4. Use unseen assessment tasks without AI assistance immediately after practice and again after a delay. A one-week retest is a practical starting choice, not a universal optimum.
5. Score with a fixed rubric, preferably blinded to condition. Combine automated checks with human review of explanations and trade-offs.
6. Report sample size, attrition, assistance usage, uncertainty, and negative results. A small pilot tests feasibility; it does not prove broad effectiveness. Choose a larger study's sample size using a power analysis.

### What to measure

- **Knowledge:** delayed retrieval and correctness of explanations.
- **Understanding:** ability to justify decisions, identify assumptions, and diagnose misconceptions.
- **Transfer:** performance on a new problem, not a memorized example.
- **Independence:** attempts solved without assistance and hints needed during practice.
- **Project evidence:** reproducibility, tests, limitations, and attributable personal contribution.
- **Agent reliability:** supported draft claims, citation accuracy, correct final state, adapter completeness, cost, and latency.
- **Application usefulness:** user-rated shortlist relevance, correction burden, and time to a reviewed application.

Course completions, time spent chatting, polished explanations, and higher CV scores are not sufficient learning outcomes. Hiring/interview outcomes can be tracked with consent, but market conditions and selection effects prevent simple causal attribution to the app.

## 11. Implementation roadmap

Detailed product comparison: [Jobright improvement report](docs/JOBRIGHT_IMPROVEMENT_REPORT.md).

| Order | Deliverable | Acceptance condition |
|---|---|---|
| 1 — Correctness | Explicit claim review, confirmation editor, score fixes, adapter fixtures | Numbers/keywords cannot verify a new claim; zero matches yield zero coverage; partial fetches are visible |
| 2 — Application workflow | Europe-aware shortlist, complete résumé editor, reviewed export, application tracker | Select a role, edit and approve a full résumé, download it, and restore application history after restart |
| 3 — Learning MVP | Diagnostic tasks, concept graph, retrieval review, project evidence | Learner completes an unseen task and delayed retest; only reviewed evidence changes the application profile |
| 4 — Adaptive support | Source-grounded tutor, validated feedback, optional mentor view | Beats a simple baseline on independently assessed learning without unacceptable cost/error increases |
| 5 — Discovery | Stable job identities, updates/closures, sourced networking, opt-in alerts | Updates are not duplicates; outages do not close jobs; scheduling follows provider rules and user preferences |

Keep the UI simple: **shared profile → career direction → target-job thread → reviewed application → learn/build next → demonstrate progress**. Avoid spending effort on bulk autofill before the core workflow and learning outcomes are reliable.

## 12. Testing and troubleshooting

Role-first delivery verification is recorded in the reports; rerun the current suite rather than relying on a historical test count. Company-catalog coverage includes HTML/JSON parsing, input bounds, fixed source selection, idempotent persistence, and reviewed board-provider validation. Live Gmail/Slack credentials were not used. See the [role-first report](docs/ROLE_FIRST_IMPLEMENTATION_REPORT.md) and [company-catalog report](docs/COMPANY_CATALOG_IMPLEMENTATION_REPORT.md).

### Role-first operations and resource budget

The feature map and interfaces are in [module context](src/tau_job_application/codex.md). No new runtime dependencies, custom browser JavaScript, visitor analytics or fingerprinting were added. Portal pages show at most twelve vacancy tiles at once; catalogue imports and displays are bounded, uploads are capped at 5 MB, extracted documents at 100,000 characters, and optional reply polling at one check per 60 seconds while its page remains open. Initial framework payload and load-time baselines are unmeasured; establish them before public deployment rather than claiming a performance improvement.

Continue to bind the preview to localhost. Public hosting needs authentication, account isolation, HTTPS/security-header policy, safe credential lifecycle, validated mail attribution, retention/deletion controls and coordinated rate limits. To back up private data, stop the app and protect a copy of `.job_assistant/assistant.sqlite`; test restoration before destructive changes. No managed backup, incident-alert service or public deployment is configured. Credentials remain environment configuration; dependencies remain locked in `uv.lock`. The implementation report records current limitations and follow-up release gates.

### Existing regression suite

```bash
uv run --no-sync pytest -q
uv run --no-sync python -m py_compile src/tau_job_application/*.py
```

The suite now includes contextual requirement extraction, review-memory persistence/reuse/deletion, invalid source-quote rejection, scoped workspace/chat persistence, shared-profile behavior, stale snapshot handling, skill aggregation, a fake-provider read-only coaching test, and Streamlit review/navigation/restart tests, alongside the original regression tests. These primarily cover synthetic examples and mocked responses. Some tests encode permissive heuristic behavior; they need to change when the known issues are fixed. A green test suite does not prove that live APIs, multilingual documents, authorship checks, or a full browser workflow work correctly.

### Manual checks

- Run `demo` and compare the report with `fixtures/candidate.txt` and `fixtures/job.txt`.
- Upload selectable-text PDF, DOCX, TXT, and Markdown examples; inspect extracted facts rather than trusting a score.
- Try empty documents, scanned PDFs, unsupported formats, and job text without recognized skills; expect explicit errors.
- Use an employer's **verified current** board identifier rather than assuming a company uses a particular ATS.
- Refresh an unchanged board twice: expect no new fingerprints on the second run, subject to the monitoring limitations above.
- Exercise imports with missing columns, invalid JSON, duplicates, and oversized files.
- Check that numerical claims and generic phrases do not get mistaken for independent truth/authorship verification.
- Confirm no transcription/API request happens until its action is selected; inspect only synthetic audit data for credential leakage.
- Test browser reruns, stale results after input edits, failed GitHub enrichment, download behavior, and question-specific transcript handling.

### Next automated tests

Add multilingual parsing fixtures, unsupported-generated-claim regressions, exact evidence-span checks, provider contract/pagination tests, scoring edge cases, stable job-identity tests, credential-redaction tests, and Streamlit interaction tests. Use synthetic documents or explicitly consented data; do not commit private CVs or application files.

### Common problems

| Symptom | What to check |
|---|---|
| Package cannot be imported after editable install | Use the regular `uv sync --no-editable --reinstall-package ...` command above |
| Source edits do not appear in the UI | Reinstall the package and restart Streamlit |
| Scanned PDF yields no text | OCR it externally first; OCR is not implemented |
| Real CV scores poorly despite relevant skills | Inspect parsing and confirmation status; the vocabulary and matching rules are limited |
| Job board returns no jobs | Check identifier, provider access, response shape, and skipped parsing; an empty list is not proof that hiring stopped |
| Token in `.env` has no effect | Export it in the launch shell; `.env` is not automatically loaded |
| API request fails | Check permissions, rate limits, network access, and provider-plan requirements |

---

## References and project notes

- [Jobright comparison and code-review backlog](docs/JOBRIGHT_IMPROVEMENT_REPORT.md)
- [European job-source strategy](docs/EU_JOB_SOURCE_STRATEGY.md)
- [Whali-inspired Role-market direction](docs/WHALI_INSPIRED_PRODUCT_DIRECTION.md)
- [Jobright public homepage](https://jobright.ai/) — product inspiration, not independently validated performance evidence
- [Tau library](https://github.com/huggingface/tau) — optional agent dependency
- [ESCO](https://esco.ec.europa.eu/en) — potential skill/occupation vocabulary; not integrated yet

This is a learning and application-preparation prototype. Source permissions, privacy requirements, and employer-specific application rules must be checked for the intended deployment. No claim is made that the system guarantees job offers, verifies authorship, or replaces domain expertise.
