# Personal AI Agent — Job Application Assistant

A local-first, evidence-first AI agent that helps students and job seekers prepare stronger, truthful applications for European and international roles.

The agent does **not** apply to jobs, message recruiters, scrape LinkedIn/X, or invent CV facts. Instead it scores your CV against a role, identifies skill gaps, builds a learning and portfolio roadmap, tailors your CV safely, checks its authenticity, helps you find jobs through permitted sources, plans contact research, and runs mock interviews.

---

## What is implemented

### Core pipeline
- **CV intake**: text, Markdown, PDF (selectable text), DOCX.
- **Profile links**: GitHub, portfolio, LinkedIn, X — stored as references, never auto-scraped.
- **Job intake**: pasted descriptions, plus public adapters.
- **Evidence model**: every skill, requirement, and claim links to a source quote.
- **Deterministic scoring**: role-evidence match + CV readiness score with transparent components.
- **Skill tree**: missing required/preferred skills mapped to prerequisites and learning resources.
- **Portfolio project roadmap**: up to 3 sequenced projects with milestones, deliverables, and acceptance tests.
- **Truthful CV tailoring**: rewrites only what is supported by supplied evidence; suggests edits, not invented claims.
- **Authenticity review**: flags generic phrasing, unsupported claims, and missing observable outcomes; never tries to evade AI detectors.

### Job discovery and monitoring
- **Permitted public career-board APIs**: Greenhouse, Lever, Recruitee.
- **Official API connectors**: LinkedIn (authorized identity check only), SmartRecruiters (authorized Posting API token), X API v2 recent-search for hiring/product signals.
- **User-provided lawful exports**: CSV/JSON contact and job imports.
- **Local monitoring**: user-triggered refreshes record snapshots and report newly observed jobs; no hidden background polling or stored credentials.

### Interview practice
- Role-specific technical, behavioural, and motivation questions.
- Optional OpenAI audio transcription.
- Structured feedback on answer evidence, not technical correctness.

### UI
- Minimalist **Streamlit** interface with drag-and-drop CV upload.
- Three-tab layout: Quick start, Opportunities & contacts, Interview practice.
- Local SQLite history and audit under `.job_assistant/`.

---

## Run it

```bash
cd /Users/magbi/Desktop/Personal_AI_agent_job_application

# Install dependencies
uv sync --no-editable --reinstall-package tau-job-application

# Launch the minimalist UI
uv run --no-sync tau-job-application ui

# Or run the fixture demo in the terminal
uv run --no-sync tau-job-application demo

# Run the regression tests
uv run --no-sync pytest -q
```

If macOS hides the editable-install pointer, the `--no-editable` install above avoids import issues.

### Optional model credentials

Only the chat agent and audio transcription need a model provider:

```bash
export OPENAI_API_KEY="your-key"
export MODEL_NAME="gpt-4o-mini"
uv run --no-sync tau-job-application agent fixtures/candidate.txt fixtures/job.txt
```

Optional official-platform credentials:

```bash
export LINKEDIN_ACCESS_TOKEN="..."
export X_BEARER_TOKEN="..."
```

Never commit real tokens.

---

## Quick-start UI flow

1. **Drop or paste your CV** in the Quick start tab.
2. **Add your links**: GitHub, portfolio, LinkedIn, X.
3. **Paste the job description** (title, company, and description).
4. Click **Build my plan**.
5. Review the three output columns:
   - **Tailored CV**: safe summary, relevant skills, section-by-section suggestions.
   - **Improvements**: CV readiness score, next actions, authenticity review.
   - **Roadmap**: skill gaps + sequenced portfolio projects with learning resources and acceptance tests.
6. Download the full `.md` report when authenticity status is **ready** or **needs_review**.

---

## Project architecture

```text
src/tau_job_application/
├── __init__.py              # package version
├── agent.py                 # optional Tau harness with safety policy
├── authenticity.py          # detector-neutral CV authenticity review
├── career.py                # CV scoring, tailoring, contact research plan
├── cli.py                   # CLI entry points
├── interview.py             # interview questions and feedback
├── matching.py              # deterministic role-evidence matching
├── models.py                # Pydantic contracts for evidence, jobs, plans, reports
├── monitoring.py            # local job-source snapshot and deduplication
├── official_sources.py      # LinkedIn, SmartRecruiters, X official APIs; export imports
├── parsing.py               # CV and job text/document parsing
├── pipeline.py              # end-to-end analysis workflow
├── planning.py              # skill tree and portfolio project plans
├── sources.py               # Greenhouse, Lever, Recruitee, GitHub enrichment
├── storage.py               # SQLite history and audit
└── ui.py                    # Streamlit frontend
```

---

## European job-source strategy

The full decision log is in [`docs/EU_JOB_SOURCE_STRATEGY.md`](docs/EU_JOB_SOURCE_STRATEGY.md).

Implemented sources:

| Source | Type | Access |
|---|---|---|
| Greenhouse | Public career-board API | Board token |
| Lever | Public postings API | Site handle |
| Recruitee | Public Careers Site API | Company slug |
| SmartRecruiters | Official Posting API | Company-provided token |
| X | Official API v2 recent search | User bearer token |
| LinkedIn | Official OIDC identity endpoint | User access token |
| User exports | CSV/JSON import | User-owned data |

Deferred/partnership-only: EURES, Welcome to the Jungle, XING, StepStone, national public employment services.

---

## Safety and data boundaries

- **Evidence first**: candidate facts, job requirements, match explanations, and application claims carry stable evidence IDs.
- **No fabrication**: the agent never invents skills, experience, metrics, projects, contacts, or email addresses.
- **No scraping or automation on LinkedIn/X**: URLs are stored as references only; official APIs are used only for explicit user actions.
- **No contact guessing**: contact research is manual and user-reviewed; email patterns are recorded but never used to generate individual addresses.
- **No automatic applications or messages**.
- **Credentials are never stored**: API tokens are used for the current request only.
- **Local data**: analysis snapshots live under `.job_assistant/`, which is ignored by Git.

---

## Testing

Run the full test suite:

```bash
uv run --no-sync pytest -q
```

Manual checks:

1. **Fixture demo**: `uv run --no-sync tau-job-application demo` should print a complete report.
2. **File upload**: drop a PDF/DOCX/TXT CV and a job description in the UI.
3. **Public sources**: try Greenhouse `apple`, Lever `notion`, or Recruitee `datacamp`.
4. **Monitoring**: refresh the same source twice; the second run should show 0 new jobs.
5. **Authenticity**: paste generic phrases or unsupported claims and confirm the status changes.
6. **Interview**: answer a question and receive structured feedback.

---

## Dependencies

- Python 3.12+
- `tau-ai==0.2.0` and `tau_agent` for the optional model-backed agent
- `pydantic`, `pypdf` for parsing and validation
- `streamlit` for the local UI
- `pytest`, `pytest-asyncio` for tests

See `pyproject.toml` for the full list.

---

## License and legal note

This is a personal learning and job-readiness tool. It is the user's responsibility to comply with the terms of service of every platform they interact with, to use only data they have permission to use, and to review every generated claim before submitting an application.
