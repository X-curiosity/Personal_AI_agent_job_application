from pathlib import Path

import pytest

from tau_job_application.matching import calculate_match
from tau_job_application.parsing import parse_candidate_text, parse_job_text
from tau_job_application.pipeline import analyze_texts, render_markdown
from tau_job_application.requirement_memory import RequirementMemory
from tau_job_application.requirements import save_requirement_review


def skills(text, **kwargs):
    job = parse_job_text(text, **kwargs)
    return {r.skill: r for r in job.requirements}


def test_prose_without_skill_headers():
    result = skills("You are experienced with Python and SQL. You are comfortable building APIs.\n"
                    "Projects involving Docker are a plus.")
    assert result["Python"].importance == "required"
    assert result["SQL"].importance == "required"
    assert result["API development"].importance == "required"
    assert result["Docker"].importance == "preferred"
    assert all(r.needs_review for r in result.values())


def test_preferred_heading_and_mixed_clauses():
    result = skills("Requirements\nPython is required, and Docker is a plus.\n"
                    "Nice to have:\nAWS\nTerraform\nResponsibilities\nBuild data pipelines.")
    assert result["Python"].required
    assert not result["Docker"].required
    assert not result["AWS"].required
    assert not result["Terraform"].required
    assert result["Data pipelines"].required


def test_explicit_and_implicit_both_retained():
    result = skills("Required skills: Python\nYou should be comfortable with SQL.\nPreferred skills: AWS")
    assert set(result) == {"Python", "SQL", "AWS"}
    assert result["Python"].extraction_method == "explicit"


@pytest.mark.parametrize("negative", [
    "Docker is not required.", "No experience with Docker required.",
    "We will teach Docker.", "You don't need Docker.",
])
def test_negated_requirements_excluded(negative):
    assert set(skills("Experienced with Python. " + negative)) == {"Python"}


def test_unknown_technology_captured_for_review():
    result = skills("Experienced with ClickHouse and comfortable with dbt.")
    assert {"ClickHouse", "dbt"} <= result.keys()
    assert result["ClickHouse"].extraction_method == "phrase"
    assert result["ClickHouse"].needs_review


def test_context_not_invented_vendor():
    result = skills("You will build APIs and work with relational databases.")
    assert set(result) == {"API development", "Relational databases"}
    assert "PostgreSQL" not in result


def test_background_excluded_and_plain_go_not_language():
    result = skills("About us\nOur clients use AWS.\nRequirements\nWe go to conferences.\nExperienced with Python.")
    assert set(result) == {"Python"}


def test_ambiguous_stack_mentions_not_scored():
    job = parse_job_text("Our stack uses Python.")
    assert job.requirements[0].importance == "uncertain"
    candidate = parse_candidate_text("Name: Alex\nSkills: Python")
    match = calculate_match(candidate, job)
    assert match.score == 0
    assert match.requirements[0].status == "unknown"


def test_exact_evidence_and_distinct_language_ids():
    text = "Required skills: C, C++, Python; SQL\nComfortable with Node.js."
    job = parse_job_text(text)
    evidence = {e.id: e for e in job.evidence}
    assert len({r.evidence_id for r in job.requirements}) == len(job.requirements)
    for r in job.requirements:
        assert evidence[r.evidence_id].quote in text
    assert {"C", "C++", "Node.js", "Python", "SQL"} == {r.skill for r in job.requirements}


def test_review_persists_but_not_across_different_descriptions(tmp_path: Path):
    path = tmp_path / "memory.sqlite"
    memory = RequirementMemory(path)
    text = "Comfortable with event-driven services."
    save_requirement_review(text, [{"skill": "Event-driven architecture", "importance": "preferred", "quote": text}], memory)
    result = skills(text, memory=RequirementMemory(path))
    assert result["Event-driven architecture"].importance == "preferred"
    assert result["Event-driven architecture"].extraction_method == "reviewed"
    assert memory.reviewed(text + " Changed.") is None
    memory.forget_review(text)
    assert memory.reviewed(text) is None


def test_learning_explicit_only_reusable_reversible(tmp_path):
    memory = RequirementMemory(tmp_path / "memory.sqlite")
    quote = "Comfortable with event-driven services."
    with pytest.raises(ValueError):
        memory.learn_alias("event-driven services", "Event-driven architecture", source_quote=quote, user_confirmed=False)
    with pytest.raises(ValueError):
        memory.learn_alias("invented phrase", "Skill", source_quote=quote, user_confirmed=True)
    for _ in range(3):
        skills(quote, memory=memory)
    assert memory.aliases() == {}  # More documents alone must not silently create rules.
    memory.learn_alias("event-driven services", "Event-driven architecture", source_quote=quote, user_confirmed=True)
    fresh = RequirementMemory(memory.path)
    required = skills("Experienced with event-driven services.", memory=fresh)
    optional = skills("Projects involving event-driven services are preferred.", memory=fresh)
    assert required["Event-driven architecture"].importance == "required"
    assert optional["Event-driven architecture"].importance == "preferred"
    assert optional["Event-driven architecture"].extraction_method == "learned"
    fresh.forget_alias("event-driven services")
    assert not fresh.aliases()


def test_invalid_review_cannot_overwrite_valid_review(tmp_path):
    memory = RequirementMemory(tmp_path / "memory.sqlite")
    text = "Experienced with Python."
    rows = [{"skill": "Python", "importance": "required", "quote": text}]
    save_requirement_review(text, rows, memory)
    with pytest.raises(ValueError):
        save_requirement_review(text, [{"skill": "Docker", "importance": "required", "quote": "not in the job"}], memory)
    assert memory.reviewed(text)[0][0].skill == "Python"
    with pytest.raises(ValueError):
        save_requirement_review(text, [], memory)


def test_review_changes_analysis_not_candidate_evidence(tmp_path):
    memory = RequirementMemory(tmp_path / "memory.sqlite")
    text = "Comfortable with databases."
    save_requirement_review(text, [{"skill": "Database design", "importance": "required", "quote": text}], memory)
    result = analyze_texts("Name: Alex\nSkills: Python", text, requirement_memory=memory)
    assert result.job.requirements[0].skill == "Database design"
    assert "Database design" not in result.candidate.skills
    assert text in render_markdown(result)
