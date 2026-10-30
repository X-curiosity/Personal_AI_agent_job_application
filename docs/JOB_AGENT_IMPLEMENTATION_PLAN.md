# Autonomous job agent: implementation plan

This is a proposed build plan, not an assertion that the complete hosted agent already operates. It complements the [architecture Q&A](APP_ARCHITECTURE_AND_AUTOMATION.md), [product integration plan](MAP_AND_AUTONOMOUS_AGENT_PLAN.md), and [map implementation plan](MAP_IMPLEMENTATION_PLAN.md).

## 1. What we know about StartupMap

StartupMap's public site describes curated company records and daily collection from career pages. A plausible system is a company/location database feeding the map, alongside job collectors feeding listings and hiring status. We have not verified its internal backend, collection methods, coordinate sources or office-level accuracy. Its markers could come from public profiles, geocoding or manual review; those are possibilities, not findings.

We should implement the visible product outcome using our own permitted sources, not assume access to a competitor's internal dataset.

## 2. Two separate systems

**Shared collection:** discover and maintain reliable public job records once for all users.

**Private recommendation:** assess those records against each user's role folders, preferences and selected CV, then propose relevant opportunities.

This avoids repeatedly crawling the same employers for every user. The autonomous agent is a controlled workflow with persistent state—not necessarily an LLM freely operating a browser.

## 3. Source registry and collection

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

## 4. Private role-folder workflow

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

## 5. Where AI belongs

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

## 6. Matching and two-project recommendations

Current deterministic matching is extracted skill coverage, not a calibrated hiring probability. The new scorer should assess explicit requirements against CV/project evidence, show citations and uncertainty, and report extraction quality separately.

For usable coverage below 70%, propose two distinct projects targeting the highest-priority learnable gaps, with deliverables, effort assumptions and acceptance criteria. Exactly 70% is not below threshold. Unreadable CVs, missing requirements and hard authorization failures need clarification or eligibility guidance—not fabricated project recommendations.

Do not raise a score simply because a project was proposed. Reassess only after the user supplies completed work and truthful evidence. Contact suggestions need public professional-source evidence and clear uncertainty; inferred email addresses remain unverified.

## 7. Runtime architecture

- **Vercel:** public map/search and private workspace interface.
- **Supabase Postgres:** company/source/job records, folders, task state and private analysis metadata.
- **Supabase Auth/private storage:** identity and CV versions, with tenant-scoped access and deletion controls.
- **Hosted Python worker:** connectors, parsing, scoring and optional model calls.
- **Scheduler:** enqueues source and folder tasks; it does not run a permanent browser session.
- **Notification adapter:** user-authorized digests with delivery status and unsubscribe/preferences.

Start with a Postgres-backed queue to avoid another service. Claim tasks atomically (for example, a transaction using `FOR UPDATE SKIP LOCKED`), use leases/heartbeats, bounded attempts and backoff. Expired leases permit recovery; task deduplication prevents repeated side effects. Track task state, attempt count, timestamps, cancellation and sanitized errors.

Use unique task keys for source refresh windows and analysis input versions. Record an outbox event transactionally with a saved recommendation, then deliver it idempotently. Sending failures with uncertain outcomes require provider reconciliation rather than blind retries. A notification provider's idempotency support must be verified rather than assumed.

Service-role credentials stay on the backend. Workers must enforce ownership even where privileged credentials bypass row-level policies. Minimize CV text in logs, configure retention and support deletion/cancellation of queued work.

## 8. Autonomy and human control

Automatic: collection, filtering, analysis, explanations, projects and opt-in opportunity notifications to the user.

Approval required: messages to third parties, sharing a CV and submitting employer applications. Bind approval to exact recipient/content/attachments or form values; edits invalidate it. Do not interpret “run my folder daily” as permission to send applications or cold emails.

Support pause, cancel, rerun and clear task status. The worker must continue preparation without an open user browser, but stop processing private data when authorization is revoked or the account is deleted.

## 9. Costs and limits

Potential costs include worker compute, network traffic, database/storage, notification delivery, model usage and licensed job feeds. Connector maintenance also costs time. A small pilot may fit provider free allowances; an always-running production service is not guaranteed free.

Reduce cost by collecting once, filtering before model calls, analyzing only relevant changed inputs, batching notifications, bounding job/CV text and applying per-user/source budgets. Show failures or deferred tasks rather than silently exceeding quotas.

Do not quote a monthly price without choosing providers and measuring: monitored sources × check frequency, jobs changed per day, users/folders, eligible analyses, model tokens per analysis and notification volume.

## 10. First release and testing

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
