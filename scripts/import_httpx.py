"""Import the remaining sources: wttj/hibob/join/dover/kula boards and httpx
scraped career pages, from the startupmap reference snapshot."""
from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ingest.ats import fetch_dover, fetch_hibob, fetch_join, fetch_httpx, fetch_kula, fetch_wttj
from ingest.pipeline import _jobs_id, _slug, _to_job_row
from ingest.store import Store

BAK = Path("/Users/magbi/Desktop/startupmap-rebuild-backup-20261104-194859")

_ATS_FETCH = {"wttj": fetch_wttj, "hibob": fetch_hibob, "join": fetch_join, "dover": fetch_dover, "kula": fetch_kula}


def _extract() -> list[tuple[str, dict, str]]:
    """Return [(kind, startup_dict, arg)] where kind is a vendor or 'httpx'."""
    startups = {s["startup_id"]: s for s in json.load(open(BAK / "sm-startups.json"))}
    seen: set[tuple[str, str]] = set()
    rows: list[tuple[str, dict, str]] = []
    for j in json.load(open(BAK / "sm-jobs.json")):
        method = j.get("scrape_method") or ""
        sid = j.get("startup_id") or ""
        s = startups.get(sid)
        if not s or not s.get("name"):
            continue
        url = j.get("apply_url") or ""
        host = urlparse(url).netloc
        path = [p for p in urlparse(url).path.split("/") if p]
        if method == "ats:wttj" and "welcometothejungle" in host:
            slug = path[path.index("companies") + 1] if "companies" in path else ""
            key = ("wttj", slug)
            if slug and key not in seen:
                seen.add(key); rows.append(("wttj", s, slug))
        elif method == "ats:hibob" and ".careers.hibob.com" in host:
            board = host.split(".")[0]
            key = ("hibob", board)
            if key not in seen:
                seen.add(key); rows.append(("hibob", s, board))
        elif method == "ats:join" and host == "join.com":
            slug = path[path.index("companies") + 1] if "companies" in path else ""
            key = ("join", slug)
            if slug and key not in seen:
                seen.add(key); rows.append(("join", s, slug))
        elif method == "ats:dover" and "dover.com" in host:
            org = path[path.index("apply") + 1] if "apply" in path else ""
            key = ("dover", org)
            if org and key not in seen:
                seen.add(key); rows.append(("dover", s, org))
        elif method == "ats:kula" and "kula.ai" in host:
            company = path[0] if path else ""
            key = ("kula", company)
            if company and key not in seen:
                seen.add(key); rows.append(("kula", s, company))
        elif method in ("httpx", "playwright"):
            first = path[0] if path else ""
            if first in ("careers", "jobs", "job", "positions", "open-positions", "companies", "vacancies"):
                listing = f"https://{host}/{first}"
            else:
                listing = f"https://{host}/careers"
            key = ("httpx", host)
            if host and key not in seen:
                seen.add(key); rows.append(("httpx", s, listing))
    return rows


def _startup(s: dict, website: str) -> dict:
    def _v(x):
        return x or ""
    return {
        "startup_id": _slug(s["name"]), "name": s["name"], "website": website,
        "logo_url": "", "latitude": s.get("latitude"), "longitude": s.get("longitude"),
        "office_city": _v(s.get("office_city")), "address": "", "country": _v(s.get("country")),
        "domain_primary": _v(s.get("domain_primary")), "stage": _v(s.get("stage")),
        "hiring_status": _v(s.get("hiring_status")), "team_size_min": None, "team_size_max": None,
        "year_founded": s.get("year_founded"), "accelerators": "[]",
        "last_funding_amount": "", "claimed": 0, "why_interesting": "",
    }


def _fetch_one(store: Store, kind: str, s: dict, arg: str) -> tuple[int, int]:
    try:
        if kind in _ATS_FETCH:
            openings = _ATS_FETCH[kind](arg)
            website = f"https://{arg}" if False else ""
        else:
            openings = fetch_httpx(arg, "httpx")
            website = f"https://{urlparse(arg).netloc}"
    except Exception:
        return 0, 0
    if not openings:
        return 0, 0
    startup = _startup(s, website)
    store.upsert_startup(startup)
    n = 0
    for op in openings:
        store.upsert_job(_to_job_row(startup, op, _jobs_id(startup["startup_id"], op.title)))
        n += 1
    return 1, n


def main() -> None:
    rows = _extract()
    print(f"{len(rows)} remaining boards to scrape")
    store = Store()
    companies = jobs = 0
    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = [pool.submit(_fetch_one, store, k, s, a) for k, s, a in rows]
        for fut in as_completed(futures):
            c, j = fut.result()
            companies += c
            jobs += j
    print(f"Fetched {jobs} roles across {companies} companies. {store.counts()}")


if __name__ == "__main__":
    main()
