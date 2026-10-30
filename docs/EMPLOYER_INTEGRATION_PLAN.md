# Employer integration plan: startups submit jobs automatically

This is a proposed employer-facing plan, not a deployed feature. It complements the [unified implementation plan](IMPLEMENTATION_PLAN.md) (map + job agent), which covers the candidate-facing map, collection, and recommendation agent.

## 1. Two meanings of "automatic"

1. **Employers push jobs to us** — a company signs up, connects a source, and jobs flow in automatically. This is self-serve onboarding.
2. **We pull jobs automatically** — reading official ATS boards on a schedule, which the project already does for a bounded set of employers.

A real "startup enters its jobs automatically" product is mostly the first, with the second as a fallback for companies that do not sign up. The two feeds share the same job records.

## 2. Recommended employer flow

```text
Company signs up → proves it owns the company → connects a source → we verify → jobs sync on a schedule → jobs go live
```

### Step 1 — Claim and verify the company

- Employer creates an account, then finds or creates their company record (already in the catalogue, or new).
- Verify control. Cheapest reliable checks:
  - Email at the company domain (`person@company.com`) plus a one-time confirmation token.
  - DNS TXT record, or sign-in through the ATS owner account.
- Verification is required; otherwise anyone could post fake jobs under a real startup's name.

### Step 2 — Connect a source

| Connection | Effort for the company | Our work |
| --- | --- | --- |
| Official ATS API (Greenhouse, Lever, Ashby, Workable, Recruitee, …) | Paste board token / company subdomain | Read the public board API already supported |
| ATS owner webhook | Enable webhooks where their plan allows | Receive signed created/updated/closed events |
| `JobPosting` structured data + sitemap | Nothing — already on their careers site | Crawl the careers sitemap on a schedule |
| Feed (XML / RSS / JSON) | Provide a feed URL | Poll it |
| Manual form | Type/paste job details | Review before publish |

Best path: **auto-detect the ATS from the careers URL** and default to the official API — least work for the startup, most reliable for us.

### Step 3 — Automatic sync

- A worker checks connected sources on a schedule and on webhook events.
- New jobs appear; changed jobs update; closed jobs drop out.
- Store `first_seen`, `last_seen`, `source_timestamp`, and `status`. A failed sync must never silently close jobs.
- Jobs go live after automated checks (valid URL, title, location, description). Human review is an escalation for first-time posters or flagged content.

### Step 4 — Trust and abuse controls

- Rate-limit job creation per company; flag suspicious volume.
- Preserve provenance: every job shows its source and submitter.
- Companies edit/close only their own jobs; users can report stale or fake ones.
- Never let a company overwrite another company's records.

## 3. Employer dashboard

- See and edit their own live jobs.
- Close filled roles, which removes them from active recommendations without deleting history.
- View source sync status, last success and errors.
- Review reported listings.

## 4. Free versus paid

| Item | Cost |
| --- | --- |
| Employer account + self-serve portal | Free to offer; build cost is time |
| Official ATS board APIs (Greenhouse / Lever / Ashby) | Free public endpoints in most cases |
| Webhooks | Depends on the ATS plan; many require an API/integration tier |
| Structured-data crawling | Compute plus polite rate limits |
| Hosted worker + database + auth | Ongoing infrastructure cost |
| Optional human job review | People time; scale only if needed |

## 5. Relationship to the job agent

Employer-submitted jobs flow into the same shared job database the candidate-facing agent reads:

```text
Self-serve employers ─┐
Official board APIs ──┼──→ shared jobs database ──→ public map + private agent
Structured-data crawl ┘
```

One job identity feeds both surfaces. A job submitted by an employer is not inherently more trustworthy than one collected from their official ATS; both carry provenance and freshness. An employer marking a job closed is authoritative for that record.

## 6. First version and acceptance tests

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

## References

- [Unified implementation plan](IMPLEMENTATION_PLAN.md): map, office accuracy, and the autonomous job agent.
- [App architecture and automation](APP_ARCHITECTURE_AND_AUTOMATION.md): current ingestion, job freshness, and provider constraints.
- [Map & autonomous agent plan](MAP_AND_AUTONOMOUS_AGENT_PLAN.md): product direction.
