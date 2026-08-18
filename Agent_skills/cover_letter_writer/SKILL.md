---
name: cover-letter-writer
description: >
  Generates a tailored, one-page, evidence-backed cover letter for a specific
  job posting. Follows Rotman Commerce Career Services structural guidelines.
  Relies exclusively on facts already present in the candidate's resume or
  verified by the user. Never invents experience, metrics, or qualifications.
  Use after running fit-check so gaps are known before drafting begins.
---

# Cover Letter Writer Skill

This skill produces a professional, targeted cover letter grounded in the
candidate's **verified evidence**. Every claim in the letter must trace back
to either the candidate's resume or information explicitly supplied by the user.
This is the final application-drafting step and builds on the output of the
`fit-check` and (optionally) `resume-tailor` skills.

---

## Prerequisites

Before drafting, gather all four inputs. If any is missing, ask the user to
provide it before proceeding.

1. **Candidate Resume / CV** — The full resume text or `.docx` file. This is the
   exclusive source of facts about the candidate. Do not accept verbal summaries
   alone; always read the source document.

2. **Job Description** — The full text (pasted or URL). Extract from it:
   - The **top 3 core employer needs** (skills, responsibilities, or traits the
     role emphasizes most).
   - Exact terminology and keywords used by the employer.
   - The hiring manager's name and full employer address block, if visible.

3. **Fit-Check Output (recommended)** — The structured gap/alignment analysis
   from the `fit-check` skill. This tells the agent which candidate strengths
   to foreground and which gaps to acknowledge honestly or reframe. If not
   available, perform a lightweight evidence-mapping pass before drafting.

4. **Candidate preferences (optional)** — Any networking contacts, company
   events attended, preferred tone, or specific achievements the candidate
   explicitly wants to include.

---

## Evidence Extraction (Mandatory Pre-Draft Step)

Before writing a single sentence, build an **evidence inventory**:

| Employer need (from JD) | Matching candidate evidence (from resume) | Evidence strength |
|---|---|---|
| e.g. "Python data pipelines" | "Built ETL pipeline processing 50k rows/day – Q3 2024" | Strong |
| e.g. "cross-functional stakeholder management" | "Collaborated with product and legal teams on…" | Partial |
| e.g. "CFA Level I" | _Not found in resume_ | **MISSING** |

- **Strong**: explicit, specific, quantified evidence exists in the resume.
- **Partial**: adjacent or transferable experience — label it as such in the draft.
- **Missing**: do **not** write this claim. Leave a `[GAP – user to confirm or omit]`
  placeholder if the employer need is critical.

---

## Cover Letter Structure (Rotman Commerce Standard)

### General Formatting
- **Length**: Strictly **one page**. Do not create dense or cramped layouts.
  Use margins of at least 1 inch. Prefer white space over cramming.
- **Tone**: Confident but not arrogant. Enthusiastic and professional.
- **Language**: Use strong action verbs. Vary sentence structure.
  Do **not** start every sentence with "I".
  Mirror exact terminology from the job description wherever evidence supports it.
- **Output**: Generate a fully formatted `.docx` file using `python-docx`,
  matching the candidate's resume masthead layout. See Generation section below.

---

### Section 1 — Header

```
[Candidate Name]                   [Phone] | [Email] | [LinkedIn URL]

[Date — spelled out, e.g. "August 18, 2026"]

[Recipient Name, if known]
[Recipient Title]
[Organization Name]
[Street Address, City, Country]

RE: [Job Title] Posting[, Position ID XXXX if shown in JD]

Dear [Recipient Name], / Dear Hiring Manager, / Dear Hiring Committee,
```

If the recipient name is not in the job description, use "Dear Hiring Manager,".

---

### Section 2 — Opening Paragraph (Hook, ~3–5 sentences)

Include **all three** of the following:

1. **Qualification hook**: A single, specific sentence naming the candidate's
   most relevant credential or achievement that directly matches the role's
   top need. Must reference an evidence-inventory item.
2. **Genuine interest**: Why *this* role at *this* company — not a generic
   statement. Reference one concrete fact about the organization (mission,
   recent product, initiative, or culture element found in public sources or
   the JD). Ask the user for this if not available.
3. **Personality signal**: A brief, authentic sentence that conveys enthusiasm
   or a personal connection to the field.

**Do not** invent networking contacts or events the candidate did not attend.
If the candidate mentioned one, ask them to confirm before including it.

---

### Section 3 — Body Paragraphs (2–3 paragraphs maximum)

Each body paragraph must:
- Open with a **topic sentence** linking the candidate's demonstrated strength
  to a specific employer need.
- Include **at least one concrete example** per paragraph: a project, result,
  metric, or responsibility sourced from the evidence inventory (Strong or
  Partial only).
- Close with a **value-forward statement**: what the candidate will *contribute*
  to the organization — not what they will gain.
- Reference the company's mission, culture, or specific initiative at least
  once across the body paragraphs to show genuine research.

**Paragraph guidance by evidence strength:**
- **Strong evidence** → State the fact directly and confidently.
- **Partial evidence** → Phrase as a transferable skill: _"My experience with X
  has given me a strong foundation for Y…"_
- **Missing evidence** → Do **not** write the claim. Insert
  `[GAP – confirm with user or omit]` and flag it in the summary of changes.

---

### Section 4 — Closing Paragraph (~3 sentences)

1. Reiterate one key specific contribution the candidate will make.
2. Thank the employer for their time and consideration.
3. Express a clear desire to discuss suitability further in an interview.

**Sign-off**:
```
Sincerely,

[Candidate Full Name]
```

---

## Generation — `.docx` Output

Write a **custom Python script** using `python-docx` that builds the file from
scratch. Do **not** attempt to regex-replace content inside an existing complex
`.docx` template; this breaks formatting.

**Formatting specifications:**
- Font: Times New Roman or Arial, 11pt body, 12pt name in masthead.
- Margins: 1 inch (72 pt) on all sides.
- Masthead: Mirror the candidate's resume header exactly (name, phone, email,
  LinkedIn). Use a thin horizontal rule beneath it.
- Date, employer block, subject line, greeting: plain 11pt, left-aligned.
- Paragraphs: 1.15x line spacing, 6pt space after each paragraph.
- Sign-off: "Sincerely," on its own line, 3 blank lines, then candidate name.
- Save the file as: `Cover_Letter_[CompanyName]_[JobTitle].docx`
  (spaces replaced with underscores) in the project workspace.

**Word-count pre-check (before generating the `.docx`):**
- Count the words in the plain-text draft. Aim for **250–400 words** of body
  content (excluding the header/address block). If the draft exceeds 400 words,
  trim body paragraphs before generating the file — do not rely on formatting
  tricks to force-fit an overlong letter.

**Iterative page-length verification (MANDATORY):**
- `python-docx` **cannot** detect page breaks or page count natively.
- After generating the `.docx` file, you **MUST** ask the user:
  *"Does the cover letter fit on exactly one page?"*
- If the user reports it exceeds one page, apply fixes **in this order**:
  1. Cut the weakest body paragraph or trim sentences with the least evidence.
  2. Reduce paragraph spacing from 6pt to 3pt.
  3. Reduce font size from 11pt to 10.5pt (never go below 10pt).
  4. Reduce margins from 1 inch to 0.75 inch (never go below 0.5 inch).
- Regenerate the `.docx` and ask again.
- **Repeat until the user confirms it fits exactly one page.**
- Do **not** finalize or deliver the `.docx` until the user confirms.

---

## Output to User

After generating the file, deliver the following:

1. **Evidence Inventory Table** — the full mapping from the pre-draft step,
   so the user can verify which claims are supported.
2. **Gap Report** — a concise list of employer needs that had **no** supporting
   evidence in the resume, with a note for the user to either provide evidence
   or accept the omission.
3. **Letter Draft (text)** — the full cover letter as plain text for review
   *before* the `.docx` is written, so the user can request edits.
4. **Generated `.docx` file** — only after the user approves the draft text.
5. **Fact-Check Statement** — confirm that every claim in the final letter
   traces back to a specific resume entry or a user-supplied fact, and that
   no experience, metrics, or qualifications were invented.

---

## Crucial Directives

- **Evidence-first, always**: Do not draft a single claim that cannot be
  pointed to in the candidate's resume or user-confirmed preference.
- **No hallucinations**: Never invent metrics, project names, technologies,
  outcomes, or qualifications. If you are uncertain whether something is in
  the resume, cite the exact line or ask the user.
- **One page, no exceptions**: A cover letter that runs over one page is worse
  than a shorter one. Cut body paragraphs or trim sentences before expanding
  margins or shrinking font below 10.5pt.
- **Human review before export**: Show the draft text and evidence inventory
  to the user and receive explicit approval before writing the `.docx` file.
- **Gap acknowledgment over invention**: A gap placeholder `[GAP – user to
  confirm or omit]` is always preferable to an invented claim.
- **Mirror the JD's language**: Use the employer's exact phrasing for skills
  and role titles wherever it is truthfully supported by evidence.
