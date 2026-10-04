from tau_job_application.company_explorer import company_footprint, detected_profile_skills, recommend_companies


def test_company_explorer_uses_only_skills_found_in_the_supplied_cv() -> None:
    cv = """Name: Maya
Skills: Python, CUDA, PyTorch, C++
Experience: Built an accelerated inference prototype.
"""

    recommendations = recommend_companies(cv, regions=("North America", "Europe"), limit=None)

    nvidia = next(item for item in recommendations if item.company == "NVIDIA")
    assert nvidia.matching_skills == ("Python", "C++", "CUDA", "PyTorch")
    assert nvidia.region == "North America"
    assert all(item.region in {"North America", "Europe"} for item in recommendations)
    assert all(item.matching_skills for item in recommendations)


def test_company_explorer_returns_no_suggestions_without_a_cv() -> None:
    assert detected_profile_skills("") == ()
    assert recommend_companies("") == []


def test_company_explorer_returns_a_deterministic_limited_result_set() -> None:
    cv = "Skills: Python, SQL, AWS, Docker, Kubernetes"

    recommendations = recommend_companies(cv, limit=3)

    assert len(recommendations) == 3
    assert recommendations == recommend_companies(cv, limit=3)
    assert all(item.careers_url.startswith("https://") for item in recommendations)


def test_company_footprint_keeps_multiple_source_linked_hubs_for_one_company() -> None:
    hubs = company_footprint("NVIDIA")

    assert [hub.city for hub in hubs] == ["Santa Clara", "Yokneam", "Bengaluru"]
    assert sum("HQ" in hub.site_type for hub in hubs) == 1
    assert {hub.focus for hub in hubs} >= {
        "Corporate headquarters; company-wide accelerated-computing platform context.",
        "Networking systems for AI data centers, including switches, NICs, and DPUs.",
    }
    assert all(hub.source_url.startswith("https://") for hub in hubs)


def test_company_without_a_curated_footprint_keeps_its_selected_explorer_hub() -> None:
    hubs = company_footprint("Mistral AI")

    assert len(hubs) == 1
    assert hubs[0].site_type == "Selected explorer hub"
    assert hubs[0].verification_note
