"""Starter skill-tree and portfolio-project planning rules."""

from tau_job_application.models import (
    MatchResult,
    ProjectPlan,
    RequirementStatus,
    SkillNode,
)


def build_skill_tree(match: MatchResult) -> list[SkillNode]:
    return [
        SkillNode(
            skill=item.skill,
            priority="high" if item.required else "medium",
            reason=(
                "Missing required skill from the target role"
                if item.required
                else "Missing preferred skill from the target role"
            ),
            prerequisites=[],  # TODO: add explicit prerequisite knowledge.
            completion_evidence=f"Build and test a small deliverable using {item.skill}",
        )
        for item in match.requirements
        if item.status == RequirementStatus.MISSING
    ]


def build_project_plans(skill_tree: list[SkillNode]) -> list[ProjectPlan]:
    """Return one seed plan; replace this with ranked plans as you iterate."""

    if not skill_tree:
        return []
    skills = [node.skill for node in skill_tree[:3]]
    return [
        ProjectPlan(
            title=f"Evidence project: {', '.join(skills)}",
            problem="Create a reviewable portfolio artifact for the highest-priority gaps.",
            skills_practised=skills,
            milestones=[
                "Write the problem statement and acceptance criteria",
                "Implement the smallest working version",
                "Add tests and usage documentation",
            ],
            deliverables=["Source code", "Automated tests", "Project README", "Demo output"],
            acceptance_tests=[
                "A new user can run the project from its README",
                "The tests exercise each claimed target skill",
            ],
            estimated_hours=8,
        )
    ]
