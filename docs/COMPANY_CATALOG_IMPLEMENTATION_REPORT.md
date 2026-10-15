# Sourced company catalogue — implementation report

15 October 2026 · Europe/Zurich

## Outcome

The app now has a **Company database** route that imports small, attributable sets from CompaniesMarketCap and the hiring subset of the community-maintained yc-oss YC directory. Twenty records were loaded into the local database for the first example: ten leading public companies and ten hiring YC startups matching “hardware”. Users can search/filter these records, open their source or website, and optionally load remote logos.

Vacancy ingestion is deliberately separate. A company contributes openings only after the user selects Greenhouse, Lever, or Ashby, supplies the public board identifier, and the app successfully reads that employer board. The reviewed mapping is persisted and automatically joins later role-page refreshes.

## Why this architecture

- **Directory seed, official vacancy source:** CompaniesMarketCap describes public-company rankings and yc-oss mirrors public YC company metadata. Neither is treated as an authoritative job advert. Role titles, descriptions, locations and application links continue to come from employer-published ATS feeds.
- **yc-oss instead of scraping VCLense:** the interactive VCLense page was not reliably available to a simple document fetch and its reuse contract was not evident. yc-oss publishes a documented static JSON endpoint, daily generation history and source metadata, making the import inspectable and testable.
- **User-reviewed board mapping instead of automatic site crawling:** arbitrary careers pages are heterogeneous and introduce terms, robots, SSRF, rate and parser risks. A three-provider allowlist fits the existing adapters and makes every live source visible.
- **SQLite instead of a new service:** the app is local and already uses SQLite. Idempotent `(source, source_key)` upserts preserve a small dependency and operations footprint.

## Data and security boundaries

`company_catalog` stores public company facts and the complete normalized payload with source URL and import time. `company_catalog_imports` records each import count. `company_job_boards` stores reviewed provider identifiers and canonical board URLs. SQL uses parameters and foreign keys.

Imports are explicit, limited to 5–100 companies in the UI, fixed to two HTTPS hosts, restricted to public DNS results, bounded to 8 MB, and time out after 15 seconds. Redirects to another host are rejected. Free-form URLs are not fetched. Company HTML, descriptions and names are rendered through Streamlit text components or escaped before custom HTML. Remote logos are disabled by default because loading them discloses the browser IP to the image host.

The current importer does not download company career pages, use LinkedIn, collect people/contact data, bypass authentication, submit applications or mark missing jobs closed. It does not implement a background scheduler. No visitor analytics or fingerprinting was added.

## Verification and residual risk

Unit tests cover the CompaniesMarketCap table parser, YC filtering and size bands, fixed endpoint selection, import bounds, idempotent upserts and supported-board validation. A live read-only parser check returned NVIDIA, Apple and Alphabet with their tickers, countries and market-cap labels. The initial 20-record local import completed successfully.

The complete test suite, syntax compilation and whitespace check must pass before handoff. Source markup/schema can still change. yc-oss is unofficial and a company-level `isHiring` flag can lag a live board. Only Greenhouse, Lever and Ashby are supported; large employers using Workday or custom career sites need a separate, reviewed adapter or licensed data source. No production authentication, multi-user authorization, central rate limiting, retention automation or dependency-security audit was added.
