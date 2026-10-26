import json
import sqlite3

import pytest

from scripts.import_startupmap import (
    MAX_SITEMAP_BYTES,
    SITEMAP,
    import_startupmap,
    parse_city_page,
    parse_company_page,
)
from scripts.export_public_map import export_catalog


CITY = b'''<html><script type="application/ld+json">{"@graph":[{"@type":"ItemList","name":"Startups in Brussels"}]}</script>
<ul><li><a href="/startup/acme_be">Acme <span class="stage">  Series A</span><span class="hiring"> hiring</span></a></li></ul></html>'''
COMPANY = b'''<script type="application/ld+json">{"@context":"https://schema.org","@graph":[{"@type":"Organization","name":"Acme","url":"https://acme.example","description":"Makes useful things","logo":"https://cdn.example/acme.png","location":{"@type":"Place","address":{"@type":"PostalAddress","addressLocality":"Brussels","addressCountry":"Belgium"}}}]}</script>'''
SITEMAP_XML = b'''<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>https://startupmap.one/map/brussels</loc></url><url><loc>https://startupmap.one/api/startups</loc></url></urlset>'''


def test_parses_public_city_and_company_json_ld():
    city = parse_city_page("https://startupmap.one/map/brussels", CITY)[0]
    assert (city.slug, city.name, city.city, city.stage) == ("acme_be", "Acme", "Brussels", "Series A")
    record = parse_company_page(city, COMPANY)
    assert record["country"] == "Belgium"
    assert record["website"] == "https://acme.example"
    assert record["logo_url"] == "https://cdn.example/acme.png"


def test_atomic_snapshot_preserves_existing_data_on_failure(tmp_path):
    db_path = tmp_path / "assistant.sqlite"
    with sqlite3.connect(db_path) as db:
        db.execute("CREATE TABLE startupmap_companies (slug TEXT PRIMARY KEY, name TEXT, payload_json TEXT, imported_at TEXT)")
        db.execute("INSERT INTO startupmap_companies VALUES ('old','Old','{}','before')")

    def failing_fetch(url, **kwargs):
        if url == SITEMAP:
            assert kwargs["max_bytes"] == MAX_SITEMAP_BYTES
            return SITEMAP_XML
        if url.endswith("/map/brussels"):
            raise OSError("offline")
        raise AssertionError("company page must not be requested")

    with pytest.raises(RuntimeError, match="existing snapshot preserved"):
        import_startupmap(db_path, fetcher=failing_fetch, workers=2)
    with sqlite3.connect(db_path) as db:
        assert db.execute("SELECT slug, name FROM startupmap_companies").fetchall() == [("old", "Old")]


def test_detail_rate_limit_keeps_public_city_record(tmp_path):
    db_path = tmp_path / "assistant.sqlite"
    def fetch(url, **kwargs):
        if url == SITEMAP: return SITEMAP_XML
        if url.endswith("/map/brussels"): return CITY
        raise OSError("429 rate limited")
    count, errors = import_startupmap(db_path, fetcher=fetch, workers=2)
    assert count == 1 and errors
    with sqlite3.connect(db_path) as db:
        payload = json.loads(db.execute("SELECT payload_json FROM startupmap_companies WHERE slug='acme_be'").fetchone()[0])
    assert payload["city"] == "Brussels" and payload["website"] is None


def test_import_and_export_deduplicates_existing_name(tmp_path):
    db_path = tmp_path / "assistant.sqlite"
    with sqlite3.connect(db_path) as db:
        db.execute("CREATE TABLE company_catalog (source TEXT, source_key TEXT, name TEXT, payload_json TEXT, imported_at TEXT)")
        db.execute("INSERT INTO company_catalog VALUES (?,?,?,?,?)", ("CompaniesMarketCap", "acme", "Acme", json.dumps({"locations": "Brussels, Belgium"}), "now"))

    def fetch(url, **kwargs):
        if url == SITEMAP:
            return SITEMAP_XML
        if url.endswith("/map/brussels"):
            return CITY
        if url.endswith("/startup/acme_be"):
            return COMPANY
        raise AssertionError(url)

    count, errors = import_startupmap(db_path, fetcher=fetch, workers=2)
    assert count == 1 and errors == []
    output = tmp_path / "companies.json"
    data = export_catalog(db_path, output, exported_at="test", logos=False)
    assert [company["name"] for company in data["companies"]] == ["Acme"]


def test_startupmap_export_uses_public_fields_and_city_estimate(tmp_path):
    db_path = tmp_path / "assistant.sqlite"
    with sqlite3.connect(db_path) as db:
        db.execute("CREATE TABLE company_catalog (source TEXT, source_key TEXT, name TEXT, payload_json TEXT, imported_at TEXT)")
        db.execute("CREATE TABLE startupmap_companies (slug TEXT, name TEXT, payload_json TEXT, imported_at TEXT)")
        payload = parse_company_page(parse_city_page("https://startupmap.one/map/brussels", CITY)[0], COMPANY)
        db.execute("INSERT INTO startupmap_companies VALUES (?,?,?,?)", ("acme_be", "Acme", json.dumps(payload), "now"))
    data = export_catalog(db_path, tmp_path / "companies.json", logos=False)
    company = data["companies"][0]
    assert company["source"] == "StartupMap public pages"
    assert company["sourceUrl"] == "https://startupmap.one/startup/acme_be"
    assert company["website"] == "https://acme.example"
    assert company["country"] == "Belgium"
    assert company["precision"] in {"city", "country"}
