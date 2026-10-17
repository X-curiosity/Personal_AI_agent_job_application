# Jev (decision model) — evaluation notes for Co-Apply GPT

Status: **the local decision model is implemented and in use (advisory); the
Jev hosted model is implemented but off unless you configure it**. Written
2026-10-17, updated the same day after implementation.

- `src/tau_job_application/skill_decision.py` — deterministic local decision
  model for skill equivalence (typed output: probability + match/no_match/
  ambiguous + reason). No network, no dependency.
- `src/tau_job_application/jev_client.py` — optional Jev escalation for the
  ambiguous band only, with SQLite caching and strict fallback.
- UI: **Overview → "Advisory: decision-model skill matching"**. Shows canonical
  coverage, decision-model coverage, ambiguous pairs, and every decision with
  its reason. The canonical match score is unchanged and remains the number the
  product calls "your match".
- No API key is configured in this repository. The Jev checkbox is disabled
  until both `JEV_API_KEY` and `JEV_API_URL` are set.

## What Jev is

Jev is TypeSafe AI's "System One" model — a **decision model, not a chatbot or
LLM**. You send it a piece of application state and it returns a typed judgment
your code can branch on:

- **choice** — e.g. `route: billing — 0.98`
- **score** — e.g. `urgency: 1.4 / 4`
- **yes/no probability** — e.g. `escalate: no — 0.12`

Facts (from public sources, verify before implementing):

- Hosted API public since 21 Sep 2026, API-key auth, no waitlist.
- Pricing: **$0.042 per 1M input tokens; output free**. Playground allows 10k
  input tokens without signup.
- Exact request/response schema is not published in the pages reviewed; take it
  from the official docs (thejevai.com/models) at implementation time.
- The vendor's own caveat: "Model judgment, not a guarantee. Review the result
  before using it to trigger an action."

## Why it is interesting for this project specifically

Co-Apply GPT's standing rule is **no model-based canonical state**: match
scores, eligibility, persistence, and status transitions stay deterministic.
That rule killed general chat-LLM integrations, because a chat model's free
text cannot be branched on safely. Jev is different in kind, not degree: its
outputs are typed primitives designed to be consumed by code, which makes it
the first model that could fit inside the rules — **if** it is used only where
a deterministic fallback already exists.

## Hard rules for any integration

1. **Advisory only, never canonical.** Jev output may order, flag, or annotate.
   It must never write a match score, an eligibility verdict, an application
   status, or a submission decision. Those stay deterministic and human-owned.
2. **Off by default, opt-in per feature.** Any Jev call sends data to a hosted
   third-party API. That is an egress decision the user makes explicitly, like
   the remote-logo checkbox.
3. **Deterministic fallback always.** No `JEV_API_KEY`, a timeout, or a bad
   response must degrade to today's pure-Python behavior silently and safely.
4. **No candidate PII.** Never send CV text, profile data, account details, or
   email content. Job-advert text only (it is already public data).
5. **No Gmail reply classification.** Email content egress conflicts with the
   exact-thread consent model. Out of scope unless a separate, explicit consent
   flow is designed.
6. **Bounded and cached.** 12 s timeout, response-size cap, and results cached
   in SQLite keyed by advert fingerprint so a refresh never re-pays for an
   unchanged advert.
7. **No new dependency.** Stdlib `urllib` client in the style of
   `accounts._https_json` (fixed host, no redirects, bounded read).

## Candidate use cases, ranked

### 1. Period classification for openings — best first candidate
`role_discovery.opening_matches_period` is a documented heuristic: the test
suite knowingly accepts that "Java Developer — we use the Spring framework"
matches the **Spring** season filter. A yes/no Jev call
("Is this advert for a {season} {year} position?") over the advert title +
description would remove that class of false positive. Heuristic stays as the
fallback; Jev only *vets* heuristic matches.

### 2. Work-area taxonomy mapping
Map arbitrary opening titles into the 12-field taxonomy used by role pages, so
the Startups/Big companies feeds group roles more accurately than title-terms
alone. Choice primitive; fallback is today's keyword mapping.

### 3. Triage for the future approval queue
When automated prospecting lands, a yes/no "does this opening plausibly belong
to the saved role query?" could pre-flag likely mismatches for faster human
review of the approval queue. Deterministic ranking stays primary; Jev only
annotates.

### 4. Application-package second opinion (later, careful)
A yes/no "does this bullet assert something not present in the supplied
evidence?" as an *advisory flag* beside the deterministic authenticity report.
Never a block by itself.

### Explicitly not recommended
Match scoring, work-eligibility decisions, reply classification, submission
gates, CV rewriting. Each is either canonical (rule 1), PII-bearing (rule 4/5),
or a human decision by design.

## Cost reality check

A period check is roughly 300–600 input tokens. At $0.042/1M tokens, checking
500 openings costs about **$0.01**. Cost is a non-issue; privacy and fallback
discipline are the real constraints.

## Minimal implementation sketch (when approved)

Implemented as described; the live shape is:

```python
# src/tau_job_application/skill_decision.py (local, deterministic, always on)
decide_skill_match("Kubernetes", "k8s")      # -> probability 0.95, "match", "alias"
decide_skill_match("Java", "JavaScript")      # -> held below threshold, never a match
refine_requirement_matches(cv_skills, requirements)  # advisory re-score, canonical weighting
```

```python
# src/tau_job_application/jev_client.py (opt-in, ambiguous pairs only)
jev_skill_probability(left, right, database_path=...)  # -> float | None (None = keep local)
```

Call-site pattern in the UI:

```python
resolver = jev_resolver(WORKSPACES.path) if (use_jev and jev_available()) else None
refinement = refine_requirement_matches(candidate.skills, requirements, resolver=resolver)
# advisory metrics only; result.match.score is never overwritten
```

Tests: `tests/test_skill_decision.py` (verdicts, false-positive guards, weighting),
`tests/test_jev_client.py` (opt-in gate, cache, clamping, malformed answers, no
redirects, payload contains only the two labels), `tests/test_skill_decision_ui.py`
(canonical score unchanged, advisory metrics render, Jev disabled without keys).

## Observed effect

On a CV containing `k8s, Python` against a role requiring `Kubernetes, Python`:
canonical coverage **60%** (exact spelling only), decision-model coverage
**100%** (alias equivalence recognised), 0 ambiguous pairs. Nothing about the
canonical number or its UI changed.

