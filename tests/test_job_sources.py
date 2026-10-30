from pathlib import Path

from tau_job_application.job_sources import (
    JobSource,
    JobSourceStore,
    detect_ats_from_text,
    detect_company_ats,
    fetch_public_text,
    ingest_sources,
)


def test_detect_ats_from_text_finds_all_providers():
    html = """
    <a href="https://boards.greenhouse.io/figma">Figma</a>
    <a href="https://jobs.lever.co/acme">Acme</a>
    <a href="https://jobs.ashbyhq.com/mistral.ai">Mistral</a>
    <a href="https://apply.workable.com/jobs/ABC123">Workable</a>
    """
    found = {(f["source"], f["board_identifier"]) for f in detect_ats_from_text(html)}
    assert ("Greenhouse", "figma") in found
    assert ("Lever", "acme") in found
    assert ("Ashby", "mistral.ai") in found
    assert ("Workable", "ABC123") in found


def test_detect_company_ats_deduplicates_and_ignores_failures():
    calls = []

    def fetcher(url):
        calls.append(url)
        if url.endswith("/careers"):
            return '<a href="https://boards.greenhouse.io/figma">Careers</a>'
        if url.endswith("/jobs"):
            return '<a href="https://boards.greenhouse.io/figma">Jobs</a>'
        if url.endswith("/unreachable"):
            raise OSError("offline")
        return ""

    found = detect_company_ats("https://acme.example", careers_url="https://acme.example/unreachable", fetcher=fetcher)
    assert [f["board_identifier"] for f in found] == ["figma"]


def test_store_register_deduplicates_and_lists(tmp_path):
    store = JobSourceStore(tmp_path / "sources.sqlite")
    first = store.register(JobSource(company="Figma", source="Greenhouse", board_identifier="figma", board_url="https://boards.greenhouse.io/figma"))
    second = store.register(JobSource(company="Figma Inc.", source="Greenhouse", board_identifier="figma", board_url="https://boards.greenhouse.io/figma"))
    assert first == second
    assert store.count() == 1
    rows = store.list()
    assert rows[0]["company"] == "Figma Inc."  # upsert updated the company label
    store.set_enabled(rows[0]["id"], False)
    assert store.list(enabled_only=True) == []


def test_ingest_sources_records_success_and_error(tmp_path):
    store = JobSourceStore(tmp_path / "sources.sqlite")
    ok = store.register(JobSource(company="Figma", source="Greenhouse", board_identifier="figma", board_url="x"))
    bad = store.register(JobSource(company="Broken", source="Greenhouse", board_identifier="nope", board_url="x"))

    def fetcher(source, identifier, company):
        if identifier == "nope":
            raise RuntimeError("board not found")
        return [{"title": "Designer", "company": company}]

    openings = ingest_sources(store, openings_fetcher=fetcher)
    assert [o["title"] for o in openings] == ["Designer"]
    rows = {r["board_identifier"]: r for r in store.list()}
    assert rows["figma"]["last_success"] is not None
    assert "board not found" in rows["nope"]["last_error"]


def test_fetch_public_text_rejects_private_hosts(monkeypatch):
    def fake_getaddrinfo(*args, **kwargs):
        # a private address forces rejection
        import ipaddress
        return [(socket.SOCK_STREAM, socket.SOCK_STREAM, 6, "", (str(ipaddress.ip_address("127.0.0.1")), 443))]

    import socket
    import tau_job_application.job_sources as js
    monkeypatch.setattr(js.socket, "getaddrinfo", fake_getaddrinfo)
    try:
        js.fetch_public_text("https://example.com")
        raise AssertionError("expected rejection")
    except ValueError:
        pass
