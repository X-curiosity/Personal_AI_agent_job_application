from pathlib import Path

import pytest

from tau_job_application.role_discovery import (
    UNKNOWN,
    CompanyFacts,
    DiscoveredOpening,
    RoleDiscoveryStore,
    RoleMatch,
    RoleQuery,
    SourceSnapshot,
    deduplicate_openings,
    match_opening,
    opening_role_locations,
    opening_sources,
    rank_openings,
    suggest_role_aliases,
)


def _facts(
    name: str,
    *,
    company_type: str = UNKNOWN,
    employee_band: str = UNKNOWN,
    funding_stage: str = UNKNOWN,
) -> CompanyFacts:
    known = any(value != UNKNOWN for value in (company_type, employee_band, funding_stage))
    return CompanyFacts(
        name=name,
        company_type=company_type,
        employee_band=employee_band,
        funding_stage=funding_stage,
        facts_source_url="https://example.com/company-facts" if known else None,
        verified_at="2026-10-04" if known else None,
    )


def _opening(
    title: str,
    company: CompanyFacts,
    *,
    source: str = "Greenhouse",
    identifier: str = "acme",
    external_id: str | None = None,
    url: str | None = None,
    description: str | None = None,
    location: str | None = "Berlin, Germany",
    workplace_type: str | None = None,
    employment_type: str | None = None,
    source_timestamp: str | None = None,
    source_timestamp_kind: str | None = None,
) -> DiscoveredOpening:
    return DiscoveredOpening(
        title=title,
        company=company,
        source=source,
        source_identifier=identifier,
        external_id=external_id,
        source_url=url,
        description=description,
        location=location,
        retrieved_at="2026-10-04T09:00:00+00:00",
        workplace_type=workplace_type,
        employment_type=employment_type,
        source_timestamp=source_timestamp,
        source_timestamp_kind=source_timestamp_kind,
    )


def test_role_ranking_is_deterministic_and_uses_aliases_and_profile_skills() -> None:
    query = RoleQuery(
        title="Backend Engineer",
        aliases=("Platform Engineer",),
        profile_skills=("Python", "Docker"),
    )
    closest = _opening(
        "Senior Backend Engineer",
        _facts("Acme"),
        external_id="1",
        url="https://jobs.example/acme/1",
        description="Build Python services in Docker.",
    )
    alias = _opening(
        "Platform Engineer",
        _facts("Beta"),
        external_id="2",
        url="https://jobs.example/beta/2",
        description="Build infrastructure with Python.",
    )
    unrelated = _opening(
        "Software Engineer",
        _facts("Gamma"),
        external_id="3",
        url="https://jobs.example/gamma/3",
        description="Python and Docker are useful.",
    )

    first = rank_openings(query, [alias, unrelated, closest])
    second = rank_openings(query, [closest, alias, unrelated])

    assert [match.opening.title for match in first] == ["Senior Backend Engineer", "Platform Engineer"]
    assert [match.opening.title for match in second] == ["Senior Backend Engineer", "Platform Engineer"]
    assert first[0].matched_profile_skills == ("Python", "Docker")
    assert first[1].matched_title_terms == ("Platform Engineer",)


def test_role_family_aliases_are_editable_transparent_baselines() -> None:
    assert suggest_role_aliases("GPU Software Engineer") == (
        "GPU Engineer",
        "CUDA Engineer",
        "Performance Engineer",
        "Systems Engineer",
    )


def test_company_and_source_filters_include_unknown_only_when_selected() -> None:
    query = RoleQuery(
        title="Backend Engineer",
        company_types=("Private", UNKNOWN),
        employee_bands=("51-200", UNKNOWN),
        funding_stages=("Series B", UNKNOWN),
        sources=("Greenhouse",),
    )
    private = _opening(
        "Backend Engineer",
        _facts("PrivateCo", company_type="Private", employee_band="51-200", funding_stage="Series B"),
        external_id="private",
        url="https://jobs.example/private",
    )
    unknown = _opening(
        "Backend Engineer",
        _facts("UnknownCo"),
        external_id="unknown",
        url="https://jobs.example/unknown",
    )
    wrong_funding = _opening(
        "Backend Engineer",
        _facts("SeriesACo", company_type="Private", employee_band="51-200", funding_stage="Series A"),
        external_id="series-a",
        url="https://jobs.example/series-a",
    )
    wrong_source = _opening(
        "Backend Engineer",
        _facts("LeverCo", company_type="Private", employee_band="51-200", funding_stage="Series B"),
        source="Lever",
        external_id="lever",
        url="https://jobs.example/lever",
    )

    matches = rank_openings(query, [private, unknown, wrong_funding, wrong_source])

    assert {match.opening.company.name for match in matches} == {"PrivateCo", "UnknownCo"}
    no_unknown = query.model_copy(update={"company_types": ("Private",), "employee_bands": ("51-200",), "funding_stages": ("Series B",)})
    assert [match.opening.company.name for match in rank_openings(no_unknown, [private, unknown])] == ["PrivateCo"]


def test_employee_band_filter_treats_display_dashes_as_plain_hyphens() -> None:
    query = RoleQuery(title="Backend Engineer", employee_bands=("51–200",))
    opening = _opening(
        "Backend Engineer",
        _facts("Acme", employee_band="51-200"),
        external_id="acme-1",
        url="https://jobs.example/acme/1",
    )

    assert [match.opening.company.name for match in rank_openings(query, [opening])] == ["Acme"]


def test_deduplication_uses_canonical_url_or_external_identity_and_keeps_provenance() -> None:
    company = _facts("Acme")
    by_greenhouse = _opening(
        "Backend Engineer",
        company,
        source="Greenhouse",
        identifier="acme",
        external_id="g-1",
        url="https://jobs.example/acme/1?utm_source=board",
        workplace_type="Hybrid",
        source_timestamp="2026-10-04T08:00:00Z",
        source_timestamp_kind="updated",
    )
    by_lever = _opening(
        "Backend Engineer",
        company,
        source="Lever",
        identifier="acme",
        external_id="l-9",
        url="https://jobs.example/acme/1#details",
        employment_type="Full-time",
        source_timestamp="2026-10-03T09:00:00Z",
        source_timestamp_kind="created",
    )
    by_external_id = _opening(
        "Platform Engineer",
        company,
        source="Greenhouse",
        identifier="acme",
        external_id="same-external-id",
        url=None,
    )
    repeat_external_id = _opening(
        "Platform Engineer",
        company,
        source="Greenhouse",
        identifier="acme",
        external_id="same-external-id",
        url=None,
    )

    merged = deduplicate_openings([by_greenhouse, by_lever, by_external_id, repeat_external_id])

    assert len(merged) == 2
    backend = next(opening for opening in merged if opening.title == "Backend Engineer")
    assert backend.canonical_url == "https://jobs.example/acme/1"
    assert opening_sources(backend) == ("Greenhouse", "Lever")
    assert len(backend.provenance) == 2
    # The displayed fields stay tied to the deterministically selected primary
    # Greenhouse observation; all other official source metadata is retained.
    assert backend.workplace_type == "Hybrid"
    assert backend.employment_type is None
    assert backend.source_timestamp_kind == "updated"
    lever_observation = next(item for item in backend.provenance if item.source == "Lever")
    assert lever_observation.employment_type == "Full-time"
    assert lever_observation.source_timestamp_kind == "created"
    assert len(next(opening for opening in merged if opening.title == "Platform Engineer").provenance) == 1


def test_discovered_opening_keeps_source_timestamp_semantics_without_breaking_older_records() -> None:
    legacy = DiscoveredOpening.model_validate({
        "title": "Backend Engineer",
        "company": _facts("Acme").model_dump(),
        "source": "Greenhouse",
    })
    assert legacy.workplace_type is None
    assert legacy.employment_type is None
    assert legacy.source_timestamp is None
    assert legacy.source_timestamp_kind is None

    with pytest.raises(ValueError, match="timestamp kind requires a source timestamp"):
        DiscoveredOpening(
            title="Backend Engineer",
            company=_facts("Acme"),
            source="Greenhouse",
            source_timestamp_kind="updated",
        )


def test_role_location_is_only_the_opening_location_not_company_footprint() -> None:
    opening = _opening(
        "Backend Engineer",
        _facts("Acme"),
        external_id="1",
        url="https://jobs.example/acme/1",
        location="Berlin, Germany",
    )
    match = match_opening(RoleQuery(title="Backend Engineer"), opening)

    assert opening_role_locations(opening) == ("Berlin, Germany",)
    assert match.role_locations == ("Berlin, Germany",)
    with pytest.raises(ValueError, match="opening location"):
        RoleMatch(
            opening=opening,
            score=100,
            title_score=100,
            profile_skill_score=0,
            role_locations=("Zurich, Switzerland",),
        )


def test_workplace_only_label_is_not_promoted_to_a_world_map_location() -> None:
    opening = _opening(
        "Backend Engineer",
        _facts("Acme"),
        external_id="hybrid-only",
        url="https://jobs.example/acme/hybrid-only",
        location="Hybrid",
    )

    match = match_opening(RoleQuery(title="Backend Engineer"), opening)

    assert opening.location == "Hybrid"
    assert opening_role_locations(opening) == ()
    assert match.role_locations == ()
    legacy_cached_match = RoleMatch(
        opening=opening,
        score=100,
        title_score=100,
        profile_skill_score=0,
        role_locations=("Hybrid",),
    )
    assert legacy_cached_match.role_locations == ()


def test_store_persists_latest_run_per_career_track_and_workspace(tmp_path: Path) -> None:
    store = RoleDiscoveryStore(tmp_path / "discovery.sqlite")
    query = RoleQuery(title="Backend Engineer", profile_skills=("Python",))
    opening = _opening(
        "Backend Engineer",
        _facts("Acme"),
        external_id="1",
        url="https://jobs.example/acme/1",
        description="Python services",
        workplace_type="Hybrid",
        source_timestamp="2026-10-04T08:00:00Z",
        source_timestamp_kind="updated",
    )
    matches = rank_openings(query, [opening])

    saved = store.save_latest_run(
        career_track_id="engineering",
        workspace_id="backend-role-page",
        query=query,
        matches=matches,
        sources=(SourceSnapshot(source="Greenhouse", identifier="acme", opening_count=1),),
        errors=("Lever board unavailable",),
    )
    restored = store.latest_run(career_track_id="engineering", workspace_id="backend-role-page")

    assert restored == saved
    assert restored is not None
    assert restored.matches[0].opening.external_id == "1"
    assert restored.matches[0].opening.workplace_type == "Hybrid"
    assert restored.matches[0].opening.source_timestamp == "2026-10-04T08:00:00Z"
    assert restored.matches[0].opening.source_timestamp_kind == "updated"
    assert restored.sources[0].identifier == "acme"
    assert restored.errors == ("Lever board unavailable",)
    assert store.latest_run(career_track_id="another-track", workspace_id="backend-role-page") is None

    replacement = store.save_latest_run(
        career_track_id="engineering",
        workspace_id="backend-role-page",
        query=RoleQuery(title="Data Engineer"),
        matches=(),
        sources=(SourceSnapshot(source="Greenhouse", identifier="acme", opening_count=0),),
    )
    assert store.latest_run(career_track_id="engineering", workspace_id="backend-role-page") == replacement
