"""Export the SQLite store to the public JSON the frontend consumes."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ingest.store import Store

ROOT = Path(__file__).resolve().parents[1]
SITE_DATA = ROOT / "vercel-site" / "data"


def main() -> None:
    store = Store()
    SITE_DATA.mkdir(parents=True, exist_ok=True)

    startups = store.all_startups()
    jobs = store.all_jobs(visible_only=True)

    # startups.json — mirror startupmap's startup schema
    for s in startups:
        s["accelerators"] = json.loads(s["accelerators"] or "[]")
    (SITE_DATA / "startups.json").write_text(json.dumps(startups, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    # jobs.json — mirror startupmap's job schema (type[] parsed back to list)
    for j in jobs:
        j["type"] = json.loads(j["type"] or "[]")
    (SITE_DATA / "jobs.json").write_text(json.dumps(jobs, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    print(f"Exported {len(startups)} startups, {len(jobs)} jobs to {SITE_DATA}")


if __name__ == "__main__":
    main()
