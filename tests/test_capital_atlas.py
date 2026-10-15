import pytest

from tau_job_application.capital_atlas import fetch_capital_atlas, parse_capital_atlas

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
