# Jobright comparison and prioritized improvement report

## Scope and evidence

Reviewed Jobright's public homepage, <https://jobright.ai/>, against the repository at commit `e4ff76a`. This is a product comparison and implementation plan, not a claim that the proposed features have shipped.

The homepage advertises personalized job matches and early alerts, application autofill, job-specific résumés, insider referrals, and a career copilot. Its claims about interview increases, time saved, job volume, ATS success, and generation speed are **vendor marketing claims, not independently verified benchmarks**. No account-based product trial, European coverage audit, or review of Jobright's internal technology was performed. Features absent from the homepage should not be assumed absent from its product.

Local verification: `uv run --no-sync pytest -q` passed all 14 existing tests. Two additional diagnostic executions reproduced scoring and evidence-review weaknesses described below. Passing those tests does not establish production readiness or live API compatibility.

## Recommendation

Borrow Jobright's integrated workflow, not its volume claims. Our proposed focus is:

> Help European students discover suitable roles, understand why they fit, build missing evidence through projects, and prepare a reviewed application.

The learning-to-project-to-application loop is our intended differentiator; it is not yet a validated competitive advantage. Prioritize an end-to-end, trustworthy workflow over more source adapters or mass application automation.

## Feature comparison

| Jobright homepage advertises | Current repository actually does | Recommended improvement |
|---|---|---|
| Personalized job matches | Compares one CV with one job using a small skill alias table; discovery results are separate from assessment | Saved candidate preferences and a ranked shortlist with evidence and eligibility constraints |
| Large job hub and early alerts | Company-board connectors, imports, and manual SQLite snapshots | Reliable source ingestion, stable identities, completeness checks, and opt-in saved-search digests |
| Job-specific tailored résumé | `career.py` produces a summary, skill list, and template editing advice; download is a planning report | Editable full résumé, original-versus-draft comparison, claim references, PDF/DOCX export |
| Insider referrals | Manual search queries and imported contacts; no relationship graph or verified alumni matching | User-authorized alumni/team connections with sourced relationship explanations and reviewable outreach drafts |
| Career copilot | Optional Tau CLI agent; Streamlit uses deterministic functions, not a conversational copilot | In-app assistant grounded in the selected profile, role, evidence, and project progress |
| Application autofill | No autofill or submission functionality | First add an application tracker and reusable reviewed answers; evaluate user-controlled autofill later |

## P0 — Correctness before additional features

### 1. Replace authenticity verdicts with explicit claim review

**Observed:** `authenticity.py` treats shared keywords as support and skips unsupported-claim checks for sentences containing numbers. A diagnostic CV containing “Managed 200 hospitals worldwide.” returned `ready` without supporting evidence. Generic wording also drives `_looks_ai_polished`, although style does not establish authorship. The checker reviews the source CV rather than the final tailored document.

**Change:** Separate wording suggestions from factual provenance. Represent claims explicitly with source spans, evidence IDs, and states such as self-reported, supported, and needs confirmation. Review the final draft against the approved source profile. Do not treat numbers, keyword overlap, or stylistic polish as proof. AI-assistance disclosure should reflect the user's declaration or actual workflow, not a style guess.

**Acceptance:** Adding a number or a known skill cannot verify a new achievement. A new employer, metric, qualification, or project in a generated draft requires supporting evidence. “No issues found” explicitly does not mean “truth verified.” Allow downloading diagnostic reports while gating a finalized application document on its own review state.

### 2. Fix scoring and profile confirmation

**Observed:** `matching.py` assigns an absent preferred-skills list full credit. A candidate with Python and a job requiring only Rust receives 20/100 despite matching no requirements. `unit testing` is aliased to `pytest`, which incorrectly equates a general practice with a particular tool. `parsing.py` marks an explicit `Skills:` list confirmed without a separate user review, but ordinary CV keyword mentions remain unconfirmed. The UI has no structured confirmation editor.

**Change:** Normalize weights over requirement groups that exist. Replace false aliases; distinguish self-reported skills from evidence-backed proficiency and unknown information. Add profile/requirement correction and confirmation before scoring. Keep readiness scores distinct from hiring probabilities.

**Acceptance:** No matched requirements means zero coverage. “Unit testing” does not prove pytest experience. Equivalent CV wording gives consistent results after confirmation. Unknown information remains visible rather than becoming an automatic pass or a claimed lack of ability.

### 3. Validate source adapters before scaling coverage

**Observed:** `sources.py` silently drops jobs that cannot be parsed. Structured locations are not consistently retained. Recruitee reads one assumed nested shape; SmartRecruiters reads descriptions directly from listing records without a detail-fetch stage. Current tests do not validate those adapters against representative provider responses. These are risks to verify against current official schemas, not confirmed live-provider failure reports.

**Change:** Add captured or representative contract fixtures for each provider, explicit field mapping, HTML normalization, supported pagination/detail retrieval, completeness flags, and visible skipped-record reasons. Revalidate redirects, limit response size, handle rate-limit responses, and redact errors.

**Acceptance:** A successful empty board, a parser failure, partial pagination, and an API outage are distinguishable. Each retained job has a provider ID/source URL, capture timestamp, title, company, and location when supplied. Test populated, empty, malformed, paginated, and rate-limited responses.

## P1 — Deliver the complete application workflow

### 4. Europe-aware ranked shortlist

Add preferences for countries/cities, relocation, remote-work country restrictions, work authorization/sponsorship, language proficiency, seniority, internships, and salary currency/pay period. Keep these user-entered; do not infer legal eligibility from a person's name or profile.

Rank multiple jobs with separate eligibility states and skill-coverage explanations. Let users choose “apply now,” “review constraints,” or “build evidence first.” Selecting a discovered job should populate the existing assessment directly, without copying text between tabs.

**Acceptance:** A high skill match cannot conceal a known hard-constraint mismatch. Missing sponsorship information displays “unknown.” At least ten varied European role fixtures exercise ranking, languages, and constraints; user labels evaluate shortlist usefulness.

### 5. Real résumé editor and export

Create structured education, experience, projects, skills, and contact sections. Retain the original. Show a side-by-side diff, let candidates accept/reject each change, and flag unsupported additions. Produce a single-column PDF/DOCX with selectable text, links, and predictable section order. Record the version and review state used for each application.

**Acceptance:** Upload → confirm profile → choose job → edit draft → approve → download works end to end. Export text can be extracted back in the intended reading order. No invented credentials or numeric outcomes appear. Call these checks “parseability checks,” not a guarantee to pass every ATS.

### 6. Application workspace and progress tracking

Persist saved roles, CV versions, statuses (saved, preparing, applied, interviewing, offer, rejected, withdrawn), dates, notes, and follow-up reminders. Users record actual submissions; the app must not infer that downloading a CV means applying.

**Acceptance:** Restarting the UI restores the workspace. Updates retain history. A user can delete/export their local records. Editing inputs marks previous results stale until recalculated.

## P2 — Strengthen the learning and networking differentiation

### 7. An actual dependency roadmap

`planning.py` currently uses a small static resource catalog and generic project templates. The UI shows expanders rather than a graph. Add explicit prerequisite edges and cycle checks, weekly time budgets, completion states, resource metadata, and deliverables tied to target-role requirements.

With permission, inspect selected GitHub repository READMEs/tests rather than relying only on primary-language labels. Research company-relevant project ideas with citations and distinguish proposals from completed evidence. No stars/language label alone proves proficiency or ownership.

**Acceptance:** Each project identifies its target gap, prerequisites, deliverables, and observable completion criteria. Completed work affects the profile only after candidate review. The graph remains acyclic and the plan fits the declared budget.

### 8. Evidence-backed networking

Use authorized imports and public professional sources to identify relevant team members and user-confirmed shared affiliations. Attach a source and observation date to roles and relationships. Prepare contextual outreach drafts but leave sending to the candidate.

`career.py` currently calls a manually entered contact “verified” based on the presence of a URL/email; change that to “needs review.” Remove guessed company domains from research queries or request the actual domain.

**Acceptance:** No contact, company affiliation, shared school, or individual email is fabricated. A syntactically valid address is not treated as independently verified.

### 9. Career copilot and interview learning loop

Expose the bounded Tau assistant in the UI with explicit consent for the data sent to the model. Give it the approved profile and selected role, not unrestricted local files. Separate answer structure, technical accuracy, and evidence quality in interview feedback; the existing `interview.py` feedback is keyword-based structure checking only.

**Acceptance:** Questions adapt to confirmed weaknesses and previous answers. References support technical corrections. Audio submission requires an explicit action, transcripts stay attached to their question, and credential/recording deletion is supported.

### 10. Freshness-aware saved-search alerts

`monitoring.py` fingerprints URL, title, company, and requirements together: changing requirements can make an old role appear new. It does not distinguish updates or confirmed closures.

Use provider job IDs/canonical URLs for identity and a separate content hash for versions. Track first seen, last seen, updated, and source-confirmed closure. Never mark a role closed because a request failed or a partial response omitted it. Add user-configured scheduling only after provider limits and permissions are checked, with cadence, pause, and notification controls.

**Acceptance:** An edit produces “updated,” not “new.” Repeated identical refreshes create no alerts. Failed/partial fetches cannot close jobs. Funding or product announcements remain hiring signals, not proof of a vacancy.

## Privacy and operational prerequisites

- Streamlit password inputs can persist in server-side session memory across reruns: the current “one-time only” wording is too strong. The code does not deliberately write tokens to SQLite, but that is not equivalent to immediate memory deletion. Add clear controls and test log/error redaction.
- Add retention/deletion controls for CVs, job snapshots, imported contacts, transcripts, and audit metadata before serving multiple users.
- The local prototype has no multi-user authentication or isolation. Do not expose it publicly as a hosted product without access controls and isolation testing.
- Avoid blanket claims such as “all claims verified,” “no fake jobs,” or “guaranteed ATS success.” Describe the checks actually performed and their uncertainty.

## Suggested implementation sequence

1. **Correctness release:** claim review, confirmation editor, scoring corrections, adapter contract tests.
2. **Usable application release:** shortlist → select role → full editable résumé → reviewed export → application tracker.
3. **Learning release:** dependency graph, company-specific project research, completion evidence, adaptive practice.
4. **Discovery release:** relationship-based networking, validated source expansion, opt-in freshness-aware alerts.

Do not start with bulk autofill. It does not address the current bottlenecks: trustworthy profile extraction, complete résumé output, and a connected application workflow.

## Evaluation and release criteria

Expand the existing synthetic suite with multilingual CV/job fixtures, adversarial unsupported claims, provider contract fixtures, and Streamlit interaction tests. Use synthetic or explicitly consented documents only.

Measure parsing corrections needed, supported-draft-claim coverage, shortlist usefulness, duplicate/update accuracy, export readability, time to a reviewed application, and completed project evidence. Track interview outcomes only with consent and do not attribute causality without evidence.

This report and its README link are documentation changes only. The features and fixes above remain a proposed backlog; no live integrations were exercised, no credentials were submitted, and no product code was changed during this review.
