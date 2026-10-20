import pytest

from tau_job_application.company_catalog import CatalogCompany, CompanyCatalogStore
from tau_job_application.hiring_index import HiringEntry, HiringIndexStore
from tau_job_application.match_onboarding import (
    MatchCompanyFacts,
    MatchPreferenceStore,
    MatchPreferences,
    classify_stage,
    company_matches,
    gather_match_candidates,
    match_summary,
)


def prefs(**overrides):
    base = dict(career_track_id="track", role_areas=("Engineering",), experience="3_5", work_styles=("remote",))
    return MatchPreferences(**{**base, **overrides})


def facts(**overrides):
    base = dict(name="Example", stage_group="growth", industry="Fintech", locations="Berlin, Germany",
                hiring_signal="live_openings", source_label="Live board", stage_basis="team ~120")
    return MatchCompanyFacts(**{**base, **overrides})


def test_classify_stage_uses_the_facts_we_hold():
    assert classify_stage(source="CompaniesMarketCap")[0] == "big"
    assert classify_stage(market_cap="$5.2 T")[0] == "big"
    assert classify_stage(company_type="Public company")[0] == "big"
    assert classify_stage(team_size=12)[0] == "early"
    assert classify_stage(team_size=120)[0] == "growth"
    assert classify_stage(team_size=400)[0] == "scaleup"
    assert classify_stage(team_size=5000)[0] == "big"
    assert classify_stage(employee_band="51-200")[0] == "growth"
    assert classify_stage(employee_band="10000+")[0] == "big"
    assert classify_stage(funding_stage="Seed")[0] == "early"
    assert classify_stage(funding_stage="Series B")[0] == "growth"
    assert classify_stage(funding_stage="Series E")[0] == "scaleup"
    assert classify_stage(funding_stage="IPO")[0] == "big"
    # The deciding fact is always reported for honest display.
    assert classify_stage(team_size=120)[1] == "team ~120"
    assert classify_stage(source="CompaniesMarketCap")[1] == "public listing"


def test_company_matches_stage_industry_location():
    company = facts()
    assert company_matches(company, prefs(stage_groups=("growth",)))
    assert not company_matches(company, prefs(stage_groups=("early",)))
    assert company_matches(company, prefs(industries=("fint",)))
    assert company_matches(company, prefs(industries=("Fintech",)))
    assert not company_matches(company, prefs(industries=("Climate",)))
    # Picked industries exclude companies whose industry is unknown.
    assert not company_matches(facts(industry=None), prefs(industries=("Fintech",)))
    assert company_matches(company, prefs(location_mode="country", country="Germany"))
    assert not company_matches(company, prefs(location_mode="country", country="France"))
    assert company_matches(company, prefs(location_mode="cities", target_cities=("Berlin",)))
    assert not company_matches(company, prefs(location_mode="cities", target_cities=("Paris",)))


def test_role_areas_and_experience_never_exclude_a_company():
    company = facts()
    assert company_matches(company, prefs(role_areas=("Legal",), experience="lt1"))
    assert company_matches(company, prefs(role_areas=(), experience=""))


def test_for_step_keeps_later_filters_out_of_the_live_count():
    p = prefs(stage_groups=("growth",), industries=("Climate",), location_mode="country", country="Germany")
    company = facts()  # growth · Fintech · Berlin, Germany
    # Full preferences reject the company on the industry filter...
    assert not company_matches(company, p)
    # ...but at the "roles" step no filter applies yet...
    assert company_matches(company, p.for_step("roles"))
    # ...at the "stage" step stage and location apply but industry does not...
    assert company_matches(company, p.for_step("stage"))
    # ...and only at "industry" does the Climate pick take effect.
    assert not company_matches(company, p.for_step("industry"))
    # A stage mismatch is already enforced at the stage step.
    assert not company_matches(facts(stage_group="big"), p.for_step("stage"))
    with pytest.raises(ValueError):
        p.for_step("nope")


def test_store_roundtrip_and_validation(tmp_path):
    store = MatchPreferenceStore(tmp_path / "db.sqlite")
    assert store.load("track") is None
    saved = store.save(prefs(steps_done=("roles", "experience")))
    assert saved.updated_at
    loaded = store.load("track")
    assert loaded.role_areas == ("Engineering",) and loaded.steps_done == ("roles", "experience")
    store.save(prefs(experience="lt1"))
    assert store.load("track").experience == "lt1"
    with pytest.raises(ValueError):
        store.save(prefs(steps_done=("nonsense",)))
    with pytest.raises(ValueError):
        store.save(prefs(location_mode="planet"))


def _seed_stores(tmp_path):
    database = tmp_path / "db.sqlite"
    hiring = HiringIndexStore(database)
    hiring.save_run([
        HiringEntry(company_key="board:Greenhouse:figma", name="Figma", signal="live_openings",
                    team_size=1400, industry="Design", locations="San Francisco, USA",
                    source_label="Live Greenhouse board", source_url="https://boards.greenhouse.io/figma"),
        HiringEntry(company_key="yc:alpha", name="Alpha AI", signal="directory_flag",
                    team_size=30, industry="Fintech", locations="Berlin, Germany",
                    source_label="YC directory flag (unverified)", source_url="https://www.ycombinator.com/companies/alpha"),
    ])
    catalog = CompanyCatalogStore(database)
    catalog.import_companies([
        CatalogCompany(source="CompaniesMarketCap", source_key="nvidia", name="NVIDIA",
                       source_url="https://companiesmarketcap.com/nvidia/marketcap/",
                       industry="Semiconductors", country="USA", market_cap="$5.2 T", hiring=True),
        CatalogCompany(source="YC community API", source_key="alpha", name="Alpha AI",
                       source_url="https://www.ycombinator.com/companies/alpha", hiring=True),
        CatalogCompany(source="YC community API", source_key="quiet", name="Quiet Co",
                       source_url="https://www.ycombinator.com/companies/quiet", hiring=False),
    ])
    return hiring, catalog


def test_gather_deduplicates_and_keeps_only_hiring(tmp_path):
    hiring, catalog = _seed_stores(tmp_path)
    candidates = gather_match_candidates(hiring, catalog)
    names = [facts.name for facts in candidates]
    assert names.count("Alpha AI") == 1  # index row wins over the catalogue duplicate
    assert "Quiet Co" not in names  # not hiring
    assert {facts.stage_group for facts in candidates} == {"big", "early"}
    nvidia = next(facts for facts in candidates if facts.name == "NVIDIA")
    assert nvidia.stage_group == "big" and nvidia.stage_basis == "public listing"
    # Live-verified companies sort first.
    assert candidates[0].hiring_signal == "live_openings"


def test_match_summary_counts_live_separately(tmp_path):
    hiring, catalog = _seed_stores(tmp_path)
    candidates = gather_match_candidates(hiring, catalog)
    summary = match_summary(candidates, prefs(stage_groups=("big",)))
    assert summary == {"companies": 2, "live": 1}  # Figma + NVIDIA; only Figma is board-verified
