from tau_job_application.matching import calculate_match
from tau_job_application.parsing import parse_candidate_text, parse_job_text


def test_match_score_is_deterministic() -> None:
    candidate = parse_candidate_text("Name: Alex\nSkills: Python, SQL")
    job = parse_job_text(
        "Title: Engineer\nCompany: Example\nRequired skills: Python, Docker\n"
        "Preferred skills: SQL"
    )

    result = calculate_match(candidate, job)

    assert result.score == 60
    assert result.required_score == 0.5
    assert result.preferred_score == 1.0
