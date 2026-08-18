---
name: resume-tailor
description: Adapts and tailors a candidate's resume to match a specific job description without inventing or hallucinating facts. It strictly adheres to Harvard College resume guidelines and uses a specific user-provided .docx template as a base.
---

# Resume Tailor Skill

This skill provides instructions for optimizing and tailoring a candidate's resume to a specific job description, adhering strictly to evidence-based facts and following Harvard College's resume best practices. It manipulates a specific Microsoft Word (.docx) template provided by the user.

## Objective

To strategically rephrase, reorder, and highlight existing experience in a candidate's resume so it aligns perfectly with the target job's requirements, all without fabricating any information, while formatting it into a professional .docx template.

## Prerequisites

1.  **Candidate's Base Resume**: Provided by the user, ideally in `.docx` format, or text/markdown.
2.  **Job Description**: The target role the candidate is applying for.
3.  **Resume Template (.docx)**: A specific Word document template provided by the user that will be used as the base for the final tailored resume.

## Harvard Resume Guidelines

When tailoring bullet points and content, strictly follow these Harvard College rules:
*   **Be specific** rather than general.
*   **Use active language** rather than passive.
*   **Write to express**, not impress. Be articulate rather than "flowery".
*   **Be fact-based**: Quantify and qualify results where possible.
*   **Scannability**: Write for people who or systems that scan quickly.
*   **DO NOT** use personal pronouns (such as I or We).
*   **DO NOT** abbreviate, use narrative style, or use slang/colloquialisms.
*   **DO** list headings in order of importance, and within headings, list information in reverse chronological order (most recent first).
*   **DO** be consistent in format and content.

## Process

When asked to tailor a resume, follow these steps strictly:

### 1. Analyze the Job Description
*   Extract the core requirements, keywords, and primary responsibilities of the role.

### 2. Fact-Based Tailoring (No Hallucinations)
*   **Rephrasing**: Rewrite existing bullet points to incorporate keywords from the job description *only if* the original meaning supports it. Follow the Harvard Guidelines (active, specific, fact-based, no personal pronouns).
*   **Reordering**: Move the most relevant experiences, skills, and bullet points to the top of their respective sections.
*   **Highlighting**: Emphasize accomplishments that directly prove the candidate can handle the target role's responsibilities.
*   **Pruning**: Remove or condense irrelevant experience to save space and maintain focus.
*   **Strict Rule**: **DO NOT INVENT** metrics, job titles, technologies used, or responsibilities. Every claim must trace back to the original resume.

### 3. The Process

1. **Information Extraction**:
   - Extract the core skills and requirements from the target Job Description.
   - Read the candidate's base resume (e.g., using `python-docx` if `.docx`).

2. **Harvard Bullet Re-writing**:
   - Map the candidate's existing experience to the required skills.
   - Re-write each bullet point following the strict Harvard rules above. Do NOT hallucinate.

3. **From-Scratch Programmatic Generation (MUST FIT 1 PAGE)**:
   - **CRITICAL**: Resumes MUST never exceed 1 page.
   - **CRITICAL**: Do NOT try to modify complex `.docx` templates using `replace` text, as this breaks formatting (tabs, indents, bullets).
   - Write a custom Python script using `python-docx` that generates a brand-new, flawlessly formatted document from scratch using Investment Banking standards:
     - Font size: Start with 10pt (Times New Roman or Arial).
     - Narrow margins (0.5 inches).
     - Bold section headers with bottom borders (underlines).
     - Top line of each experience (Company/School) must be Bold and ALL CAPS.
     - Second line of each experience (Position/Degree and Dates) must be Italicized.
     - ALL months must be spelled out fully (e.g. "August" instead of "Aug").
     - Add 2-3pt spacing between experiences so the page feels full.
     - Perfectly right-aligned dates/locations using paragraph tab stops.
     - Include a tailored 2-3 sentence PROFILE at the top.
    - **Iterative Length Verification (MANDATORY)**:
      - `python-docx` **cannot** detect page breaks or page count natively.
      - After generating the `.docx` file, you **MUST** ask the user:
        *"Does the resume fit on exactly one page?"*
      - If the user reports it exceeds one page, apply fixes **in this order**:
        1. Prune the weakest or least-relevant bullet points.
        2. Reduce spacing between experiences from 2-3pt to 0pt.
        3. Reduce font size from 10pt to 9.5pt (never go below 9pt).
        4. Reduce margins from 0.5 inches to 0.4 inches (never go below 0.3 inches).
      - Regenerate the `.docx` and ask again.
      - **Repeat until the user confirms it fits exactly one page.**
      - Do **not** finalize or deliver the `.docx` until the user confirms.
    - Save the finalized document directly for the user.

## Output Format

1.  **Summary of Changes**: A brief list of what was highlighted, what keywords were added, and what was removed.
2.  **New Resume Content**: A newly generated `.docx` file based on the provided template, or tailored markdown text if programmatic insertion fails.
3.  **Fact-Check Guarantee**: A statement confirming that no new facts were invented during the tailoring process and that Harvard guidelines were followed.
