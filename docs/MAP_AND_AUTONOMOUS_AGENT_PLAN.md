# Hired: integrating a startup map and an autonomous career agent

## Product direction

Combine a **public startup map** with a **private career agent**, both using the same company and jobs database. They are two ways of discovering opportunities, not separate apps.

This is a proposed integration plan, not a claim that these features are already live. For implementation details and current limitations, see [App architecture and automation](APP_ARCHITECTURE_AND_AUTOMATION.md).

## 1. What to take from each product

| Inspiration | Features to build |
| --- | --- |
| StartupMap | Browse companies geographically; filter by sector, stage and hiring status; open company profiles and current vacancies. |
| Jack & Jill | Understand candidate preferences, proactively discover roles, explain matches, notify the candidate and support next steps. |

The public [StartupMap](https://startupmap.one/) page describes a curated European company directory with roles pulled daily from company career pages. [Jack & Jill](https://www.jackandjill.ai/) advertises proactive discovery, direct introductions and interview/negotiation support.

These are their public product descriptions, not an independent verification of coverage or insight into their internal architecture. In particular, **direct introductions require participating employers—not just an AI model**.

## 2. How it would work in Hired

### Public experience: Explore

Anyone can browse the map without an account:

- Company profiles, verified locations, logos and source links.
- Filters for city, industry, funding stage and available roles.
- Clear distinction between offices and estimated city locations.
- Actions to **follow this company** or **add this role to my folder**, with sign-in when saving private preferences.

### Private experience: My agent

The user signs in, uploads a CV and sets preferences. For example:

> Find junior ML roles in Belgium or remote in Europe. Prefer small startups. Exclude unpaid internships.

The agent then:

1. Checks approved job sources on a schedule.
2. Filters out incompatible roles.
3. Compares relevant roles with the selected CV version.
4. Proposes a short, ranked list with supporting evidence, gaps and freshness information.
5. Learns from **interested / not interested** feedback without silently changing hard requirements.
6. For usable matches below 70%, suggests two projects addressing learnable gaps.
7. Prepares sourced contact research, outreach drafts or applications for approval.

The agent keeps running when the user closes the website. That requires a hosted background worker, not an open browser tab.

## 3. Existing foundations and missing integration

| Existing foundation | Integration still needed |
| --- | --- |
| Public map and company catalogue | Better location accuracy, street-level navigation and verified startup classification |
| Official job-source connectors | Broader employer coverage and reliable refresh/closure handling |
| CV extraction and deterministic skill matching | Evidence-based ranking beyond keyword coverage |
| Hosted account/storage foundation | Production activation and end-to-end isolation checks |
| Reviewed application runner | Hosted execution, task tracking and secure approval handoff |
| Targets and application records | Role folders, saved searches, preferences and feedback |

These foundations exist in the repository; that does not mean every hosted feature has been activated or verified in production.

**The company catalogue is not a live vacancy feed.** Monitoring thousands of companies means discovering and maintaining their official career sources. Directory presence or a hiring flag must not be presented as proof of a current vacancy.

## 4. Recommended architecture

Keep the existing stack where practical:

```text
Official employer sources
          ↓
Scheduled ingestion workers
          ↓
Shared companies + offices + jobs database
          ├── Public map and search
          └── Private agent
                 ↓
          CV + preferences + role folders
                 ↓
          Ranked recommendations
                 ↓
          In-app/email notifications
                 ↓
          User-approved next actions
```

### Responsibilities

- **Vercel:** public interface and authenticated workspace.
- **Supabase:** accounts, private CV storage, database and owner-scoped access policies.
- **Hosted Python worker:** source collection, analysis and scheduled tasks.
- **Durable task queue:** retries, cancellation, duplicate prevention and visible task status.
- **Optional LLM:** interpret preferences and draft explanations/projects. Deterministic rules enforce eligibility, permissions and approval boundaries.

### Efficient execution

The agent should analyze new or changed jobs—not repeatedly process the whole internet for every user. Shared ingestion and cached analyses keep costs manageable.

Keep job identities and source history stable. Bind private analyses to the user, job content version, CV version and scoring version. Recompute when relevant inputs change. A failed source request must not mark all its vacancies closed.

The map and agent should share the same job records, so a role discovered on the map can be saved into a folder and analyzed without a second import or inconsistent vacancy status.

## 5. What autonomous should mean initially

| Automatic preparation | Requires approval |
| --- | --- |
| Job discovery and filtering | Sending a message |
| CV matching and explanations | Sharing a CV |
| Two-project suggestions | Submitting an application |
| Relevant opportunity notifications | Other external actions on the user's behalf |

Most value comes from finding a few genuinely relevant opportunities and explaining why they matter. A useful product does not need unrestricted browser automation.

Approval must cover the actual recipient, message, attachments or application values. Changes invalidate approval. An uncertain submission outcome must not cause a blind retry.

**70% must mean a defined evidence-coverage score**, not a 70% probability of being hired. Missing or unreadable CV evidence should produce uncertainty, not misleading precision. Exactly 70% is not below the threshold. Project proposals alone must not increase a match score; completed work needs evidence.

## 6. The hardest parts

### Job coverage and freshness

Identify sources, respect access rules and rate limits, remove closed jobs, avoid duplicates and make stale data visible. Broad company coverage does not automatically produce broad vacancy coverage.

### Recommendation quality

Seniority, work authorization, location and candidate intent matter more than shared keywords. Explain recommendations using job requirements and actual CV evidence. Treat unknown information explicitly.

### Reliable private execution

Implement tenant isolation, secure storage, retries, audit trails, notifications, cancellation and cost controls. Keep private CVs and contact data out of the public catalogue and GitHub snapshot pipeline.

### Employer relationships

Direct introductions like those advertised by Jack & Jill need an employer-facing product and participating recruiters. Generating a contact suggestion or an email draft is not equivalent to arranging an introduction.

LinkedIn sign-in does not grant unrestricted people-search or messaging permissions. Contact research and outreach must use supported sources/channels and preserve uncertainty about inferred email addresses.

### Geographic completeness

“All startups” is not a dataset whose completeness we can guarantee. Publish measured coverage and clear unknowns. A sourced HQ coordinate is not necessarily the workplace of a vacancy; an estimated city centre is not an exact office.

## 7. Recommended delivery sequence

### Phase 1: complete manual workflow

- Activate and verify hosted sign-in and private CV storage.
- Create role folders with explicit criteria and a selected CV version.
- Save companies and roles from the public map.
- Analyze selected roles and show evidence, gaps and uncertainty.
- Propose two grounded projects for usable below-threshold results.
- Prepare sourced contact suggestions and editable drafts, without sending.

### Phase 2: autonomous preparation

- Expand the reviewed employer-source registry.
- Add durable ingestion and per-folder scheduled analysis.
- Rank new or changed opportunities and collect feedback.
- Send opt-in daily shortlists with links to the private workspace.
- Add freshness monitoring, budgets, cancellation and failure alerts.

### Phase 3: reviewed execution

- Connect supported outbound channels with user authorization.
- Approve exact recipients/content and individual applications.
- Record actual outcomes and prevent duplicate submissions.
- Stop on CAPTCHA, ambiguous questions, restrictions or unsupported flows.

### Phase 4: coverage and employer participation

- Expand regions and role categories based on measured source quality.
- Improve office verification and map navigation.
- Evaluate recommendation usefulness with users.
- Build employer onboarding and mutual-interest introductions if demand supports it.

## 8. First experience to deliver

> Browse the map → save a role/company → create a folder → activate the agent → receive a daily shortlist → approve the next step.

Start with a well-covered region and role category, then expand. **Finish this connected workflow before adding voice conversations, mass outreach or employer-side recruiting agents.** It delivers both discovery modes without rebuilding everything.

### Minimum acceptance criteria

- A map role can be saved and analyzed in the same user's folder.
- User A cannot access user B's CV, preferences or analyses.
- Scheduled preparation runs without an open browser session.
- A new relevant job generates at most one notification per configured policy.
- Failed ingestion preserves known jobs with a stale indicator rather than falsely closing them.
- Every recommendation explains its evidence and important unknowns.
- Below-threshold project suggestions are grounded in learnable gaps.
- No message, CV share or employer submission occurs without the required approval.

## References

- [StartupMap](https://startupmap.one/): public geographic browsing inspiration.
- [Jack & Jill](https://www.jackandjill.ai/): public proactive discovery/introduction inspiration.
- [Hired app architecture and automation](APP_ARCHITECTURE_AND_AUTOMATION.md): current implementation, job ingestion, mapping providers, scoring, outreach and concrete blockers.
