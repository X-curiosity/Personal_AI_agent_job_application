import pytest

from tau_job_application.company_catalog import CatalogCompany, CompanyCatalogStore
from tau_job_application.hiring_index import (
    MAX_INDEX_ENTRIES,
    MAX_LIVE_CHECKS_PER_BUILD,
    HiringEntry,
    HiringIndexStore,
    build_hiring_index,
    refresh_all_data,
)
from tau_job_application.yc_directory import YCDirectoryStore, parse_yc_directory


def _stores(tmp_path):
    database = tmp_path / "db.sqlite"
    yc = YCDirectoryStore(database)
    yc.refresh(parse_yc_directory([
        {"slug": "alpha-ai", "name": "Alpha AI", "status": "Active", "isHiring": True,
         "industries": ["Fintech"], "all_locations": "Berlin, Germany", "team_size": 30,
         "small_logo_thumb_url": "https://img.example.com/alpha.png"},
        {"slug": "beta-health", "name": "Beta Health", "status": "Active", "isHiring": True,
         "industries": ["Healthcare"], "team_size": 12},
        {"slug": "gamma-pay", "name": "Gamma Pay", "status": "Active", "isHiring": True},
        {"slug": "delta-old", "name": "Delta Old", "status": "Inactive", "isHiring": True},
        {"slug": "epsilon-calm", "name": "Epsilon Calm", "status": "Active", "isHiring": False},
    ]))
    return database, yc, CompanyCatalogStore(database)


def _openings_fetch(boards: dict[str, list]):
    def fetch(provider, identifier, *, company):
        if company in boards:
            return boards[company]
        raise RuntimeError("no network in tests")
    return fetch


def test_index_contains_active_hiring_and_never_scrapes_linkedin(tmp_path):
    _, yc, catalog = _stores(tmp_path)
    entries, errors = build_hiring_index(
        yc_store=yc, catalog_store=catalog,
        fetch_openings=_openings_fetch({}),  # every board check fails honestly
    )
    names = {entry.name for entry in entries}
    assert {"Alpha AI", "Beta Health", "Gamma Pay"} <= names  # Inactive / not-hiring excluded
    assert "Delta Old" not in names and "Epsilon Calm" not in names
    assert all("linkedin" not in entry.source_url.casefold() for entry in entries)
    # Failed vetted-board checks are skipped and reported, never zeroed.
    assert errors and all("Figma" in error or "Mistral" in error or "Cloudflare" in error for error in errors)
    yc_entries = [entry for entry in entries if entry.company_key.startswith("yc:")]
    assert all(entry.signal == "directory_flag" for entry in yc_entries)


def test_vetted_and_reviewed_boards_become_live_rows(tmp_path):
    _, yc, catalog = _stores(tmp_path)
    fetch = _openings_fetch({
        "Figma": [{"title": "Backend Engineer", "location": "San Francisco, CA"},
                  {"title": "Data Scientist", "location": "New York, NY"}],
    })
    entries, errors = build_hiring_index(yc_store=yc, catalog_store=catalog, fetch_openings=fetch)
    live = {entry.name: entry for entry in entries if entry.signal == "live_openings"}
    assert "Figma" in live
    figma = live["Figma"]
    assert figma.openings_count == 2
    assert figma.sample_titles == ("Backend Engineer", "Data Scientist")
    assert figma.sample_locations == ("San Francisco, CA", "New York, NY")
    assert figma.board_provider == "Greenhouse"
    # The boards that failed are reported, not zeroed.
    assert any("Mistral AI" in error for error in errors)
    assert any("Cloudflare" in error for error in errors)


def test_yc_candidate_matching_a_live_board_is_enriched_not_duplicated(tmp_path):
    database, yc, catalog = _stores(tmp_path)
    catalog.import_companies([CatalogCompany(
        source="YC community API", source_key="alpha-ai",
        source_url="https://www.ycombinator.com/companies/alpha-ai", name="Alpha AI",
    )])
    row = catalog.list_companies(query="Alpha AI")[0]
    catalog.register_board(int(row["id"]), "Lever", "alphaai")
    fetch = _openings_fetch({"Alpha AI": [{"title": "Platform Engineer", "location": "Berlin, Germany"}]})
    entries, _ = build_hiring_index(yc_store=yc, catalog_store=catalog, fetch_openings=fetch)
    alpha_entries = [entry for entry in entries if entry.name == "Alpha AI"]
    assert len(alpha_entries) == 1
    alpha = alpha_entries[0]
    assert alpha.signal == "live_openings" and alpha.openings_count == 1
    # Directory facts enrich the live row.
    assert alpha.logo_url == "https://img.example.com/alpha.png"
    assert alpha.team_size == 30 and alpha.industry == "Fintech"


def test_live_checks_are_capped_per_build(tmp_path):
    database = tmp_path / "db.sqlite"
    yc = YCDirectoryStore(database)
    yc.refresh(parse_yc_directory([
        {"slug": f"co-{index}", "name": f"Co {index:03d}", "status": "Active", "isHiring": True}
        for index in range(30)
    ]))
    catalog = CompanyCatalogStore(database)
    for index in range(30):
        catalog.import_companies([CatalogCompany(
            source="YC community API", source_key=f"co-{index}",
            source_url=f"https://www.ycombinator.com/companies/co-{index}", name=f"Co {index:03d}",
        )])
    for row in catalog.list_companies(limit=500):
        catalog.register_board(int(row["id"]), "Greenhouse", row["company"].source_key.replace("-", ""))

    checks = []

    def counting_fetch(provider, identifier, *, company):
        checks.append(company)
        return []

    entries, _ = build_hiring_index(yc_store=yc, catalog_store=catalog, fetch_openings=counting_fetch)
    assert len(checks) == MAX_LIVE_CHECKS_PER_BUILD  # vetted boards first, then reviewed ones
    live = [entry for entry in entries if entry.signal == "live_openings"]
    assert len(live) == MAX_LIVE_CHECKS_PER_BUILD


def test_store_roundtrip_filters_and_bounds(tmp_path):
    database, yc, catalog = _stores(tmp_path)
    store = HiringIndexStore(database)
    assert store.run() is None
    with pytest.raises(ValueError):
        store.save_run([])
    entries, _ = build_hiring_index(yc_store=yc, catalog_store=catalog, fetch_openings=_openings_fetch({}))
    store.save_run(entries)
    run = store.run()
    assert run["entry_count"] == len(entries)
    assert {entry.name for entry in store.entries(industry="fint")} == {"Alpha AI"}
    assert {entry.name for entry in store.entries(region="germany")} == {"Alpha AI"}
    assert {entry.name for entry in store.entries(query="health")} == {"Beta Health"}
    with pytest.raises(ValueError):
        store.entries(limit=0)
    store.save_run(entries)
    assert len(store.entries(limit=MAX_INDEX_ENTRIES)) == len(entries)


def test_entry_model_is_bounded():
    with pytest.raises(ValueError):
        HiringEntry(company_key="", name="X", signal="live_openings", source_label="s", source_url="https://x.example.com")
    with pytest.raises(ValueError):
        HiringEntry(company_key="k", name="X", signal="maybe", source_label="s", source_url="https://x.example.com")


def test_refresh_all_data_updates_snapshots_and_index(tmp_path):
    database, yc, catalog = _stores(tmp_path)
    from tau_job_application.capital_atlas import parse_atlas_companies
    atlas_companies = parse_atlas_companies(
        "a=[{rank:1,name:`Foo Systems`,value:100,country:`USA`,ownership:`Public`,"
        "website:`https://foo.example.com`,source:`https://example.com/foo`}];"
    )
    summary = refresh_all_data(
        database,
        yc_fetcher=lambda: parse_yc_directory([{"slug": "z-co", "name": "Z Co", "status": "Active", "isHiring": True}]),
        atlas_fetcher=lambda: atlas_companies,
        openings_fetcher=_openings_fetch({"Figma": [{"title": "PM", "location": "NYC"}]}),
    )
    assert summary["yc_records"] == 1 and summary["atlas_records"] == 1
    assert summary["indexed"] >= 2  # live Figma row + Z Co flag
    assert summary["live"] == 1
    store = HiringIndexStore(database)
    assert {entry.name for entry in store.entries(query="z co")} == {"Z Co"}


def test_refresh_all_data_never_destroys_previous_data_on_failure(tmp_path):
    database, yc, catalog = _stores(tmp_path)
    entries, _ = build_hiring_index(yc_store=yc, catalog_store=catalog, fetch_openings=_openings_fetch({}))
    HiringIndexStore(database).save_run(entries)
    before = yc.snapshot()["record_count"]

    def broken_yc():
        raise RuntimeError("source down")

    summary = refresh_all_data(
        database, yc_fetcher=broken_yc, atlas_fetcher=None,
        openings_fetcher=_openings_fetch({}),
    )
    assert yc.snapshot()["record_count"] == before
    assert any("kept previous data" in error for error in summary["errors"])
    assert summary["indexed"] == len(entries)  # index still rebuilt from the kept snapshot
