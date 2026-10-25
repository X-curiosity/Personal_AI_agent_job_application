from pathlib import Path
import io
from zipfile import ZipFile

import pytest

from tau_job_application.job_skills import SKILLS

from tau_job_application.hosted_matching import cv_text, filter_jobs, load_public_jobs, match_cv_to_job

JOB = {"id": "job-1", "title": "ML Engineer", "company": "Example", "url": "https://jobs.example/1", "skills": ["Python", "SQL", "Docker"], "area": "Data & AI", "locations": ["Paris, France"], "description": "Build systems"}


def test_deterministic_cv_match_is_explainable():
    result = match_cv_to_job(b"Skills: Python, SQL\nhttps://github.com/example", "text/plain", JOB)
    assert result.matched == ("Python", "SQL")
    assert result.missing == ("Docker",)
    assert result.coverage == 67
    assert result.links["github"] == "https://github.com/example"


def test_no_advert_terms_means_no_invented_score():
    result = match_cv_to_job(b"Skills: Python", "text/plain", {**JOB, "skills": []})
    assert result.coverage is None


def test_text_formats_reject_bad_data():
    with pytest.raises(ValueError): cv_text("cv.txt", "text/plain", b"")
    with pytest.raises(ValueError): cv_text("cv.pdf", "application/pdf", b"not a pdf")
    with pytest.raises(ValueError): cv_text("cv.txt", "application/octet-stream", b"text")


def test_cv_and_advertiser_share_every_canonical_skill():
    result = match_cv_to_job(" ".join(SKILLS).encode(), "text/plain", {**JOB, "skills": list(SKILLS)})
    assert set(result.matched) == set(SKILLS)
    assert result.coverage == 100


def test_docx_rejects_suspicious_decompression():
    buffer = io.BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", b"0" * 20_000_001)
    with pytest.raises(ValueError, match="too large"):
        cv_text("cv.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", buffer.getvalue())


def test_filter_jobs_uses_all_search_terms_and_area():
    assert filter_jobs([JOB], "example python", "Data & AI") == [JOB]
    assert filter_jobs([JOB], "example docker paris") == [JOB]
    assert filter_jobs([JOB], "example rust") == []
    assert filter_jobs([JOB], area="Engineering") == []


def test_hosted_snapshot_loads_only_public_job_fields(monkeypatch, tmp_path):
    root = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("HOSTED_JOBS_URL", "")
    jobs = load_public_jobs()
    assert jobs and jobs[0]["url"].startswith("https://")
    assert set(jobs[0]) == {"id", "title", "company", "url", "source", "area", "description", "skills", "locations"}
