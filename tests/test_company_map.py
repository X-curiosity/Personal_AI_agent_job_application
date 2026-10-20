from tau_job_application.city_coordinates import geocode_location
from tau_job_application.company_map_ui import build_map_points
from tau_job_application.match_onboarding import MatchCompanyFacts, MatchPreferences


def test_city_level_resolution():
    result = geocode_location("San Francisco, CA, USA")
    assert result is not None and result.precision == "city"
    assert abs(result.latitude - 37.7749) < 0.01 and abs(result.longitude - (-122.4194)) < 0.01
    assert geocode_location("Berlin, Germany").precision == "city"
    assert geocode_location("Sophia Antipolis, France").precision == "city"
    assert geocode_location("Kraków, Poland").precision == "city"
    assert geocode_location("Tel Aviv, Israel").precision == "city"
    # Bare-city alias when the string carries no country.
    assert geocode_location("Bangalore").precision == "city"
    assert geocode_location("Zürich").precision == "city"


def test_country_fallback_is_labeled_country_level():
    result = geocode_location("USA")
    assert result is not None and result.precision == "country"
    assert geocode_location("Germany").precision == "country"
    assert geocode_location("Some Small Town, Germany").precision == "country"


def test_unmappable_locations_return_none():
    assert geocode_location("Remote") is None
    assert geocode_location("Remote (Global)") is None
    assert geocode_location("Remote - EMEA") is None
    assert geocode_location("") is None
    assert geocode_location(None) is None
    assert geocode_location("Atlantis") is None


def facts(name, stage, locations, signal="directory_flag"):
    return MatchCompanyFacts(
        name=name, stage_group=stage, industry="Fintech", locations=locations,
        hiring_signal=signal, source_label="test", stage_basis="test",
    )


def test_build_map_points_separates_unmapped_and_styles_by_precision():
    points, unmapped = build_map_points([
        facts("City Co", "early", "Berlin, Germany", signal="live_openings"),
        facts("Country Co", "big", "Germany"),
        facts("Remote Co", "growth", "Remote"),
    ])
    assert [point["name"] for point in points] == ["City Co", "Country Co"]
    assert unmapped == ["Remote Co"]
    city = points[0]
    assert city["radius"] == 26_000  # live board gets the stronger pin
    assert "city-level" in city["precision"]
    country = points[1]
    assert country["color"][3] == 90  # country-level discs stay soft
    assert country["radius"] == 90_000


def test_build_map_points_applies_match_preferences():
    prefs = MatchPreferences(career_track_id="t", stage_groups=("early",))
    points, _ = build_map_points([
        facts("Early Co", "early", "Berlin, Germany"),
        facts("Big Co", "big", "USA"),
    ], prefs)
    assert [point["name"] for point in points] == ["Early Co"]
