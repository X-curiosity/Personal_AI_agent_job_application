import json

import pytest

from tau_job_application.company_catalog import (
    CatalogCompany, CompanyCatalogStore, fetch_yc_hiring, parse_companies_marketcap,
    parse_yc_hiring,
)


CMC_HTML = """
<table><tbody><tr><td></td><td class="rank-td" data-sort="1">1</td>
<td><a href="/nvidia/marketcap/"><div class="company-name">NVIDIA</div><div class="company-code"><span></span>NVDA</div></a></td>
<td data-sort="5">$5.2 T</td><td></td><td></td><td></td><td><span class="responsive-hidden">USA</span></td></tr></tbody></table>
"""


def test_parse_companies_marketcap_preserves_source_and_market_fields():
    company = parse_companies_marketcap(CMC_HTML, limit=1)[0]
    assert company.name == "NVIDIA"
    assert company.rank == 1
    assert company.ticker == "NVDA"
    assert company.country == "USA"
    assert company.source_url == "https://companiesmarketcap.com/nvidia/marketcap/"


def test_parse_yc_hiring_filters_and_bounds():
    payload = [{"id": 5, "name": "CircuitHub", "slug": "circuithub", "url": "https://www.ycombinator.com/companies/circuithub",
                "website": "https://circuithub.com", "isHiring": True, "tags": ["Hardware"], "team_size": 58,
                "stage": "Early", "batch": "Winter 2012", "industry": "Industrials"}]
    assert parse_yc_hiring(payload, query="hardware")[0].employee_band == "51-200"
    assert parse_yc_hiring(payload, query="healthcare") == []
    with pytest.raises(ValueError):
        parse_yc_hiring(payload, limit=101)


def test_fetch_yc_uses_only_fixed_endpoint_shape():
    payload = [{"name": "A", "slug": "a", "url": "https://www.ycombinator.com/companies/a", "isHiring": True}]
    seen = []
    def fetcher(url, *, expected_host):
        seen.append((url, expected_host))
        return json.dumps(payload).encode()
    assert fetch_yc_hiring(limit=1, fetcher=fetcher)[0].name == "A"
    assert seen == [("https://yc-oss.github.io/api/companies/hiring.json", "yc-oss.github.io")]


def test_store_upserts_catalog_and_requires_reviewed_supported_board(tmp_path):
    store = CompanyCatalogStore(tmp_path / "catalog.sqlite")
    company = CatalogCompany(source="YC community API", source_key="circuithub",
        source_url="https://www.ycombinator.com/companies/circuithub", name="CircuitHub",
        company_type="Startup", hiring=True, funding_stage="Early", employee_band="51-200")
    assert store.import_companies([company]) == 1
    assert store.import_companies([company.model_copy(update={"summary": "Updated"})]) == 1
    rows = store.list_companies(hiring_only=True)
    assert len(rows) == 1 and rows[0]["company"].summary == "Updated"
    with pytest.raises(ValueError):
        store.register_board(rows[0]["id"], "Workday", "example")
    board = store.register_board(rows[0]["id"], "Greenhouse", "circuithub")
    assert board.board_url == "https://boards.greenhouse.io/circuithub"
    assert store.boards()[0].company.name == "CircuitHub"
