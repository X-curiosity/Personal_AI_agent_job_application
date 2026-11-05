"""Headless-browser (playwright) pass for boards whose listing page is JS-rendered
(no SSR content for the httpx scraper). Reuses the browser per thread."""
from __future__ import annotations

import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from ingest.ats import Opening, fetch_playwright
from ingest.pipeline import _jobs_id, _slug, _to_job_row
from ingest.store import Store
from import_httpx import _extract, _startup  # reuse extraction

_local = threading.local()


def _listing(kind: str, arg: str) -> str:
    if kind == "wttj":
        return f"https://www.welcometothejungle.com/en/companies/{arg}/jobs"
    if kind == "hibob":
        return f"https://{arg}.careers.hibob.com/jobs"
    if kind == "join":
        return f"https://join.com/companies/{arg}/jobs"
    if kind == "dover":
        return f"https://app.dover.com/apply/{arg}/"
    if kind == "kula":
        return f"https://careers.kula.ai/{arg}/"
    return arg


def _fetch_one(store: Store, kind: str, s: dict, arg: str) -> tuple[int, int]:
    # skip if this company already has jobs
    sid = _slug(s["name"])
    with store._connect() as con:
        have = con.execute("SELECT COUNT(*) FROM jobs WHERE startup_id = ?", (sid,)).fetchone()[0]
    if have:
        return 0, 0
    openings = fetch_playwright(_listing(kind, arg), "playwright" if kind == "httpx" else f"ats:{kind}")
    if not openings:
        return 0, 0
    website = f"https://{urlparse(_listing(kind, arg)).netloc}"
    startup = _startup(s, website)
    store.upsert_startup(startup)
    n = 0
    for op in openings:
        store.upsert_job(_to_job_row(startup, op, _jobs_id(sid, op.title)))
        n += 1
    return 1, n


def main() -> None:
    rows = _extract()
    print(f"{len(rows)} boards to try with playwright")
    store = Store()
    companies = jobs = 0
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(_fetch_one, store, k, s, a) for k, s, a in rows]
        for fut in as_completed(futures):
            c, j = fut.result()
            companies += c
            jobs += j
    print(f"Fetched {jobs} roles across {companies} companies. {store.counts()}")


if __name__ == "__main__":
    main()
