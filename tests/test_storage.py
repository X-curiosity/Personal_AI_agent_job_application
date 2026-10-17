import os
import stat

from tau_job_application.storage import LocalStore
from tau_job_application.workspaces import WorkspaceStore


def test_local_store_is_private_to_the_os_user(tmp_path):
    store = LocalStore(tmp_path / ".job_assistant" / "assistant.sqlite")
    assert stat.S_IMODE(os.stat(store.path.parent).st_mode) == 0o700
    assert stat.S_IMODE(os.stat(store.path).st_mode) == 0o600


def test_workspace_store_repairs_permissive_existing_files(tmp_path):
    database = tmp_path / ".job_assistant" / "assistant.sqlite"
    store = WorkspaceStore(database)
    os.chmod(database.parent, 0o755)
    os.chmod(database, 0o644)
    WorkspaceStore(database)  # reopening corrects the permissions in place
    assert stat.S_IMODE(os.stat(database.parent).st_mode) == 0o700
    assert stat.S_IMODE(os.stat(database).st_mode) == 0o600
