import pytest

from tau_job_application.skill_decision import (
    SkillDecision,
    decide_skill_match,
    refine_requirement_matches,
    _similarity,
)


def test_exact_and_alias_pairs_match():
    assert decide_skill_match("Python", "python").verdict == "match"
    assert decide_skill_match("Kubernetes", "k8s").verdict == "match"
    assert decide_skill_match("Amazon Web Services", "AWS").verdict == "match"
    assert decide_skill_match("PostgreSQL", "Postgres").method == "alias"


def test_quantity_words_do_not_block_a_match():
    decision = decide_skill_match("Advanced Python experience", "Python")
    assert decision.verdict == "match"


def test_java_and_javascript_stay_undecided_not_matched():
    # The classic false positive: a bare prefix must not silently become a match.
    decision = decide_skill_match("Java", "JavaScript")
    assert decision.verdict != "match"
    assert decision.probability < 0.62


def test_contained_longer_label_matches():
    assert decide_skill_match("SQL", "PostgreSQL").verdict == "match"


def test_unrelated_skills_do_not_match():
    decision = decide_skill_match("Kubernetes", "Copywriting")
    assert decision.verdict == "no_match"
    assert decision.probability <= 0.42


def test_similarity_is_deterministic_and_explainable():
    first = _similarity("Machine Learning", "ML")
    second = _similarity("Machine Learning", "ML")
    assert first == second
    assert first[0] >= 0.62 and first[2]


def test_resolver_only_consulted_for_ambiguous_pairs():
    consulted: list[tuple[str, str]] = []

    def resolver(left: str, right: str) -> float | None:
        consulted.append((left, right))
        return 0.9

    confident = decide_skill_match("Kubernetes", "k8s", resolver=resolver)
    assert confident.method == "alias" and consulted == []

    ambiguous = decide_skill_match("React", "React Native", resolver=resolver)
    assert consulted == [("React", "React Native")]
    assert ambiguous.method == "jev" and ambiguous.verdict == "match"


def test_failing_resolver_keeps_the_local_verdict():
    def broken(left: str, right: str) -> float | None:
        return None

    decision = decide_skill_match("React", "React Native", resolver=broken)
    assert decision.method != "jev"


class _Requirement:
    def __init__(self, skill: str, required: bool = True, importance: str = "stated") -> None:
        self.skill = skill
        self.required = required
        self.importance = importance


def test_refinement_recognises_synonyms_and_mirrors_canonical_weighting():
    requirements = [
        _Requirement("Kubernetes"),
        _Requirement("Python"),
        _Requirement("JavaScript"),
        _Requirement("Copywriting", required=False),
    ]
    refinement = refine_requirement_matches(["k8s", "Python", "Java"], requirements)
    # k8s→Kubernetes and Python→Python match; JavaScript→Java and Copywriting do not.
    assert refinement.refined_score == 53  # required 2/3 * 0.8 + preferred 0/1 * 0.2
    assert "Kubernetes" in refinement.changed_requirements
    assert refinement.source == "local"


def test_refinement_reports_ambiguity_and_escalation():
    requirements = [_Requirement("React"), _Requirement("Python")]

    def resolver(left: str, right: str) -> float | None:
        return 0.8

    refinement = refine_requirement_matches(["React Native", "Python"], requirements, resolver=resolver)
    assert refinement.escalated_to_jev >= 1
    assert refinement.source == "jev"
    assert refinement.refined_score == 100


def test_refinement_without_skills_or_requirements_is_safe():
    assert refine_requirement_matches([], [_Requirement("Python")]).refined_score == 0
    assert refine_requirement_matches(["Python"], []).refined_score == 0
    assert refine_requirement_matches(["Python"], [_Requirement("Python", importance="uncertain")]).refined_score == 0


def test_decision_model_is_bounded():
    for left, right in [("Python", "Deep Learning"), ("SQL", "Rust"), ("AWS", "Azure")]:
        decision = decide_skill_match(left, right)
        assert isinstance(decision, SkillDecision)
        assert 0.0 <= decision.probability <= 1.0
