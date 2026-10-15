import pytest

from tau_job_application.yc_directory import (
    YCDirectoryStore,
    YCFilters,
    directory_facets,
    filter_yc_companies,
    parse_yc_directory,
)


def _payload():
    return [
        {"slug": "alpha-ai", "name": "Alpha AI", "status": "Active", "batch": "W24", "isHiring": True,
         "team_size": 12, "stage": "Early", "one_liner": "AI tooling", "industries": ["B2B", "Artificial Intelligence"],
         "regions": ["United States of America"], "tags": ["AI"], "all_locations": "San Francisco, CA, USA",
         "website": "https://alpha.example.com", "small_logo_thumb_url": "https://bookface-static.ycombinator.com/alpha.png",
         "url": "https://www.ycombinator.com/companies/alpha-ai"},
        {"slug": "beta-health", "name": "Beta Health", "status": "Active", "batch": "S23", "isHiring": False,
         "team_size": 60, "stage": "Growth", "one_liner": "Clinic software", "industries": ["Healthcare"],
         "regions": ["Germany"], "tags": ["health"], "all_locations": "Berlin, Germany"},
        {"slug": "gamma-pay", "name": "Gamma Pay", "status": "Acquired", "batch": "W21", "isHiring": None,
         "team_size": 200, "industries": ["Fintech"], "regions": ["United Kingdom"], "one_liner": "Payments"},
        {"slug": "", "name": "No slug"},
        "not-a-record",
    ]


def test_parse_yc_directory_validates_and_bounds():
    companies = parse_yc_directory(_payload())
    assert [company.slug for company in companies] == ["alpha-ai", "beta-health", "gamma-pay"]
    alpha = companies[0]
    assert alpha.status == "Active" and alpha.is_hiring is True and alpha.team_size == 12
    assert alpha.industries == ("B2B", "Artificial Intelligence")
    assert alpha.logo_url == "https://bookface-static.ycombinator.com/alpha.png"
    assert companies[1].logo_url is None
    assert companies[2].is_hiring is None
    with pytest.raises(ValueError):
        parse_yc_directory({"not": "a list"})
    with pytest.raises(ValueError):
        parse_yc_directory(_payload(), limit=0)


def test_unknown_status_becomes_unknown_and_filter_rejects_it():
    companies = parse_yc_directory([{"slug": "x", "name": "X", "status": "Stealth"}])
    assert companies[0].status == "Unknown"
    with pytest.raises(ValueError):
        YCFilters(statuses=("Stealth",))


def test_filters_mirror_the_ycglobe_flags():
    companies = parse_yc_directory(_payload())
    active_hiring = filter_yc_companies(companies, YCFilters(statuses=("Active",), hiring_only=True))
    assert [company.slug for company in active_hiring] == ["alpha-ai"]
    acquired = filter_yc_companies(companies, YCFilters(statuses=("Acquired",)))
    assert [company.slug for company in acquired] == ["gamma-pay"]
    fintech = filter_yc_companies(companies, YCFilters(industries=("fint",)))
    assert [company.slug for company in fintech] == ["gamma-pay"]
    germany = filter_yc_companies(companies, YCFilters(regions=("germany",)))
    assert [company.slug for company in germany] == ["beta-health"]
    batch = filter_yc_companies(companies, YCFilters(batches=("W24",)))
    assert [company.slug for company in batch] == ["alpha-ai"]
    query = filter_yc_companies(companies, YCFilters(query="clinic"))
    assert [company.slug for company in query] == ["beta-health"]
    small = filter_yc_companies(companies, YCFilters(max_team_size=50))
    assert [company.slug for company in small] == ["alpha-ai"]
    limited = filter_yc_companies(companies, YCFilters(limit=2))
    assert len(limited) == 2


def test_facets_collect_distinct_values():
    facets = directory_facets(parse_yc_directory(_payload()))
    assert facets["batches"] == ["W24", "W21", "S23"] or set(facets["batches"]) == {"W24", "S23", "W21"}
    assert "Healthcare" in facets["industries"]
    assert "Germany" in facets["regions"]


def test_store_refresh_snapshot_and_search(tmp_path):
    store = YCDirectoryStore(tmp_path / "db.sqlite")
    assert store.snapshot() is None
    with pytest.raises(ValueError):
        store.refresh([])
    count = store.refresh(parse_yc_directory(_payload()))
    assert count == 3
    snapshot = store.snapshot()
    assert snapshot["record_count"] == 3
    matches = store.search(YCFilters(statuses=("Active",), hiring_only=True))
    assert [company.slug for company in matches] == ["alpha-ai"]
    # A second refresh replaces, not duplicates.
    store.refresh(parse_yc_directory(_payload()))
    assert len(store.companies()) == 3
