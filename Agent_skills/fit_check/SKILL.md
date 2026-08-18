---
name: fit-check
description: Evaluates a candidate's resume against a job description realistically and sincerely to determine if it is a good fit. Use this skill when asked to evaluate a job match, assess a candidate's fit, or compare a resume to a job description.
---

# Job Fit Check Skill

This skill provides instructions for sincerely and realistically evaluating how well a candidate's resume matches a job description.

## Objective

To provide an honest, evidence-based assessment of a candidate's fit for a specific role, highlighting both strong alignments and critical gaps without hallucinating or sugar-coating.

## Prerequisites

1.  **Candidate Resume / CV**: You need access to the user's latest resume or a detailed profile. If not provided, ask the user to provide it or point to a file in the workspace.
2.  **Job Description**: You need the text or URL of the job description.

## Evaluation Process

When asked to evaluate fit, follow these steps strictly:

### 1. Requirement Extraction
First, analyze the job description to extract:
*   **Must-Have Requirements**: Hard constraints like years of experience, specific degrees, mandatory languages, required visas/work authorizations, and core technical skills.
*   **Nice-to-Have / Preferred Qualifications**: Secondary skills or experiences that add value but aren't strictly required.
*   **Role Responsibilities**: What the candidate will actually be doing on a day-to-day basis.

### 2. Evidence Mapping
Compare the candidate's resume against the extracted requirements:
*   **Demonstrated Fit**: Match requirements to explicit evidence in the resume. Note *where* in the resume the evidence is found.
*   **Missing Evidence / Gaps**: Identify required or preferred skills that are *not* explicitly supported by the resume. Do not assume or hallucinate experience that isn't written down.
*   **Partial Match**: Identify areas where the candidate has adjacent or partial experience (e.g., knows Python but the job asks for Java).

### 3. Realistic Assessment (The "Sincere Fit" Check)
Provide a grounded, objective evaluation:
*   **Hard Constraints Check**: Did the candidate pass all non-negotiable requirements? If they miss a fundamental must-have (e.g., requires 10 years experience, candidate has 1; requires active security clearance, candidate lacks it), state clearly that they are unlikely to be a fit.
*   **Competitiveness**: Evaluate how competitive the candidate is for this role. Are they a strong match, an underdog, or unqualified? Be sincere and realistic. Don't be overly optimistic if the gaps are significant.

## Output Format

Present your evaluation to the user in a clear, structured format (using markdown or an artifact):

1.  **Bottom-Line Verdict**: A one-paragraph summary stating realistically whether the candidate is a Strong Fit, Potential Fit, Stretch/Underdog, or Not a Fit, and why.
2.  **Hard Filters (Pass/Fail)**: A quick rundown of non-negotiable requirements.
3.  **Strongest Alignments**: Bullet points linking the candidate's achievements directly to the job's core needs.
4.  **Critical Gaps**: Honest identification of missing skills or experience.
5.  **Recommendation**: Should the user apply? If so, what should they highlight in their cover letter or portfolio to mitigate the gaps?

## Crucial Directives

*   **Be Honest**: If it's a bad fit, say so respectfully but firmly. Time is valuable; applying to jobs where there is zero chance of success is inefficient.
*   **No Hallucinations**: Never invent experience for the candidate to make them look better.
*   **Evidence-Based**: Always tie your claims back to specific text in the resume or job description.
