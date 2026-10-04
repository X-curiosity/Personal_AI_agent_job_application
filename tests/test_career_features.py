from tau_job_application.career import contact_research_plan, parse_contact_leads
from tau_job_application.interview import build_interview_questions, evaluate_answer
from tau_job_application.pipeline import analyze_texts
from tau_job_application.planning import build_project_plans


CANDIDATE = """Name: Alex
Headline: Backend developer
Skills: Python, SQL
Experience: Built a small data API with tests.
"""
JOB = """Title: Platform Engineer
Company: Acme
Required skills: Python, Docker
Preferred skills: AWS
"""


def test_analysis_has_evidence_bounded_cv_and_project_outputs() -> None:
    result = analyze_texts(CANDIDATE, JOB)

    assert result.match.score == 40
    assert result.cv_score is not None
    assert "Docker" in [node.skill for node in result.skill_tree]
    assert result.tailored_resume is not None
    assert "Docker" not in result.tailored_resume.relevant_skills
    assert result.project_plans[0].acceptance_tests


def test_standout_project_plans_are_limited_to_one_or_two_real_gaps() -> None:
    result = analyze_texts(
        "Name: Alex\nSkills: Python",
        """Title: Platform Engineer
Company: Acme
Required skills: Python, Docker, AWS, Kubernetes, SQL
""",
    )

    assert len(result.project_plans) == 2
    assert result.project_plans[0].skills_practised == ["Docker"]
    assert result.project_plans[1].skills_practised == ["Docker", "AWS", "Kubernetes"]
    assert all(plan.title != "Production-readiness extension" for plan in result.project_plans)

    remaining_after_project_proof = build_project_plans(
        result.skill_tree,
        covered_skills=("docker",),
    )
    assert remaining_after_project_proof[0].skills_practised == ["AWS"]
    assert len(remaining_after_project_proof) == 2
    assert build_project_plans(
        result.skill_tree,
        covered_skills=("Docker", "AWS", "Kubernetes", "SQL"),
    ) == []

    fully_evidenced = analyze_texts(
        "Name: Alex\nSkills: Python, Docker",
        "Required skills: Python, Docker",
        job_title="Platform Engineer",
        company="Acme",
    )
    assert fully_evidenced.project_plans == []


def test_contact_plan_does_not_generate_an_email_address() -> None:
    leads = parse_contact_leads("Ada Lovelace | Engineering Manager | https://example.com/ada")
    plan = contact_research_plan("Acme", "Platform Engineer", leads, "first.last@acme.com")

    assert plan.leads[0].name == "Ada Lovelace"
    assert plan.email_pattern == "first.last@acme.com"
    assert plan.leads[0].public_email is None
    assert "do not generate" in plan.safety_note


def test_interview_feedback_is_structured() -> None:
    result = analyze_texts(CANDIDATE, JOB)
    question = build_interview_questions(result.candidate, result.job)[1]
    feedback = evaluate_answer(question, "I built a project for a user. I tested it and measured the result. I learned to improve the trade-off.")

    assert feedback.score > 0
    assert feedback.question_id == question.id
