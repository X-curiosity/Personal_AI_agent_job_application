"""Safe extraction of a user-submitted public job page."""
from __future__ import annotations

from html.parser import HTMLParser
from ipaddress import ip_address
import json
import re
import socket
from urllib.parse import urljoin, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from tau_job_application.models import JobPosting
from tau_job_application.parsing import parse_job_text


class _PageParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title: list[str] = []
        self.text: list[str] = []
        self.json_ld: list[str] = []
        self._in_title = False
        self._in_script = False
        self._script_type = ""
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if tag == "title":
            self._in_title = True
        if tag in {"script", "style", "noscript", "svg"}:
            self._skip_depth += 1
            if tag == "script":
                self._in_script = True
                self._script_type = attrs_dict.get("type", "")

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        if tag in {"script", "style", "noscript", "svg"}:
            self._skip_depth = max(0, self._skip_depth - 1)
            if tag == "script":
                self._in_script = False

    def handle_data(self, data):
        if self._in_title:
            self.title.append(data)
        if self._in_script and "ld+json" in self._script_type:
            self.json_ld.append(data)
        elif self._skip_depth == 0 and data.strip():
            self.text.append(data.strip())


class _PublicRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_public_url(urljoin(req.full_url, newurl))
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def validate_public_url(url: str) -> str:
    parsed = urlparse(url.strip())
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Job URL must be an HTTPS URL without embedded credentials")
    hostname = parsed.hostname.casefold().rstrip(".")
    if hostname in {"localhost", "localhost.localdomain"}:
        raise ValueError("Local job URLs are not allowed")
    try:
        records = socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError(f"Could not resolve job URL host: {hostname}") from exc
    for record in records:
        address = ip_address(record[4][0])
        if address.is_private or address.is_loopback or address.is_link_local or address.is_reserved or address.is_multicast:
            raise ValueError("Job URL resolved to a non-public address")
    return parsed.geturl()


def fetch_job_url(url: str, *, max_bytes: int = 2_000_000) -> JobPosting:
    """Fetch one explicitly supplied public page; never crawl links or search a site."""
    url = validate_public_url(url)
    request = Request(url, headers={"Accept": "text/html,application/xhtml+json", "User-Agent": "job-readiness-assistant/0.3"})
    try:
        with build_opener(_PublicRedirect()).open(request, timeout=15) as response:
            final_url = validate_public_url(response.geturl())
            content_type = response.headers.get_content_type()
            if content_type not in {"text/html", "application/xhtml+xml", "application/json"}:
                raise ValueError(f"Job page returned unsupported content type: {content_type}")
            raw = response.read(max_bytes + 1)
    except ValueError:
        raise
    except Exception as exc:
        raise RuntimeError(f"Could not read the job URL: {exc}") from exc
    if len(raw) > max_bytes:
        raise ValueError("Job page is larger than the 2 MB safety limit")
    encoding = response.headers.get_content_charset() or "utf-8"
    text = raw.decode(encoding, errors="replace")
    return parse_job_page(text, final_url, content_type)


def parse_job_page(raw: str, url: str, content_type: str = "text/html") -> JobPosting:
    """Extract Schema.org JobPosting metadata plus readable page text."""
    title = company = location = description = None
    if content_type == "application/json":
        data = json.loads(raw)
        candidates = data if isinstance(data, list) else [data]
        data = next((item for item in candidates if isinstance(item, dict)), {})
        title, company, location, description = _job_fields(data)
        page_text = description or raw
    else:
        parser = _PageParser()
        parser.feed(raw)
        page_text = "\n".join(parser.text)
        for blob in parser.json_ld:
            try:
                data = json.loads(blob)
            except json.JSONDecodeError:
                continue
            candidates = data if isinstance(data, list) else [data]
            for item in candidates:
                if not isinstance(item, dict):
                    continue
                if item.get("@type") == "JobPosting" or "JobPosting" in item.get("@type", []):
                    title, company, location, description = _job_fields(item)
                    break
            if title or description:
                break
        title = title or _meta(raw, "og:title") or (" ".join(parser.title).strip() or None)
        company = company or _meta(raw, "og:site_name") or _meta(raw, "application-name")
    description = description or page_text
    description = _clean_text(description)
    if not description:
        raise ValueError("The job page did not contain readable description text")
    try:
        job = parse_job_text(description, title=title, company=company, url=url)
        return job.model_copy(update={"location": location}) if location else job
    except ValueError as exc:
        raise ValueError("The page was read, but no job requirements could be inferred. Review or paste the description.") from exc


def _job_fields(item: dict):
    company = item.get("hiringOrganization", {})
    company = company.get("name") if isinstance(company, dict) else company
    location = item.get("jobLocation", {})
    if isinstance(location, list):
        location = location[0] if location else {}
    if isinstance(location, dict):
        address = location.get("address", {})
        location = ", ".join(str(address.get(key)) for key in ("addressLocality", "addressRegion", "addressCountry") if address.get(key)) if isinstance(address, dict) else str(location.get("name", ""))
    return item.get("title"), company, location or None, item.get("description")


def _meta(raw: str, property_name: str) -> str | None:
    match = re.search(rf'<meta[^>]+(?:property|name)=["\']{re.escape(property_name)}["\'][^>]+content=["\']([^"\']+)', raw, re.I)
    return match.group(1).strip() if match else None


def _clean_text(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()
