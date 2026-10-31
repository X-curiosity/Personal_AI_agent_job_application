from unittest.mock import patch

from scripts.export_public_jobs import export, extract_skills, role_area


class _EmptyStore:
    def list(self, enabled_only=False):
        return []


def _opening(identifier, location, title="Machine Learning Engineer"):
    return {
        "source_id": identifier, "title": title, "location": location,
        "url": f"https://jobs.example.com/{identifier}", "description": "Python and SQL for machine learning systems.",
        "source": "Ashby", "source_timestamp": "2026-10-25T00:00:00Z",
        "source_timestamp_kind": "published", "workplace_type": "Hybrid", "employment_type": "Full-time",
    }


def test_export_keeps_vacancy_locations_and_excludes_unresolved_places():
    rows = [
        _opening("one", "Paris, France • Dublin, Ireland"),
        _opening("two", "New York, United States"),
        _opening("three", "Remote"),
    ]
    with patch("tau_job_application.job_sources.JobSourceStore", return_value=_EmptyStore()), \
         patch("scripts.export_public_jobs.fetch_public_board_openings", return_value=rows):
        payload = export(limit=9)
    assert len(payload["jobs"]) == 3  # one valid opening per reviewed source
    job = payload["jobs"][0]
    assert [place["city"] for place in job["locations"]] == ["Paris", "Dublin"]
    assert all(place["precision"] == "city" for place in job["locations"])
    assert job["sourceTimestampKind"] == "published"
    assert payload["live"] is False


def test_export_reports_source_errors_without_blocking_other_boards():
    with patch("tau_job_application.job_sources.JobSourceStore", return_value=_EmptyStore()), \
         patch("scripts.export_public_jobs.fetch_public_board_openings", side_effect=[RuntimeError("offline"), [_opening("one", "Berlin, Germany")], [_opening("two", "London, United Kingdom")]]):
        payload = export(limit=9)
    assert len(payload["jobs"]) == 2
    assert len(payload["errors"]) == 1


def test_role_area_uses_title_not_company_industry():
    assert role_area("FPGA Design Engineer") == "Engineering"
    assert role_area("Product Manager") == "Product"
    assert role_area("Venture Capital Analyst") == "Operations"
    assert role_area("Data Center Hardware Engineer") == "Engineering"
    assert role_area("Data Centre Operations Manager") == "Operations"


def test_skill_extraction_uses_whole_terms():
    assert extract_skills("ongoing low-ego negotiate trust JavaScript go as you go go-to-market") == ["JavaScript"]
    assert extract_skills("Go, Rust, Java, C++, C#") == ["C++", "C#", "Rust", "Go", "Java"]
    assert extract_skills("Golang") == ["Go"]
