from streamlit.testing.v1 import AppTest

from tau_job_application.accounts import ConnectedAccountStore
from tau_job_application.application_tracker import ApplicationTrackerStore
from tau_job_application.capital_atlas import AtlasStore
from tau_job_application.company_catalog import CompanyCatalogStore
from tau_job_application.eligibility import ResidencyStore
from tau_job_application.hiring_index import HiringIndexStore
from tau_job_application.monitoring import JobMonitor
from tau_job_application.requirement_memory import RequirementMemory
from tau_job_application.role_discovery import RoleDiscoveryStore
from tau_job_application.storage import LocalStore
from tau_job_application.workspaces import WorkspaceStore
from tau_job_application.yc_directory import YCDirectoryStore


def setup_ui(tmp_path, monkeypatch):
    from tau_job_application import ui
    path = tmp_path / "portal.sqlite"
    for name, store in {
        "WORKSPACES": WorkspaceStore(path), "STORE": LocalStore(path), "MONITOR": JobMonitor(path),
        "REQUIREMENT_MEMORY": RequirementMemory(path), "ROLE_DISCOVERY": RoleDiscoveryStore(path),
        "YC_DIRECTORY": YCDirectoryStore(path), "RESIDENCY": ResidencyStore(path),
        "COMPANY_CATALOG": CompanyCatalogStore(path), "APPLICATIONS": ApplicationTrackerStore(path),
        "ATLAS": AtlasStore(path), "HIRING_INDEX": HiringIndexStore(path),
        "ACCOUNTS": ConnectedAccountStore(path),
    }.items():
        monkeypatch.setattr(ui, name, store)
    return ui


def _app():
    app = AppTest.from_string("from tau_job_application.ui import main\nmain()", default_timeout=60)
    app.query_params["view"] = "account"
    return app


def test_accounts_view_states_and_github_flow(tmp_path, monkeypatch):
    ui = setup_ui(tmp_path, monkeypatch)
    app = _app()
    app.run()
    assert not app.exception
    bodies = " ".join(item.value for item in app.markdown)
    assert "Connected accounts" in bodies
    assert "not connected" in bodies
    # LinkedIn without app credentials shows honest setup instructions, not a fake button.
    assert any("developer.linkedin.com" in item.value for item in app.markdown)
    # Gmail card points to the per-conversation flow; no whole-inbox promise.
    assert any("per-conversation" in item.value for item in app.markdown)

    def fake_fetcher(url, *, expected_host, **kwargs):
        if "repos" in url:
            return [{"language": "Python"}]
        return {"login": "octocat", "name": "The Octocat", "public_repos": 3,
                "avatar_url": "https://avatars.githubusercontent.com/u/1"}

    monkeypatch.setattr("tau_job_application.accounts_ui.connect_github",
                        lambda username: __import__("tau_job_application.accounts", fromlist=["connect_github"]).connect_github(username, fetcher=fake_fetcher))
    next(item for item in app.text_input if item.label == "GitHub username").set_value("octocat").run()
    next(item for item in app.button if item.label == "Connect GitHub").click().run()
    assert not app.exception
    account = ui.ACCOUNTS.get("github")
    assert account is not None and account.subject == "octocat"
    # Prefill offer appears because the shared profile has no GitHub link yet.
    prefill = next(item for item in app.button if "as my profile link" in item.label)
    prefill.click().run()
    assert ui.WORKSPACES.shared_profile()["github"] == "https://github.com/octocat"
    # Unlink returns to the not-connected state.
    next(item for item in app.button if item.label == "Unlink").click().run()
    assert ui.ACCOUNTS.get("github") is None


def test_profile_identity_saves_edits_and_removes_locally(tmp_path, monkeypatch):
    from tau_job_application.profile_identity import ProfileIdentityStore

    ui = setup_ui(tmp_path, monkeypatch)
    app = AppTest.from_string("from tau_job_application.ui import main\nmain()", default_timeout=40)
    app.query_params["view"] = "account"
    app.run()
    assert not app.exception
    assert any(item.value == "Your profile" for item in app.subheader)

    next(item for item in app.text_input if item.label == "Your name").set_value("Alex Example")
    next(item for item in app.text_input if item.label == "Your email").set_value("alex@example.com")
    next(item for item in app.button if item.label == "Save my profile").click()
    app.run()
    assert not app.exception
    identity = ProfileIdentityStore(ui.WORKSPACES.path).load()
    assert (identity.name, identity.email) == ("Alex Example", "alex@example.com")
    assert any("Alex Example" in item.value for item in app.markdown)

    next(item for item in app.button if item.label == "Edit").click()
    app.run()
    next(item for item in app.text_input if item.label == "Your name").set_value("Alexandra Example")
    next(item for item in app.button if item.label == "Save my profile").click()
    app.run()
    assert ProfileIdentityStore(ui.WORKSPACES.path).load().name == "Alexandra Example"

    next(item for item in app.button if item.label == "Remove").click()
    app.run()
    assert ProfileIdentityStore(ui.WORKSPACES.path).load() is None


def test_profile_identity_rejects_an_invalid_email(tmp_path, monkeypatch):
    ui = setup_ui(tmp_path, monkeypatch)
    app = AppTest.from_string("from tau_job_application.ui import main\nmain()", default_timeout=40)
    app.query_params["view"] = "account"
    app.run()
    next(item for item in app.text_input if item.label == "Your name").set_value("Alex")
    next(item for item in app.text_input if item.label == "Your email").set_value("not-an-email")
    next(item for item in app.button if item.label == "Save my profile").click()
    app.run()
    assert not app.exception
    assert any("valid email" in item.body for item in app.error)
    from tau_job_application.profile_identity import ProfileIdentityStore
    assert ProfileIdentityStore(ui.WORKSPACES.path).load() is None
