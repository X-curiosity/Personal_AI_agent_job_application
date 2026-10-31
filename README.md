# Hired — company map, source-linked jobs, and a career agent

An orange-and-yellow job explorer with two parts:

- **Public:** a global company directory on a map, plus a bounded European vacancy snapshot from reviewed official employer boards (Greenhouse/Ashby). No login required.
- **Private:** your CV, role folders, evidence-based matching, and reviewed auto-apply. Mostly a local prototype today; a hosted foundation is being prepared.

It's a research-and-preparation assistant, not a production hiring platform or a validated tutor. The agent helps you become a stronger candidate; it never predicts hiring probability.

## The two surfaces

| Surface | What it is | Where |
|---|---|---|
| Public explorer | Static **Jobs / Map** site: company catalogue, source-linked jobs, logos, city routes | [`vercel-site/`](vercel-site/) — live at [co-apply-gpt](https://co-apply-gpt-magbixavier-gmailcoms-projects.vercel.app) |
| Local app | Streamlit workspace: CV analysis, role discovery, evidence matching, accounts, auto-apply | [`src/tau_job_application/`](src/tau_job_application/) |
| Hosted MVP | Account sign-in, private CVs, targets, application queue (scaffold, not yet live) | [`docs/HOSTED_MVP.md`](docs/HOSTED_MVP.md) |

## Run the local app

```bash
git clone https://github.com/X-curiosity/Personal_AI_agent_job_application.git
cd Personal_AI_agent_job_application

# Install (Python 3.12+, via uv)
uv sync --python 3.12 --no-editable --reinstall-package tau-job-application

# Run — opens http://127.0.0.1:8506
./run.sh
```

No API key is required for the core app. Optional model/account credentials are documented in [`.env.example`](.env.example).

If you see `requires a different Python: 3.9.x`, run `conda deactivate` and reinstall.

### Verify

```bash
uv run --no-sync pytest -q        # Python tests
node --test tests/*.mjs           # browser-core tests
```

## Refresh public data

```bash
# Public company directory (Capital Atlas, YC, StartupMap public pages)
PYTHONPATH=src .venv/bin/python scripts/export_public_map.py --cached-logos

# Public European vacancy snapshot
PYTHONPATH=src .venv/bin/python scripts/export_public_jobs.py
```

Jobs refresh automatically via [`.github/workflows/refresh-jobs.yml`](.github/workflows/refresh-jobs.yml) (daily 06:00 UTC). It publishes a saved snapshot, not a live feed — verify roles on their official adverts.

## Auto-apply (local, reviewed)

Deterministic browser form filling — no LLM, no provider key. Fills recognized fields, attaches your exact CV, and stops on CAPTCHA, consent, restrictions, or ambiguous fields. Every application needs your explicit final approval.

```bash
uv run --no-sync tau-job-application auto-apply cv.pdf https://employer.example/job \
  --application-id my-1 --full-name "Your Name" --email you@example.com
```

It is not an unattended bot and can't guarantee compatibility with every employer form.

## Where the project is going

Read the plans in [`docs/`](docs/):

- [App architecture and automation](docs/IMPLEMENTATION_PLAN.md) — jobs freshness, maps, the GitHub bot, outreach and legal limits.
- [Map & autonomous agent plan](docs/IMPLEMENTATION_PLAN.md) — StartupMap + Jack & Jill inspired direction.
- [Unified implementation plan](docs/IMPLEMENTATION_PLAN.md) — map details, office accuracy, and the job agent build.
- [Codex](Codex.md) — repository context and deployment history.

## Honesty notes

- Directory presence ≠ an open vacancy. HQ coordinates ≠ a job's workplace.
- City-level pins are labelled estimates; exact offices require verified addresses.
- CV matching is skill/evidence coverage, not a probability of being hired.
- No LinkedIn scraping, no invented jobs, no blind outreach. Auto-apply always requires your approval.
