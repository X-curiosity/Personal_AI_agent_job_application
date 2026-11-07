"""Company enrichment: fetch official logos and geocode HQ street addresses.

Logos: prefer the company's own site (apple-touch-icon / icon / og:image),
fall back to the public Google favicon service, and self-host the result.

Geocoding: best-effort via OpenStreetMap Nominatim — only keep a result when it
resolves to an office/building with a street, so we never show a made-up
address. Falls back to the caller's city-level location otherwise.
"""
from __future__ import annotations

import re
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx

UA = "HiredJobs/1.0 (public job directory; contact: repo)"
HEADERS = {"User-Agent": UA}

_APPLE_RE = re.compile(r'<link[^>]+rel=["\']apple-touch-icon["\'][^>]*>', re.I)
_FAVICON_RE = re.compile(r'<link[^>]+rel=["\'](?:icon|shortcut icon)["\'][^>]*>', re.I)
_HREF_RE = re.compile(r'href=["\']([^"\']+)["\']', re.I)

_EXT_BY_TYPE = {"image/png": ".png", "image/jpeg": ".jpg", "image/x-icon": ".ico",
                "image/vnd.microsoft.icon": ".ico", "image/svg+xml": ".svg", "image/webp": ".webp"}


def _extract_logo_urls(html: str, base: str) -> list[str]:
    urls: list[str] = []
    # apple-touch-icon (180px logo) first, then plain favicon. No og:image
    # (that's a social share card, not a logo).
    for tag in _APPLE_RE.findall(html):
        m = _HREF_RE.search(tag)
        if m:
            urls.append(urljoin(base, m.group(1)))
    for tag in _FAVICON_RE.findall(html):
        m = _HREF_RE.search(tag)
        if m:
            urls.append(urljoin(base, m.group(1)))
    return urls


def _is_company_article(title: str, name: str) -> bool:
    """True when the Wikipedia article is about the company, not a homonym
    (e.g. reject 'Mercury (planet)' when looking for Mercury the company)."""
    t = title.strip(); n = name.strip()
    if t.casefold() == n.casefold():
        return True
    m = re.match(rf"{re.escape(n)}\s*\(([^)]*)\)", t, re.I)
    return bool(m and re.search(r"company|software|corporation|financial|bank|startup|app|firm|brand|tech", m.group(1), re.I))


def _wikipedia_logo(name: str) -> str:
    """Official logo from the company's Wikipedia article (infobox image)."""
    try:
        response = httpx.get(
            "https://en.wikipedia.org/w/api.php",
            params={"action": "query", "generator": "search", "gsrsearch": name, "gsrlimit": "1",
                    "prop": "pageimages", "pithumbsize": "512", "format": "json", "redirects": "1"},
            headers=HEADERS, timeout=12, follow_redirects=True,
        )
        if response.status_code != 200:
            return ""
        pages = response.json().get("query", {}).get("pages", {})
        for page in pages.values():
            if not _is_company_article(page.get("title", ""), name):
                continue
            src = (page.get("thumbnail") or {}).get("source")
            if src:
                return src
    except Exception:
        pass
    return ""


def fetch_logo(website: str, slug: str, dest_dir: Path, name: str = "") -> str:
    """Download the best available logo for a company; return a relative path
    under the destination dir (or '' when nothing works)."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    domain = urlparse(website).netloc
    candidates: list[str] = [f"https://{domain}/apple-touch-icon.png"]
    try:
        response = httpx.get(website, headers=HEADERS, timeout=12, follow_redirects=True)
        if response.status_code == 200:
            candidates += _extract_logo_urls(response.text, website)
    except Exception:
        pass
    if name:
        wiki = _wikipedia_logo(name)
        if wiki:
            candidates.append(wiki)
    candidates.append(f"https://www.google.com/s2/favicons?domain={domain}&sz=128")

    seen: set[str] = set()
    for url in candidates:
        if url in seen:
            continue
        seen.add(url)
        try:
            response = httpx.get(url, headers=HEADERS, timeout=12, follow_redirects=True)
            if response.status_code != 200 or not response.content or len(response.content) < 120:
                continue
            content_type = (response.headers.get("content-type") or "").split(";")[0].strip().lower()
            if not content_type.startswith("image/"):
                continue  # ignore HTML error pages
            ext = _EXT_BY_TYPE.get(content_type, ".png")
            if ext == ".svg" and b"<svg" not in response.content[:200].lower():
                ext = ".png"
            path = dest_dir / f"{slug}{ext}"
            path.write_bytes(response.content)
            return f"data/logos/{slug}{ext}"
        except Exception:
            continue
    return ""


def fetch_logo_playwright(website: str, slug: str, dest_dir: Path) -> str:
    """Fetch a logo from a JS-rendered job board by rendering it headlessly,
    then downloading the first real logo candidate (icon / og:image / logo img)."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return ""
    candidates: list[str] = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            page.goto(website, wait_until="domcontentloaded", timeout=25000)
            page.wait_for_timeout(2500)
            candidates = page.evaluate("""() => {
                const urls = [];
                document.querySelectorAll('link[rel="apple-touch-icon"], link[rel="icon"], link[rel="shortcut icon"]').forEach(l => l.href && urls.push(l.href));
                document.querySelectorAll('meta[property="og:image"]').forEach(m => m.content && urls.push(m.content));
                document.querySelectorAll('img[src*="logo"], img.logo, header img, nav img').forEach(i => i.src && urls.push(i.src));
                return urls;
            }""")
            browser.close()
    except Exception:
        return ""
    dest_dir.mkdir(parents=True, exist_ok=True)
    for url in candidates:
        if not url.startswith("http"):
            continue
        try:
            r = httpx.get(url, headers=HEADERS, timeout=12, follow_redirects=True)
            if r.status_code != 200 or not r.content or len(r.content) < 120:
                continue
            ct = (r.headers.get("content-type") or "").split(";")[0].strip().lower()
            if not ct.startswith("image/"):
                continue
            ext = _EXT_BY_TYPE.get(ct, ".png")
            path = dest_dir / f"{slug}{ext}"
            path.write_bytes(r.content)
            return f"data/logos/{slug}{ext}"
        except Exception:
            continue
    return ""


def geocode_hq(name: str, city: str, country: str = "") -> dict | None:
    """Resolve a company HQ to a street address via Nominatim (best-effort).

    Returns {'address', 'latitude', 'longitude'} only when a street-level office
    is found; otherwise None (caller keeps city-level coordinates).
    """
    query = f"{name} {city}".strip()
    try:
        response = httpx.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": query, "format": "json", "limit": 1, "addressdetails": 1},
            headers=HEADERS, timeout=12,
        )
        if response.status_code != 200:
            return None
        data = response.json()
    except Exception:
        return None
    if not data:
        return None
    hit = data[0]
    # Require an actual office/building, never a street/place/park that merely
    # shares the name (e.g. "Mercury Street", a "Linear" park).
    if hit.get("class") not in ("office", "building"):
        return None
    addr = hit.get("address") or {}
    street = ", ".join(filter(None, [addr.get("house_number"), addr.get("road")]))
    # Only accept a result that actually has street detail and looks like a place/building.
    if not street:
        return None
    city_name = addr.get("city") or addr.get("town") or addr.get("municipality") or city
    country_name = addr.get("country") or country
    return {
        "address": f"{street}, {city_name}, {country_name}".strip(", "),
        "latitude": float(hit["lat"]),
        "longitude": float(hit["lon"]),
    }
