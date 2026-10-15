import pytest

from tau_job_application.eligibility import (
    DISCLAIMER,
    FREE_MOVEMENT_BLOC,
    ResidencyProfile,
    ResidencyStore,
    eligibility_checklist,
    normalize_country,
)


def test_normalize_country_aliases_and_unknown():
    assert normalize_country("usa") == "United States"
    assert normalize_country(" UK ") == "United Kingdom"
    assert normalize_country("germany") == "Germany"
    assert normalize_country("Narnia") is None
    assert normalize_country("") is None


def test_profile_requires_known_countries():
    with pytest.raises(ValueError):
        ResidencyProfile(citizenships=("Narnia",), residence_country="France")
    with pytest.raises(ValueError):
        ResidencyProfile(citizenships=("France",), residence_country="Narnia")
    profile = ResidencyProfile(citizenships=["france", "FRANCE"], residence_country="france")
    assert profile.citizenships == ("France",)


def test_domestic_citizen_pathway():
    profile = ResidencyProfile(citizenships=("France",), residence_country="France")
    result = eligibility_checklist(profile, "France")
    assert result.pathway == "domestic"
    assert "no work authorization" in result.summary.lower()
    assert result.disclaimer == DISCLAIMER


def test_domestic_resident_without_citizenship_must_prove_right_to_work():
    profile = ResidencyProfile(citizenships=("Brazil",), residence_country="Germany")
    result = eligibility_checklist(profile, "Germany")
    assert result.pathway == "domestic"
    assert any("permit" in item.title.lower() or "right to work" in item.title.lower() for item in result.items)
    assert any(item.documents for item in result.items)


def test_free_movement_bloc_needs_no_work_visa():
    assert "Switzerland" in FREE_MOVEMENT_BLOC
    profile = ResidencyProfile(citizenships=("France",), residence_country="France")
    result = eligibility_checklist(profile, "Switzerland")
    assert result.pathway == "free_movement"
    assert "without a work visa" in result.summary
    sources = [item.official_source for item in result.items if item.official_source]
    assert sources and all(source.startswith("https://") for source in sources)


def test_swiss_citizen_gets_free_movement_into_eu():
    profile = ResidencyProfile(citizenships=("Switzerland",), residence_country="Switzerland")
    result = eligibility_checklist(profile, "Germany")
    assert result.pathway == "free_movement"


def test_existing_permit_pathway_takes_priority_over_sponsorship():
    profile = ResidencyProfile(citizenships=("India",), residence_country="India", work_permits=("Canada",))
    result = eligibility_checklist(profile, "Canada")
    assert result.pathway == "existing_permit"
    assert "covers this new employer" in result.summary


def test_sponsorship_pathway_has_country_notes_and_documents():
    profile = ResidencyProfile(citizenships=("France",), residence_country="France")
    result = eligibility_checklist(profile, "United States")
    assert result.pathway == "sponsorship"
    assert any("H-1B" in item.detail for item in result.items)
    documents = [document for item in result.items for document in item.documents]
    assert any("Passport" in document for document in documents)
    uk = eligibility_checklist(profile, "United Kingdom")
    assert any("Certificate of Sponsorship" in item.detail for item in uk.items)
    generic = eligibility_checklist(profile, "Japan")
    assert generic.pathway == "sponsorship"
    assert all(item.official_source for item in generic.items)


def test_unknown_job_country_is_rejected():
    profile = ResidencyProfile(citizenships=("France",), residence_country="France")
    with pytest.raises(ValueError):
        eligibility_checklist(profile, "Narnia")


def test_residency_store_roundtrip(tmp_path):
    store = ResidencyStore(tmp_path / "db.sqlite")
    assert store.get("track") is None
    profile = ResidencyProfile(citizenships=("Canada", "France"), residence_country="Canada", work_permits=("United States",))
    store.save("track", profile)
    loaded = store.get("track")
    assert loaded == profile
    store.save("track", ResidencyProfile(citizenships=("France",), residence_country="France"))
    assert store.get("track").citizenships == ("France",)
    assert store.get("other-track") is None
