import pytest

from tau_job_application.capital_atlas import (
    AtlasFilters,
    AtlasStore,
    atlas_facets,
    fetch_atlas_companies,
    fetch_capital_atlas,
    filter_atlas_companies,
    parse_atlas_companies,
    parse_capital_atlas,
    to_catalog_company,
)

FIXTURE_JS = """
;var i=e(t(),1),a=[{rank:1,name:`Foo Systems`,ticker:`FOO`,value:1566,country:`USA`,
source:`https://companiesmarketcap.com/foo/marketcap/`,ownership:`Public`,
address:`1 Example Way, Austin, TX, United States`,lat:30.1,lng:-97.7,
website:`https://www.foo.example.com`,description:`Foo builds example infrastructure.`,
industry:`Technology`,subIndustry:`Semiconductors`,recent:!0,
marketCapHistory:[{year:2024,value:900},{year:2025,value:1566}]},
{rank:2,name:`Bar Group`,value:42,country:`Germany`,ownership:`Private`,
source:`https://example.com/bar`,website:`https://bar.example.com`,description:`Bar invests.`,active:!1},
{name:`Tiny Co`,value:5,country:`France`,ownership:`Public`}];
"""


def test_parse_handles_minified_js_literals_and_nested_arrays():
    companies = parse_capital_atlas(FIXTURE_JS, min_value_billions=10, limit=100)
    assert [company.name for company in companies] == ["Foo Systems", "Bar Group"]
    foo = companies[0]
    assert foo.market_cap == "$1.6T"
    assert foo.company_type == "Public"
    assert foo.industry == "Semiconductors"
    assert foo.ticker == "FOO"
    assert foo.country == "USA"
    assert foo.locations and "Austin" in foo.locations
    bar = companies[1]
    assert bar.market_cap == "$42B"
    assert bar.company_type == "Private"
    assert bar.rank == 2


def test_threshold_and_limit_are_enforced():
    assert [c.name for c in parse_capital_atlas(FIXTURE_JS, min_value_billions=100, limit=100)] == ["Foo Systems"]
    assert [c.name for c in parse_capital_atlas(FIXTURE_JS, min_value_billions=10, limit=1)] == ["Foo Systems"]
    with pytest.raises(ValueError):
        parse_capital_atlas(FIXTURE_JS, min_value_billions=10, limit=0)
    with pytest.raises(ValueError):
        parse_capital_atlas(FIXTURE_JS, min_value_billions=15, limit=100)
    with pytest.raises(ValueError):
        parse_capital_atlas("a=[{rank:1,name:`Tiny`,value:5}];", min_value_billions=1000, limit=100)


def test_invalid_payloads_raise_honest_errors():
    with pytest.raises(ValueError):
        parse_capital_atlas("var nothing = true;", min_value_billions=10, limit=100)
    with pytest.raises(ValueError):
        parse_capital_atlas("a=[{rank:1,name:`Unterminated", min_value_billions=10, limit=100)


def test_fetch_uses_fixed_host_for_homepage_and_asset():
    calls = []

    def fake_fetcher(url, *, expected_host):
        calls.append((url, expected_host))
        if url.endswith(".js"):
            return FIXTURE_JS.encode()
        return b'<html><head><link rel="modulepreload" href="/assets/page-test.js"></head></html>'

    companies = fetch_capital_atlas(min_value_billions=10, limit=100, fetcher=fake_fetcher)
    assert [company.name for company in companies] == ["Foo Systems", "Bar Group"]
    assert calls == [
        ("https://capital.theojaffee.net/", "capital.theojaffee.net"),
        ("https://capital.theojaffee.net/assets/page-test.js", "capital.theojaffee.net"),
    ]


def test_fetch_fails_when_asset_reference_is_missing():
    def fake_fetcher(url, *, expected_host):
        return b"<html><head></head></html>"

    with pytest.raises(RuntimeError):
        fetch_capital_atlas(fetcher=fake_fetcher)


def test_parse_atlas_companies_returns_validated_sorted_records():
    companies = parse_atlas_companies(FIXTURE_JS)
    assert [company.name for company in companies] == ["Foo Systems", "Bar Group", "Tiny Co"]
    foo = companies[0]
    assert foo.value_billions == 1566 and foo.formatted_value == "$1.6T"
    assert foo.ownership == "Public" and foo.industry == "Semiconductors"
    assert foo.website == "https://www.foo.example.com"
    assert companies[1].ownership == "Private"
    assert companies[2].rank is None


def test_filter_atlas_companies_local_filters():
    companies = parse_atlas_companies(FIXTURE_JS)
    assert [c.name for c in filter_atlas_companies(companies, AtlasFilters(ownership=("Private",)))] == ["Bar Group"]
    assert [c.name for c in filter_atlas_companies(companies, AtlasFilters(countries=("germany",)))] == ["Bar Group"]
    assert [c.name for c in filter_atlas_companies(companies, AtlasFilters(query="infrastructure"))] == ["Foo Systems"]
    assert [c.name for c in filter_atlas_companies(companies, AtlasFilters(min_value_billions=50))] == ["Foo Systems"]
    with pytest.raises(ValueError):
        AtlasFilters(min_value_billions=15)
    with pytest.raises(ValueError):
        AtlasFilters(ownership=("State",))
    facets = atlas_facets(companies)
    assert "Semiconductors" in facets["industries"]
    assert "Germany" in facets["countries"]


def test_atlas_store_snapshot_roundtrip(tmp_path):
    store = AtlasStore(tmp_path / "db.sqlite")
    assert store.snapshot() is None
    with pytest.raises(ValueError):
        store.refresh([])
    count = store.refresh(parse_atlas_companies(FIXTURE_JS))
    assert count == 3
    assert store.snapshot()["record_count"] == 3
    matches = store.search(AtlasFilters(ownership=("Public",)))
    # Tiny Co ($5B) falls below the minimum $10B threshold.
    assert [company.name for company in matches] == ["Foo Systems"]
    store.refresh(parse_atlas_companies(FIXTURE_JS))
    assert len(store.companies()) == 3


def test_to_catalog_company_mapping():
    company = parse_atlas_companies(FIXTURE_JS)[0]
    record = to_catalog_company(company)
    assert record.source == "Global Capital Atlas"
    assert record.market_cap == "$1.6T"
    assert record.company_type == "Public"
    assert record.ticker == "FOO"
    assert record.website == company.website


def test_fetch_atlas_companies_two_step_fixed_host():
    calls = []

    def fake_fetcher(url, *, expected_host, max_bytes=8_000_000):
        calls.append(url)
        if url.endswith(".js"):
            return FIXTURE_JS.encode()
        return b'<html><head><link rel="modulepreload" href="/assets/page-test.js"></head></html>'

    companies = fetch_atlas_companies(fetcher=fake_fetcher)
    assert [company.name for company in companies][:2] == ["Foo Systems", "Bar Group"]
    assert calls == ["https://capital.theojaffee.net/", "https://capital.theojaffee.net/assets/page-test.js"]
