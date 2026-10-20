#!/usr/bin/env python3
"""Fetch verified headquarters coordinates from Wikidata (CC0) for catalogue domains.

Matching is deliberately strong: a company only gets an exact coordinate when
its official-website statement (P856) on Wikidata matches its catalogue
website, and the entity has a headquarters location (P159) with a coordinate
(P625). Nothing is guessed from names. Output: data/wikidata_hq.json mapping
domain -> {lat, lng, label, qid}. Wikidata content is CC0; attribution is in
vendor/README.md and the company detail panel.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
USER_AGENT = "CoApplyGPT-PublicMap/1.0 (https://github.com/X-curiosity/Personal_AI_agent_job_application; wikidata hq lookup)"
API = "https://www.wikidata.org/w/api.php"
SEARCH_DELAY = 0.15


def _call(params: dict) -> dict:
    query = urlencode({"format": "json", "maxlag": "5", **params})
    request = Request(f"{API}?{query}", headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=30) as response:  # noqa: S310 - fixed official endpoint
        return json.loads(response.read().decode("utf-8"))


def domain_of(website: str | None) -> str | None:
    if not website:
        return None
    host = (urlparse(website).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host or None


def find_entity(domain: str) -> str | None:
    """Exact official-website statement match; no fuzzy name matching."""
    for scheme in ("https", "http"):
        for host in (f"www.{domain}", domain):
            try:
                result = _call({
                    "action": "query", "list": "search",
                    "srsearch": f'haswbstatement:P856={scheme}://{host}/',
                    "srlimit": "1",
                })
            except Exception:
                time.sleep(1)
                continue
            hits = result.get("query", {}).get("search", [])
            if hits:
                return hits[0]["title"]
            time.sleep(SEARCH_DELAY)
    return None


def fetch_coordinates(qids: list[str]) -> dict[str, tuple[float, float, str]]:
    coords: dict[str, tuple[float, float, str]] = {}
    hq_items: dict[str, str] = {}
    labels: dict[str, str] = {}
    for start in range(0, len(qids), 50):
        batch = qids[start:start + 50]
        try:
            result = _call({"action": "wbgetentities", "ids": "|".join(batch), "props": "claims|labels", "languages": "en"})
        except Exception:
            continue
        for qid, entity in result.get("entities", {}).items():
            labels[qid] = entity.get("labels", {}).get("en", {}).get("value", "")
            claims = entity.get("claims", {}).get("P159", [])
            if claims:
                hq_items[qid] = claims[0]["mainsnak"]["datavalue"]["value"]["id"]
        time.sleep(SEARCH_DELAY)
    hq_list = sorted(set(hq_items.values()))
    hq_coords: dict[str, tuple[float, float]] = {}
    for start in range(0, len(hq_list), 50):
        batch = hq_list[start:start + 50]
        try:
            result = _call({"action": "wbgetentities", "ids": "|".join(batch), "props": "claims"})
        except Exception:
            continue
        for qid, entity in result.get("entities", {}).items():
            claims = entity.get("claims", {}).get("P625", [])
            if claims:
                value = claims[0]["mainsnak"]["datavalue"]["value"]
                hq_coords[qid] = (value["latitude"], value["longitude"])
        time.sleep(SEARCH_DELAY)
    for qid, hq in hq_items.items():
        if hq in hq_coords:
            lat, lng = hq_coords[hq]
            coords[qid] = (lat, lng, labels.get(qid, ""))
    return coords


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--companies", type=Path, default=ROOT / "vercel-site/data/companies.json")
    parser.add_argument("--output", type=Path, default=ROOT / "vercel-site/data/wikidata_hq.json")
    parser.add_argument("--limit", type=int, default=0, help="Debug: only try the first N domains")
    args = parser.parse_args()
    companies = json.loads(args.companies.read_text())["companies"]
    domains = sorted({domain_of(c.get("website")) for c in companies} - {None})
    if args.limit:
        domains = domains[: args.limit]
    print(f"Looking up {len(domains)} website domains on Wikidata…")
    found: dict[str, str] = {}
    for index, domain in enumerate(domains):
        qid = find_entity(domain)
        if qid:
            found[domain] = qid
        if (index + 1) % 100 == 0:
            print(f"  {index + 1}/{len(domains)} domains, {len(found)} matched")
    coords = fetch_coordinates(sorted(set(found.values())))
    output = {}
    qid_to_domain = {qid: domain for domain, qid in found.items()}
    for qid, (lat, lng, label) in coords.items():
        domain = qid_to_domain.get(qid)
        if domain and -90 <= lat <= 90 and -180 <= lng <= 180:
            output[domain] = {"lat": lat, "lng": lng, "label": label, "qid": qid}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"Exact HQ coordinates for {len(output)} of {len(domains)} domains -> {args.output}")


if __name__ == "__main__":
    sys.exit(main())
