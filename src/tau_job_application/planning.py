"""Deterministic gap-to-learning and gap-to-portfolio planning."""

from tau_job_application.models import LearningResource, MatchResult, ProjectPlan, RequirementStatus, SkillNode

KNOWLEDGE = {
    "docker": (["Linux", "Command line"], [
        LearningResource(title="Docker getting started", kind="documentation", url="https://docs.docker.com/get-started/", note="Build, run, and publish a small container."),
        LearningResource(title="Docker Deep Dive", kind="book", note="Use the container, image, and networking chapters."),
    ]),
    "aws": (["Cloud fundamentals", "Networking", "IAM"], [
        LearningResource(title="AWS Cloud Practitioner Essentials", kind="course", url="https://explore.skillbuilder.aws/learn", note="Start with identity, networking, and deployment concepts."),
        LearningResource(title="AWS Well-Architected Framework", kind="documentation", url="https://docs.aws.amazon.com/wellarchitected/latest/framework/", note="Use it as a production review checklist."),
    ]),
    "kubernetes": (["Docker", "Linux", "Networking"], [
        LearningResource(title="Kubernetes Basics", kind="course", url="https://kubernetes.io/docs/tutorials/kubernetes-basics/", note="Complete the deployment and service exercises."),
        LearningResource(title="Kubernetes documentation", kind="documentation", url="https://kubernetes.io/docs/home/", note="Use only after a working Docker image exists."),
    ]),
    "python": (["Programming fundamentals"], [
        LearningResource(title="Python tutorial", kind="documentation", url="https://docs.python.org/3/tutorial/", note="Work through functions, modules, exceptions, and environments."),
        LearningResource(title="Effective Python", kind="book", note="Apply a small number of items in a tested project."),
    ]),
    "sql": (["Relational data modeling"], [
        LearningResource(title="SQLBolt", kind="practice", url="https://sqlbolt.com/", note="Practice queries before adding a database to a project."),
        LearningResource(title="PostgreSQL tutorial", kind="documentation", url="https://www.postgresql.org/docs/current/tutorial.html", note="Use the schema and query chapters."),
    ]),
    "machine learning": (["Python", "Statistics", "Linear algebra"], [
        LearningResource(title="Introduction to Machine Learning", kind="course", url="https://www.kaggle.com/learn/intro-to-machine-learning", note="Build and evaluate a baseline before using complex models."),
        LearningResource(title="Hands-On Machine Learning", kind="book", note="Reproduce a small end-to-end evaluation."),
    ]),
}


def build_skill_tree(match: MatchResult) -> list[SkillNode]:
    nodes = []
    for item in match.requirements:
        if item.status != RequirementStatus.MISSING:
            continue
        key = item.skill.casefold()
        prerequisites, resources = KNOWLEDGE.get(key, ([], [
            LearningResource(title=f"Official documentation for {item.skill}", kind="documentation", note="Start with the official beginner guide and build an observable example."),
            LearningResource(title=f"Deliberate practice: {item.skill}", kind="practice", note="Complete one small, tested task and publish the result."),
        ]))
        nodes.append(SkillNode(
            skill=item.skill,
            priority="high" if item.required else "medium",
            reason="Missing required skill from the target role" if item.required else "Missing preferred skill from the target role",
            prerequisites=prerequisites,
            completion_evidence=f"Publish a small tested deliverable using {item.skill}, with setup steps and a demo or benchmark.",
            resources=resources,
        ))
    return nodes


def build_project_plans(skill_tree: list[SkillNode]) -> list[ProjectPlan]:
    """Produce up to three sequenced briefs, never represent them as completed work."""
    if not skill_tree:
        return []
    skills = [node.skill for node in skill_tree]
    plans = [_foundation_project(skills[0])]
    if len(skills) > 1:
        plans.append(_integration_project(skills[: min(3, len(skills))]))
    if len(skills) > 3:
        plans.append(_production_project(skills[1: min(5, len(skills))]))
    return plans[:3]


def _foundation_project(skill: str) -> ProjectPlan:
    return ProjectPlan(
        title=f"{skill} fundamentals: a tested mini-service",
        problem=f"Demonstrate one observable {skill} capability without hiding behind a large framework.",
        skills_practised=[skill], estimated_hours=6,
        milestones=["Define one user story and success metric", "Implement the smallest working version", "Add a repeatable test or verification command", "Write setup and demo instructions"],
        deliverables=["Source repository", "Automated check or reproducible verification", "README with a screenshot/output"],
        acceptance_tests=["A reviewer can run the documented command from a clean checkout", f"The test or demo exercises {skill}", "README names a limitation and next step"],
        readme_outline=["Problem", "Scope", "Setup", "Architecture", "Demo", "Tests", "Trade-offs", "Next steps"],
    )


def _integration_project(skills: list[str]) -> ProjectPlan:
    joined = ", ".join(skills)
    return ProjectPlan(
        title=f"Portfolio integration: {joined}",
        problem="Solve a small end-to-end problem whose architecture makes the target skills visible.",
        skills_practised=skills, estimated_hours=16,
        milestones=["Write a one-page design and acceptance criteria", "Build a vertical slice", "Integrate each target skill deliberately", "Test failures and document decisions", "Record a 2-minute demo"],
        deliverables=["Design note", "Source repository", "Tests", "Demo video or screenshots", "Architecture diagram"],
        acceptance_tests=["Each claimed skill is linked to code, a command, or an architecture decision", "A failure case has a test", "A reviewer can reproduce the demo from the README"],
        readme_outline=["Problem and user", "Requirements", "Architecture", "Local run", "Tests", "Demo", "Trade-offs", "Learning notes"],
    )


def _production_project(skills: list[str]) -> ProjectPlan:
    return ProjectPlan(
        title="Production-readiness extension",
        problem="Extend the integration project with reliability, deployment, and measured operating behaviour.",
        skills_practised=skills, estimated_hours=12,
        milestones=["Choose one realistic reliability risk", "Add observability or deployment", "Measure a before/after behaviour", "Write an incident or trade-off note"],
        deliverables=["Deployment or automation configuration", "Measurement output", "Operational runbook", "Short postmortem/trade-off note"],
        acceptance_tests=["A fresh environment can deploy or run the project", "The repository contains a measured result", "The runbook describes recovery or rollback"],
        readme_outline=["Objective", "Deployment", "Monitoring", "Measurement", "Runbook", "Trade-offs"],
    )
