from tau_job_application.authenticity import check_authenticity
from tau_job_application.parsing import parse_candidate_text


def test_generic_phrases_are_flagged() -> None:
    cv = parse_candidate_text(
        "Name: Alex\nSkills: Python\nExperience: Passionate about building results-oriented teams."
    )
    report = check_authenticity(cv)

    assert report.status == "needs_review"
    assert any("passionate about" == hit.phrase for hit in report.generic_phrases)
    assert any("results-oriented" == hit.phrase for hit in report.generic_phrases)


def test_unsupported_claim_blocks_cv() -> None:
    cv = parse_candidate_text(
        "Name: Alex\nSkills: Python\nExperience: Built a hyperloop from scratch in one weekend."
    )
    report = check_authenticity(cv)

    assert report.status == "blocked"
    assert any("hyperloop" in claim.claim for claim in report.unsupported_claims)


def test_metric_claim_is_accepted() -> None:
    cv = parse_candidate_text(
        "Name: Alex\nSkills: Python\nExperience: Built a Python service that reduced latency by 40% for 10,000 daily users."
    )
    report = check_authenticity(cv)

    assert report.status == "ready"
    assert not report.unsupported_claims
    assert not report.weak_metrics
