import json
from pathlib import Path
import sqlite3

from scripts.export_public_map import COMPANY_FIELDS, export_catalog, public_id, safe_https, _safe_geocode, classify_stage


def _database(path: Path) -> None:
    with sqlite3.connect(path) as db:
        db.execute("""CREATE TABLE company_catalog (
            id INTEGER PRIMARY KEY, source TEXT, source_key TEXT, name TEXT,
            payload_json TEXT, imported_at TEXT)""")
        payload = {
            "source_url": "https://example.com/source", "website": "http://unsafe.example",
            "summary": "Public summary", "industry": "Robotics", "funding_stage": "Unknown",
            "locations": "London, Canada", "hiring": False,
            "private_notes": "never publish", "credentials": "secret", "custom_board": "private",
        }
        db.execute("INSERT INTO company_catalog VALUES (1,?,?,?,?,?)", (
            "YC community API", "acme", "Acme", json.dumps(payload), "2026-10-20T12:00:00+00:00"))
        db.execute("INSERT INTO company_catalog VALUES (2,?,?,?,?,?)", (
            "YC community API", "remote", "Remote Co", json.dumps({
                "source_url": "javascript:alert(1)", "locations": "Remote", "hiring": True,
            }), "2026-10-20T12:00:00+00:00"))


def test_export_has_only_public_schema_and_safe_values(tmp_path: Path) -> None:
    database, output = tmp_path / "catalog.sqlite", tmp_path / "companies.json"
    _database(database)
    data = export_catalog(database, output, exported_at="2026-10-20T13:00:00+00:00")
    assert data["schemaVersion"] == 1
    assert len(data["companies"]) == 2
    company = data["companies"][0]
    assert set(company) == COMPANY_FIELDS
    assert company["stage"] == "unknown"  # unknown is never promoted to early
    assert company["website"] is None
    assert company["precision"] == "country"  # London must not become a UK city pin
    assert company["id"] == public_id("YC community API", "acme")
    assert "private_notes" not in output.read_text()
    assert "credentials" not in output.read_text()
    assert "custom_board" not in output.read_text()


def test_export_schema_coordinates_and_unmapped_records(tmp_path: Path) -> None:
    database, output = tmp_path / "catalog.sqlite", tmp_path / "companies.json"
    _database(database)
    companies = export_catalog(database, output)["companies"]
    assert {company["precision"] for company in companies} <= {"city", "country", "unmapped"}
    assert all(company["stage"] in {"early", "growth", "scaleup", "big", "unknown"} for company in companies)
    for company in companies:
        if company["latitude"] is not None:
            assert -90 <= company["latitude"] <= 90
            assert -180 <= company["longitude"] <= 180
        else:
            assert company["longitude"] is None
    remote = next(company for company in companies if company["name"] == "Remote Co")
    assert remote["precision"] == "unmapped"
    assert remote["sourceUrl"] is None
    assert remote["hiringSignal"] == "directory_flag"


def test_public_links_reject_network_literals_and_reserved_hosts():
    for host in ["172.16.0.1", "172.31.255.255", "10.0.0.1", "192.168.1.1", "127.0.0.1",
                 "[::1]", "[fc00::1]", "169.254.169.254", "2130706433", "0177.0.0.1",
                 "8.8.8.8", "localhost", "app.local", "app.internal"]:
        assert safe_https(f"https://{host}/path") is None
    assert safe_https("https://example.com/jobs") == "https://example.com/jobs"
    assert safe_https("https://example.com/\nsecret") is None


def test_multi_office_locations_choose_first_resolvable_place():
    for separator in [";", "•", "|"]:
        point = _safe_geocode(f"San Francisco, USA{separator} Paris, France")
        assert point.longitude < -100
        assert point.label != "France"
    assert _safe_geocode("Remote; London, United Kingdom").label == "London"
    assert _safe_geocode("Mexico City, Mexico; Lima, Peru").longitude < -90
    assert classify_stage({"company_type": "Startup", "funding_stage": "Not applicable"})[0] == "unknown"


def test_street_address_keeps_city_pin_but_london_canada_stays_country():
    point = _safe_geocode("Affolternstrasse 44, Zurich, 8050, Switzerland")
    assert point.precision == "city" and point.label == "Zurich"
    guarded = _safe_geocode("London, Canada")
    assert guarded.precision == "country"  # alias must not steer to the UK


def test_country_normalization_and_region_detection():
    from scripts.export_public_map import normalize_country, split_location
    assert normalize_country("USA") == "United States"
    assert normalize_country("United States") == "United States"
    assert normalize_country("UK") == "United Kingdom"
    assert normalize_country("france") == "France"
    assert normalize_country(None) is None
    assert split_location("San Francisco, CA, USA") == ("United States", "California")
    assert split_location("Austin, TX, United States") == ("United States", "Texas")
    assert split_location("New York City, NY, USA") == ("United States", "New York")
    assert split_location("Seattle, Washington, USA") == ("United States", "Washington")
    assert split_location("Paris, France") == ("France", None)
    assert split_location("Lyon, Auvergne-Rhône-Alpes, France") == ("France", "Auvergne-Rhône-Alpes")
    assert split_location("Mexico City, Mexico; Lima, Peru")[0] == "Mexico"
    assert split_location(None) == (None, None)


def test_logo_source_prefers_direct_url_and_validates_domains():
    from scripts.export_public_map import _logo_source
    assert _logo_source({"logo_url": "https://cdn.example.com/logo.png"}) == ["https://cdn.example.com/logo.png"]
    candidates = _logo_source({"website": "https://www.acme.com/about"})
    assert candidates[0] == "https://www.acme.com/apple-touch-icon.png"
    assert candidates[1] == "https://www.acme.com/favicon.ico"
    assert candidates[2] == "https://icons.duckduckgo.com/ip3/acme.com.ico"
    assert _logo_source({"website": "http://acme.com"}) == []
    assert _logo_source({}) == []
    assert _logo_source({"logo_url": "javascript:x"}) == []
