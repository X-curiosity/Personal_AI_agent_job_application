from pathlib import Path

from tau_job_application.role_folders import (
    RoleFolder,
    RoleFolderStore,
    build_project,
    discover_roles,
    load_companies,
    load_jobs,
    normalize_region,
    region_for_country,
    run_all_folders,
    run_folder,
    score_role,
)
from tau_job_application.project_pdf import build_project_sections, render_document, render_project_pdf


def _job(title, company, company_type="Startup", skills=("Python",), country="Belgium", area="Data & AI", url="https://jobs.example.com/1"):
    return {"id": f"job_{abs(hash((title, company))) % 10**20:020d}", "title": title, "company": company,
            "companyType": company_type, "area": area, "description": f"{title} at {company}.", "skills": list(skills),
            "locations": [{"label": f"{country}", "city": "Brussels", "country": country, "latitude": 50.85, "longitude": 4.35, "precision": "city"}],
            "url": url, "source": "Ashby"}


def _cv() -> bytes:
    return b"Python, SQL, Docker, Machine Learning\n"


def test_region_classification_and_aliases():
    assert region_for_country("France") == "Europe"
    assert region_for_country("United States") == "United States"
    assert region_for_country("USA") == "United States"
    assert region_for_country("Nigeria") == "Africa"
    assert region_for_country("India") == "Asia"
    assert region_for_country("Nowhereland") == "Other"
    assert normalize_region("US") == "United States"
    assert normalize_region("eu") == "Europe"
    assert normalize_region("Any") == "Any"


def test_role_terms_from_keywords_or_name_first_segment():
    assert RoleFolder(name="PCB design engineer - US", role_keywords=["pcb design"]).role_terms() == ["pcb design"]
    assert RoleFolder(name="ML engineer - Europe - Startup", role_keywords=[]).role_terms() == ["ml engineer"]
    assert RoleFolder(name="All roles - Europe", role_keywords=[]).role_terms() == []


def test_discover_roles_filters_keyword_region_type():
    jobs = [
        _job("ML Engineer", "Euro AI", "Startup", ("Machine Learning",), "Belgium"),
        _job("ML Engineer", "US Corp", "Public", ("Machine Learning",), "United States"),
        _job("Backend Engineer", "Euro AI", "Startup", ("Go",), "Belgium"),
    ]
    folder = RoleFolder(name="ML engineer - Europe - Startup", role_keywords=["ml engineer", "machine learning"],
                        region="Europe", company_type="startup")
    found = discover_roles(folder, jobs)
    assert [j["company"] for j in found] == ["Euro AI"]


def test_score_role_returns_coverage_and_gaps():
    job = _job("ML Engineer", "Euro AI", skills=("Python", "SQL", "Kubernetes"))
    score, matched, missing = score_role(job, _cv(), "text/plain")
    assert score == 67
    assert "Python" in matched and "SQL" in matched
    assert missing == ["Kubernetes"]


def test_score_role_without_cv_is_unscored():
    job = _job("ML Engineer", "Euro AI", skills=("Python",))
    assert score_role(job, None, None) == (None, [], [])


def test_build_project_is_domain_aware_and_deterministic():
    job = _job("ML Engineer", "Euro AI", skills=("Python", "SQL", "Kubernetes"))
    project = build_project(job, {"industry": "Logistics"}, ["Kubernetes"], RoleFolder(name="x", role_keywords=["ml"]))
    assert project["domain"] == "Logistics"
    assert project["title"].endswith("Euro AI")
    assert any("Kubernetes" in task for task in project["tasks"])
    assert build_project(job, None, [], RoleFolder(name="x", role_keywords=["ml"]))["gap_skills"] == []


def test_pdf_render_is_valid():
    data = render_document("Project title", "subtitle · 67%", [("Section", ["line one", "line two"])])
    assert data.startswith(b"%PDF-1.4")
    assert data.rstrip().endswith(b"%%EOF")
    assert b"Project title" in data


def test_project_pdf_from_match_dict():
    match = {"title": "ML Engineer", "company": "Euro AI", "area": "Data & AI", "score": 67,
             "project": {"title": "ML proof project", "domain": "Logistics", "gap_skills": ["Kubernetes"],
                         "tasks": ["build X"], "deliverables": ["a"], "acceptance": ["b"], "goal": "g", "why": "w"}}
    data = render_project_pdf(match, "ML engineer - Europe", "I want to grow in ML.")
    assert data.startswith(b"%PDF-1.4")
    assert b"ML proof project" in data


def test_store_crud_and_documents(tmp_path):
    store = RoleFolderStore(tmp_path / "assistant.sqlite")
    folder_id = store.create(RoleFolder(name="PCB - US", role_keywords=["pcb design"], region="United States", company_type="public"))
    store.set_documents(folder_id, b"CV bytes", "cv.txt", "text/plain", "I am a PCB engineer.")
    assert store.documents(folder_id)["cv_name"] == "cv.txt"
    assert store.get(folder_id)["letter_text"] == "I am a PCB engineer."
    assert len(store.list()) == 1
    store.delete(folder_id)
    assert store.list() == []


def test_run_folder_end_to_end(tmp_path):
    store = RoleFolderStore(tmp_path / "assistant.sqlite")
    folder_id = store.create(RoleFolder(name="ML engineer - Europe - Startup", role_keywords=["ml engineer"], region="Europe", company_type="startup"))
    store.set_documents(folder_id, _cv(), "cv.txt", "text/plain", "I like ML.")
    folder = RoleFolder(name="ML engineer - Europe - Startup", role_keywords=["ml engineer"], region="Europe", company_type="startup", id=folder_id)
    jobs = [_job("ML Engineer", "Euro AI", "Startup", ("Python", "SQL", "Kubernetes"), "Belgium"),
            _job("ML Engineer", "US Corp", "Public", ("Python",), "United States")]
    companies = {"euro ai": {"industry": "Logistics", "summary": None, "type": "startup"}}
    matches = run_folder(store, folder, jobs, companies)
    assert [m.company for m in matches] == ["Euro AI"]
    assert matches[0].score == 67
    assert "Kubernetes" in matches[0].missing
    stored = store.list_matches(folder_id)
    assert len(stored) == 1 and stored[0]["score"] == 67


def test_run_all_folders(tmp_path):
    store = RoleFolderStore(tmp_path / "assistant.sqlite")
    store.create(RoleFolder(name="ML - Europe", role_keywords=["ml engineer"], region="Europe"))
    store.create(RoleFolder(name="PCB - US", role_keywords=["pcb design"], region="United States"))
    jobs = [_job("ML Engineer", "Euro AI", "Startup", ("Python",), "Belgium"),
            _job("PCB Design Engineer", "US Corp", "Public", ("PCB",), "United States", area="Engineering")]
    summary = run_all_folders(store, jobs, {})
    assert summary["total_matches"] == 2
    names = {f["name"]: f["matches"] for f in summary["folders"]}
    assert names == {"ML - Europe": 1, "PCB - US": 1}
