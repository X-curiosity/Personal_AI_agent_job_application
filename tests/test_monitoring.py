from pathlib import Path

from tau_job_application.monitoring import JobMonitor
from tau_job_application.parsing import parse_job_text


def test_monitor_returns_only_new_jobs_across_user_triggered_refreshes(tmp_path: Path) -> None:
    monitor = JobMonitor(tmp_path / "monitor.sqlite")
    job = parse_job_text("Title: Engineer\nCompany: Acme\nRequired skills: Python")

    first = monitor.refresh(source="Recruitee", identifier="acme", jobs=[job])
    second = monitor.refresh(source="Recruitee", identifier="acme", jobs=[job])

    assert [item.title for item in first] == ["Engineer"]
    assert second == []
    assert monitor.watches()[0]["known_jobs"] == 1
