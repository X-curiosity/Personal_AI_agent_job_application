from pathlib import Path

from tau_job_application.pipeline import analyze_files, render_markdown


ROOT = Path(__file__).resolve().parents[1]


def test_fixture_pipeline() -> None:
    result = analyze_files(ROOT / "fixtures/candidate.txt", ROOT / "fixtures/job.txt")
    report = render_markdown(result)

    assert result.match.score == 63
    assert [node.skill for node in result.skill_tree] == ["Docker", "AWS"]
    assert "Junior Backend Engineer" in report
    assert "Evidence-first result" in report
    assert result.cv_score is not None
    assert result.tailored_resume is not None
