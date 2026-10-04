# European job-source strategy

## Product rule

Role-first discovery is the default opportunity flow. A user enters a target role, can edit the app's suggested lookalike titles, selects registered employer feeds, and explicitly chooses to refresh. The result is a local role-market page for that Career track and Job Workspace—not a manual contact-research workflow, people search, or outreach tool.

A source enters the product only when the data path is one of:

1. a documented public career-board API/feed;
2. an official API used with the employer's or user's authorized token; or
3. a CSV/JSON export supplied by the user who obtained it lawfully.

The application does not scrape LinkedIn, Indeed, Glassdoor, ZipRecruiter, XING, StepStone, or any other aggregator. It does not bypass access controls, browser automation, or robots restrictions. A LinkedIn control may open an outbound role-search URL, but it does not retrieve, import, or monitor LinkedIn listings.

## Registered role-market feeds and separate lawful inputs

The Role market can refresh only the small, manually registered set of vetted Greenhouse and Ashby employer boards. It is deliberately not a provider-wide search endpoint: adding an arbitrary board identifier belongs in the separate lawful-source flow, not in the registered market.

| Source/path | Europe relevance | Access model | Current boundary | Refresh behavior |
|---|---|---|---|---|
| Greenhouse | Widely used by EU/international startups | Official public Job Board API, registered board token | Registered Role-market feed; a known official board can also be fetched manually | Only after the user presses Role-market refresh or the manual board-fetch button |
| Lever | Widely used by EU/international startups | Public postings API, user-supplied site handle | Lawful manual source only; not a registered Role-market feed | User-triggered manual board fetch |
| Ashby | Used by international technology companies, including European teams | Official public Job Postings API, registered job-board name | Registered Role-market feed | Only after the user presses Role-market refresh |
| Recruitee | EU-founded ATS with European employer coverage | Documented unauthenticated Careers Site API, user-supplied company slug | Lawful manual source only; not a registered Role-market feed | User-triggered manual board fetch |
| SmartRecruiters | Strong EU enterprise presence | Official Posting API, employer-provided `X-SmartToken` | Authorized employer integration only; not a registered Role-market feed | User-triggered request; token is not stored |
| X | Useful hiring/funding/product signals | Official API v2 recent search, user token | Signal only, not a job-board adapter or Role-market result | Manual API request only |
| LinkedIn | Useful external search destination | Browser handoff to a role-search URL; authorized-user OIDC identity is separate | No listing feed/import, profile/people search, scrape, or automated outreach | Opens only when the user selects the handoff |
| User-provided export | Any European market | CSV/JSON, user-owned/licensed data | Lawful manual source; imported records remain reviewable and outside the registered Role market | User upload only |

## Role-market matching, provenance, and locations

- **Transparent matching:** the target title and editable aliases are the only role-family expansion. The app presents a small local alias suggestion rather than claiming an opaque semantic search has verified relevance. It then ranks listing titles deterministically and adds locally detected CV-skill overlap when a CV is present. CV text is not sent to a board for this ranking.
- **Source provenance:** an opening carries its provider, board identifier, external listing ID, listing URL, and retrieval time. Equivalent openings are merged only by canonical listing URL or provider/board/external identity; merged results retain every source observation so source filters and audits remain truthful.
- **Company filters:** company type, employee band, and funding stage must have a linked company-facts source when known. If a fact is missing or has not been verified, it is displayed as **Unknown** rather than guessed. An empty filter includes all values; selecting **Unknown** deliberately includes records without that sourced fact.
- **Role-location map:** pins come only from the locations stated on the matching listings. A company headquarters, office footprint, or company-explorer hub is never used as a proxy for where a role is located. Locations without a local coordinate are listed without a pin; missing listing locations remain missing.
- **Outcome boundary:** title/alias and CV-skill overlap explain why a listing appears. They do not establish fit, eligibility, compensation, work authorization, current availability, or likelihood of an interview.

## Candidate evidence and hiring-pattern boundary

The Job Workspace may show an **Evidence match** after a user analyzes one specific role. It is candidate-directed preparation support, not a recruiter-facing ranking or prediction of an interview, offer, or hiring outcome.

- **What contributes now:** explicit, confirmed CV skills and a candidate-added project only when it is marked complete, the candidate confirms their concrete contribution, it names a matching role skill, and it includes a non-confidential proof reference plus an observable outcome or test. A suggested project brief, work in progress, a GitHub language label, or an unconfirmed claim earns no credit.
- **What it does not collect:** no employee names, employee/profile URLs, CVs, portfolios, education histories, past-hire records, inferred employment, protected characteristics, or proxy attributes. The app does not use LinkedIn people search, profile scraping, or automated public-profile research to construct a company score.
- **Company component:** when no permitted company benchmark exists, it is shown as **Unavailable**, never as zero and never replaced with a synthetic "people who work there" comparison. A future integration may accept only a source-dated, employer-authorized or licensed **anonymous aggregate capability rubric** scoped to the company and compatible role. It must carry source provenance, validity dates, data-rights and anonymisation attestations, and a minimum-cohort policy; it cannot contain employee-level records.
- **Scope and retention:** project proof belongs to one Job Workspace and is kept locally. It is visible only to the candidate using that local workspace, follows the workspace if moved, and is deleted with the workspace. It is not sent to an employer, job board, or role-market source.

This design leaves a clear integration boundary: a company that wants a capability alignment feature must supply a documented aggregate rubric through an authorized arrangement. It cannot be substituted with collected public people data.

## Lawful manual sources

The **Bring a lawful source** panel stays separate from role discovery. A user may enter an official Greenhouse, Lever, or Recruitee employer board they know; use an employer-authorized SmartRecruiters token; or upload a job export they personally exported or obtained with permission. These paths support reviewing a specific source and creating a Job Workspace, but they do not silently expand the registered Role-market registry or turn into a crawler.

## Deferred / partnership-only sources

- **EURES:** Europe-wide and strategically valuable, but the publicly discoverable API material is not a stable, supported product integration contract. Add only after written API/access confirmation from EURES or a licensed partner.
- **Welcome to the Jungle:** Use its recruiter/customer API only under an appropriate customer or partnership agreement.
- **XING:** Its recruiting API requires a customer agreement and OAuth. Add when a customer credential and permitted use case exist.
- **StepStone:** Its documented XML integrations are employer feed workflows, not an open job-search API. Add under a commercial/feed agreement.
- **National public employment services** (for example France Travail, Bundesagentur für Arbeit, VDAB): evaluate country by country, using their current official developer agreement, rate limits, allowed redistribution, and language/location coverage before enabling an adapter.

## Refresh and monitoring design

Role-market discovery is deliberately **user-triggered**, not a hidden cron crawler:

1. The user chooses one or more registered Greenhouse or Ashby feeds and presses **Discover matching openings**.
2. The adapter retrieves only the current published listings from those registered boards.
3. The app saves the current query, source-attempt counts/errors, and ranked sourced openings as the latest local run for that Career track and Job Workspace.
4. A later explicit discovery refresh replaces that scope's market page. It is not evidence that an omitted listing is closed, and it does not create alerts.

Individual lawful boards use the existing manual monitoring path:

1. The user chooses a permitted source and identifier, then requests a fetch.
2. `JobMonitor` fingerprints fetched roles from canonical URL (when present), title, company, and requirements.
3. A local SQLite registry records first/last seen timestamps and reports roles newly observed on that manual refresh.
4. Tokens are never stored. The registry stores source identifiers and job snapshots only.

This gives the user auditable, bounded refreshes without creating an autonomous collection system. Scheduled polling should be added only for a source whose written terms and API quota expressly allow it, after the user configures cadence, region, retention, and notification preferences.

## Evaluation checklist for each new European source

- Official documentation and current terms reviewed.
- Explicit permission for the intended search, retrieval, local storage, and display use.
- Geographic and language coverage recorded.
- Authentication, rate limits, pagination, and error behavior tested with a fixture.
- Registered-board approval, public board URL, and provider/board identifier recorded before it is added to the Role market.
- Source URL, external ID, retrieval time, and supplied listing description retained with the opening.
- Known company-filter values link to a company-facts source; missing values remain **Unknown**.
- Role maps use only listing-stated locations and never company locations as a fallback.
- One source adapter cannot access arbitrary URLs or internal network addresses.
- Job fingerprint/deduplication and closed-role behavior tested.
- A user approves any scheduled refresh or external notification.

## Research references

- Greenhouse Job Board API: <https://developers.greenhouse.io/job-board.html>
- Lever Postings API: <https://github.com/lever/postings-api>
- Ashby Job Postings API: <https://developers.ashbyhq.com/docs/public-job-posting-api>
- Recruitee Careers Site API: <https://docs.recruitee.com/reference/intro-to-careers-site-api>
- SmartRecruiters Posting API: <https://developers.smartrecruiters.com/docs/posting-api>
- Teamtailor RSS guide: <https://support.teamtailor.com/en/articles/11171756-rss-feed-how-to-guide>
- Welcome to the Jungle Solutions API: <https://developers.welcomekit.co/>
- XING job integration API: <https://dev.xing.com/partners/job_integration/api_docs>
- StepStone XML integration guide: <https://api.stepstone.com/knowledge-base/xml-guide/>
