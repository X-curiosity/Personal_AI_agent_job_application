# Co-Apply GPT Privacy Notice — Draft, not for publication

**This document is an implementation draft, not legal advice or a finished public privacy policy.** Complete every bracketed item and have the policy reviewed for the jurisdictions in which the service will operate before opening registration.

_Last updated: [date]_

## Who operates the service

Co-Apply GPT is operated by **[legal name / operator]**. Privacy contact: **[contact email or postal address]**. Data controller location: **[country / address]**.

## Information processed

If you create an account, the service processes your email address and authentication metadata. When you acknowledge this notice, the service records its published URL and version with a server-generated timestamp as an account-linked receipt. If you use the hosted workspace, it stores the CV files you upload, target-company names and optional website URLs, job titles and URLs you enter, your selected CV for each application, progress stages, and private notes.

The hosted preview parses CVs only for deterministic job comparison on the application server; it does not send hosted CVs or notes to an AI/model provider, submit applications, send messages, or import your local desktop application's SQLite data. Optional LinkedIn connection shares the requested OpenID identity attributes with LinkedIn and Supabase. A separate local rule-based runner fills supported forms without an AI model and sends the CV/answers to the employer only after explicit per-application approval. Public company catalogue facts are shared public research data; your saved targets and application workspace are private to your account.

## Purpose and legal basis

The service uses this information to authenticate you and provide the career-preparation workspace you request. **[Operator: specify and confirm the applicable legal bases and any additional purposes before publication.]**

## Service providers and locations

The planned application host is Render and the planned authentication, Postgres, and private-file provider is Supabase. Select and document the actual regions before launch: **[Render region]**, **[Supabase region]**. Their own privacy, security, subprocessors, backup, and retention terms also apply. **[Operator: list any other providers actually enabled, such as email delivery or future AI/model services.]**

## Access controls

The design uses authenticated sessions, owner-scoped database row-level security, a read-only account-linked Privacy Notice receipt, and a non-public CV bucket. Signed CV download links expire after five minutes. These safeguards reduce exposure but cannot guarantee absolute security. Do not upload documents you are not entitled to store.

## Retention and deletion

Your hosted workspace is intended to remain until you delete your account. Account deletion requires a fresh email one-time code and removes the account's CV objects and hosted records through a server-side deletion function. The code is used for reauthentication and is not stored by the application. Cross-service cleanup can fail partway; in that case, contact **[privacy contact]** for assistance. Provider backups may retain deleted data according to the provider's actual backup schedule: **[confirm and document provider retention period before publication]**.

You can request a ZIP export of saved targets, applications, and uploaded CV files from the Account & Privacy screen. **[Operator: add a process for requests the application cannot fulfill automatically.]**

## Your choices and rights

You may choose not to create an account or upload a CV. Depending on your location, you may have rights to access, correct, export, restrict, or delete personal data, or to complain to a regulator. Contact **[privacy contact]** to make a request. **[Operator: add applicable rights, response time, and supervisory authority before publication.]**

## Security incidents and contact

Report suspected account or privacy issues to **[security/privacy contact]**. **[Operator: document incident handling and applicable notification process.]**

## Changes

The operator will publish material updates here with a revised date and explain when additional data or providers are introduced.
