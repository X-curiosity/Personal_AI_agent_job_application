"""Re-fetch logos for companies whose `website` points at an ATS board (wrong
logo), by resolving their real domain and pulling the header logo."""
from __future__ import annotations

import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ingest.enrich import fetch_logo
from ingest.store import Store

ROOT = Path(__file__).resolve().parents[1]
LOGO_DIR = ROOT / "vercel-site" / "data" / "logos"

_BOARDS = ("teamtailor", "personio", "bamboohr", "odoo", "gem.com", "careers-page",
           "bizneo", "welcomekit", "hibob", "kula", "dover", "join.com", "ashbyhq",
           "lever.co", "greenhouse", "workable", "recruitee", "smartrecruiters", "breezy")


def _real_domains(slug: str) -> list[str]:
    core = re.sub(r"[^a-z0-9]", "", slug.lower())
    for suf in ("gmbh", "labs", "ab", "oy", "bv", "srl", "limited", "ag"):
        if core.endswith(suf) and len(core) - len(suf) >= 3:
            core = core[: -len(suf)]
            break
    out = []
    for c in {core, core.replace("-", "")}:
        for tld in ("com", "io", "ai", "co", "app", "tech", "dev", "org"):
            out.append(f"https://{c}.{tld}")
    return out + [f"https://www.{core}.com", f"https://get{core}.com"]


def _one(store: Store, s: dict) -> tuple[str, str]:
    website = s.get("website") or ""
    host = urlparse(website).netloc
    candidates = [website]
    if any(b in host for b in _BOARDS):
        slug = host.split(".")[0]
        candidates = _real_domains(slug)
    for dom in candidates:
        logo = fetch_logo(dom, s["startup_id"], LOGO_DIR, name=s.get("name") or "")
        if logo:
            return s["startup_id"], logo
    return s["startup_id"], ""  # no real logo -> clear the wrong board logo


def main() -> None:
    store = Store()
    todo = [s for s in store.all_startups() if any(b in urlparse(s.get("website") or "").netloc for b in _BOARDS)]
    print(f"Re-fetching logos for {len(todo)} board-linked companies…")
    fixed = cleared = 0
    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = [pool.submit(_one, store, s) for s in todo]
        for fut in as_completed(futures):
            sid, logo = fut.result()
            if logo:
                with store._connect() as con:
                    con.execute("UPDATE startups SET logo_url = ? WHERE startup_id = ?", (logo, sid))
                fixed += 1
            else:
                with store._connect() as con:
                    con.execute("UPDATE startups SET logo_url = '' WHERE startup_id = ?", (sid,))
                cleared += 1
    print(f"Fixed {fixed}, cleared {cleared}. {store.counts()}")


if __name__ == "__main__":
    main()
