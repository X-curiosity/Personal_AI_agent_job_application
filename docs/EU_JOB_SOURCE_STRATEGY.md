# European job-source strategy

## Product rule

A job source enters the product only when the data path is one of:

1. a documented public career-board API/feed;
2. an official API used with the employer's or user's authorized token; or
3. a CSV/JSON export supplied by the user who obtained it lawfully.

The application does not scrape LinkedIn, Indeed, Glassdoor, ZipRecruiter, XING, StepStone, or any other aggregator. It does not bypass access controls, browser automation, or robots restrictions.

## Implemented source adapters

| Source | Europe relevance | Access model | Status | Monitoring |
|---|---|---|---|---|
| Greenhouse | Widely used by EU/international startups | Official public Job Board API, board token | Implemented | User refresh snapshots results |
| Lever | Widely used by EU/international startups | Public postings API, site handle | Implemented | User refresh snapshots results |
| Recruitee | EU-founded ATS with European employer coverage | Documented unauthenticated Careers Site API, company slug | Implemented | User refresh snapshots results |
| SmartRecruiters | Strong EU enterprise presence | Official Posting API, company-provided `X-SmartToken` | Implemented | User refresh snapshots results |
| X | Useful hiring/funding/product signals | Official API v2 recent search, user token | Implemented as signals, not a job-board adapter | Manual API request only |
| LinkedIn | Important profile/reference source | Official OIDC identity endpoint for connected user | Implemented only as authorization check | No profile search or scraping |
| User-provided export | Any European market | CSV/JSON, user-owned/licensed data | Implemented | Imported data remains reviewable |

## Deferred / partnership-only sources

- **EURES:** Europe-wide and strategically valuable, but the publicly discoverable API material is not a stable, supported product integration contract. Add only after written API/access confirmation from EURES or a licensed partner.
- **Welcome to the Jungle:** Use its recruiter/customer API only under an appropriate customer or partnership agreement.
- **XING:** Its recruiting API requires a customer agreement and OAuth. Add when a customer credential and permitted use case exist.
- **StepStone:** Its documented XML integrations are employer feed workflows, not an open job-search API. Add under a commercial/feed agreement.
- **National public employment services** (for example France Travail, Bundesagentur für Arbeit, VDAB): evaluate country by country, using their current official developer agreement, rate limits, allowed redistribution, and language/location coverage before enabling an adapter.

## Monitoring design

Monitoring is deliberately **user-triggered**, not a hidden cron crawler:

1. The user chooses a permitted source and identifier.
2. The source adapter retrieves its current published jobs.
3. `JobMonitor` fingerprints each role from canonical URL (when present), title, company, and requirements.
4. A local SQLite registry records first/last seen timestamps and reports roles newly seen on the current refresh.
5. Tokens are never stored. The registry stores source identifiers and job snapshots only.

This gives the user an auditable “new since my last check” workflow without creating an autonomous collection system. Scheduled polling should be added only for a source whose written terms and API quota expressly allow it, after the user configures cadence, region, retention, and notification preferences.

## Evaluation checklist for each new European source

- Official documentation and current terms reviewed.
- Explicit permission for the intended search, retrieval, local storage, and display use.
- Geographic and language coverage recorded.
- Authentication, rate limits, pagination, and error behavior tested with a fixture.
- Source URL, retrieval time, and raw requirement wording retained as provenance.
- One source adapter cannot access arbitrary URLs or internal network addresses.
- Job fingerprint/deduplication and closed-role behavior tested.
- A user approves any scheduled refresh or external notification.

## Research references

- Greenhouse Job Board API: <https://developers.greenhouse.io/job-board.html>
- Lever Postings API: <https://github.com/lever/postings-api>
- Recruitee Careers Site API: <https://docs.recruitee.com/reference/intro-to-careers-site-api>
- SmartRecruiters Posting API: <https://developers.smartrecruiters.com/docs/posting-api>
- Teamtailor RSS guide: <https://support.teamtailor.com/en/articles/11171756-rss-feed-how-to-guide>
- Welcome to the Jungle Solutions API: <https://developers.welcomekit.co/>
- XING job integration API: <https://dev.xing.com/partners/job_integration/api_docs>
- StepStone XML integration guide: <https://api.stepstone.com/knowledge-base/xml-guide/>
