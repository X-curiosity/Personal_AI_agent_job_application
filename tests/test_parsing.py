from tau_job_application.parsing import parse_candidate_text, parse_job_text


def test_parse_candidate_and_job() -> None:
    candidate = parse_candidate_text("Name: Alex\nSkills: Python, SQL")
    job = parse_job_text(
        "Title: Engineer\nCompany: Example\nRequired skills: Python, Docker"
    )

    assert candidate.skills == ["Python", "SQL"]
    assert job.title == "Engineer"
    assert len(job.requirements) == 2
    assert candidate.evidence[0].source == "candidate"
