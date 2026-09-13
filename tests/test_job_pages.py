import json

import pytest

from tau_job_application.job_pages import parse_job_page, validate_public_url
from tau_job_application.parsing import infer_profile_links, parse_candidate_text
from tau_job_application.requirement_memory import RequirementMemory


HTML = """<html><head><title>Firmware Engineer | Acme</title>
<script type="application/ld+json">{"@type":"JobPosting","title":"Firmware Engineer","hiringOrganization":{"name":"Acme"},"jobLocation":{"address":{"addressLocality":"Zurich"}},"description":"You are experienced with C++ and comfortable with RTOS. FPGA is a plus."}</script></head><body><h1>Firmware Engineer</h1><p>Build embedded systems.</p></body></html>"""


def test_parse_schema_job_page_infers_metadata_and_source():
    job = parse_job_page(HTML, "https://careers.acme.example/firmware")
    assert job.title == "Firmware Engineer"
    assert job.company == "Acme"
    assert job.url == "https://careers.acme.example/firmware"
    assert {item.skill for item in job.requirements} >= {"C++", "RTOS", "FPGA"}
    assert next(item for item in job.requirements if item.skill == "FPGA").required is False


def test_parse_json_job_page():
    job = parse_job_page(json.dumps({"title": "GPU Engineer", "hiringOrganization": {"name": "Acme"}, "description": "Experience with CUDA and C++."}), "https://jobs.acme.example/gpu", "application/json")
    assert job.title == "GPU Engineer"
    assert {item.skill for item in job.requirements} >= {"CUDA", "C++"}


def test_profile_links_are_inferred_and_explicit_links_override():
    text = "GitHub: https://github.com/alex\nLinkedIn https://www.linkedin.com/in/alex\nPortfolio https://alex.dev\nX https://x.com/alex"
    links = infer_profile_links(text)
    assert links == {"github": "https://github.com/alex", "linkedin": "https://www.linkedin.com/in/alex", "portfolio": "https://alex.dev", "x": "https://x.com/alex"}
    candidate = parse_candidate_text(text, links={"github": "https://github.com/edited"})
    assert candidate.links.github == "https://github.com/edited"
    assert candidate.links.portfolio == "https://alex.dev"


@pytest.mark.parametrize("url", ["http://example.com/job", "https://localhost/job", "https://127.0.0.1/job", "https://user:pass@example.com/job"])
def test_job_url_validation_rejects_unsafe_urls(url):
    with pytest.raises(ValueError):
        validate_public_url(url)


def test_feedback_is_persisted_without_training(tmp_path):
    memory = RequirementMemory(tmp_path / "memory.sqlite")
    memory.save_feedback("Experienced with C++.", "partly useful", "Capture technical phrases more precisely")
    assert memory.feedback("Experienced with C++.")[0]["rating"] == "partly useful"
