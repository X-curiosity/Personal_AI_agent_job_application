# Whali-inspired Role-market direction

## Scope

This is a product direction and safety boundary, not a claim that every item below is already implemented. It reviews Whali's public [homepage](https://whali.com/) and [job-board documentation](https://whali.com/docs/job-board) for useful interaction patterns. We borrow the clarity of a role-first workflow—not its automated application or outreach model.

The product's north star is a candidate-controlled loop:

```text
Find an official opening → understand why it is relevant → prepare honestly →
apply on the employer's official site → practice for the interview
```

## What we adopt

| Product element | Current foundation | Direction |
|---|---|---|
| Official-board role feed | The Role market refreshes a small registered set of public employer boards and retains provenance. | Keep discovery bounded to permitted sources; show the supplied listing URL, provider, and retrieval time. |
| Transparent relevance | Ranking uses editable role aliases and local CV-skill overlap, with reasons shown beside a result. | Label it **Role relevance**, explain the matched terms/skills, and state that it is not a prediction of being hired. |
| Direct official application handoff | A result can open its supplied official listing and seed a local Job Workspace. | Make the two actions visually clear: **Open official application** and **Prepare this application**. The former leaves the product; the latter never submits anything. |
| Focused local preparation | A Job Workspace keeps the role-specific CV guidance, evidence review, proof projects, interview practice, and coaching history locally. | Keep preparation tied to one role and preserve the distinction between completed evidence and a proposed project. |
| Candidate-entered progress | The Role market has a local `saved`, `tracking`, and `hidden` shortlist that preserves a source snapshot across refreshes. None of those states means an application was sent. | Add a fuller, user-edited application timeline next; it should never infer that opening a listing or downloading a document means the person applied. |

Whali's public job-board materials also illustrate the value of showing a score explanation, filtering a role list, and handing a candidate to an employer's application page. Those interaction ideas are useful here; marketing claims or proprietary data coverage are not treated as product evidence. See [Whali's job-board documentation](https://whali.com/docs/job-board).

## Job-card design direction

The visual hierarchy can take inspiration from the compact listing layout in the supplied reference without copying its branding or inventing activity states:

```text
[AC]  Senior Data Engineer                                  Role relevance 82
      Acme Cloud · Zurich, Switzerland · Hybrid
      Official Greenhouse listing · retrieved 6 Oct
      Why it appears: “data engineer” alias + Python and SQL evidence

      [Open official application]  [Prepare this application]
```

- Use a generated company monogram rather than scraping or hotlinking company logos.
- Show location, workplace type, employment type, and source timestamp only when the source supplies them.
- Put the explanation and source provenance near the primary actions; full description and company facts can stay in an expandable details area.
- Do not show labels such as “actively reviewing,” “promoted,” or “easy apply” unless a permitted source provides that exact status and the product is authorized to display it. This product should call the action **Open official application**, not imply an in-product submission flow.
- Keep one compact relevance score, but explicitly state that it represents query/title and candidate-evidence overlap—not qualification, eligibility, interview odds, or hiring likelihood.

## What we deliberately do not adopt

The current product must not turn a candidate's profile into a volume-outreach engine. It will not:

- automatically submit applications, generate a claim-heavy CV/cover letter, or represent that a candidate applied;
- scrape LinkedIn or other social/professional sites for people, roles, private contact details, or employment histories;
- infer or label an individual's email address as verified, enrich person records, or construct a company score from historical hires or employee profiles;
- send bulk individualized email, run automatic follow-up sequences, use tracking pixels, or contact people without the candidate's specific approval;
- treat a relevance score, an opening, or a contact as proof that a candidate is qualified or will be interviewed.

Connection preparation can still be valuable, but only with candidate-supplied contacts or employer-published/authorized contact paths. The product can help prepare a factual draft after the candidate chooses the recipient; it must not find, guess, or message people on the candidate's behalf.

## Phased delivery

### Phase 1 — Trustworthy role feed and preparation

Continue improving the source-provenance cards, explicit official-listing handoff, local role preparation, and interview-practice loop. Keep refreshes user-triggered and make unavailable or unsourced facts visibly unknown.

### Phase 2 — Local application timeline

Extend the local shortlist with candidate-edited milestones such as `preparing`, `applied by me`, `interviewing`, `offer`, `rejected`, and `withdrawn`, plus dates and notes. Every status change should be explicit, locally stored, editable, and exportable/deletable. The product must not advance a status based on a click, a download, an email draft, or a calendar event.

### Phase 3 — Opt-in email and calendar connectors

Only after the local workflow is reliable, consider providers that the candidate explicitly connects. A safe connector design requires:

- least-privilege OAuth scopes, visible connected-account state, disconnect/revoke controls, and a clear retention policy;
- per-message recipient, subject, body, attachments, and send-time preview, followed by an explicit candidate approval for **each** send;
- draft assistance only by default—no mail merge, automatic sending, automatic reply classification, or automatic follow-up;
- a calendar view limited to user-approved interview events, with explicit confirmation before creating or changing an event;
- an auditable local activity record that says what action the candidate approved, without silently treating it as an application or interview outcome.

This keeps the useful "two ways in" idea as two candidate-controlled lanes: official application preparation today, and future consented communication preparation—not automated outreach.

## Success criteria

Measure whether people can identify a relevant opening, understand why it appears, reach the official application page, build an honest preparation plan, and record their own progress with fewer corrections. Do not use application volume, inferred contact reach, or interview outcomes as proof of product value without consented, carefully interpreted evidence.

## Sources

- [Whali homepage](https://whali.com/)
- [Whali job-board documentation](https://whali.com/docs/job-board)
- [Project European source strategy](EU_JOB_SOURCE_STRATEGY.md)
