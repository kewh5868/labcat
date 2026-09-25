"""Project drafts and prompt-derived labels preserve history and trust
boundaries."""

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from labcat.config import load_config
from labcat.web import create_app
from labcat.workspace import WorkspaceNotFound, WorkspaceStore

pytestmark = pytest.mark.usefixtures("authenticated_app_models")


def test_project_creation_and_first_prompt_reuse_one_starter(tmp_path):
    path = tmp_path / "workspace.sqlite3"
    with TestClient(create_app(workspace_path=path), base_url="http://localhost") as c:
        project = c.post("/api/projects", json={"name": "Oxide materials"}).json()
        pid = project["id"]
        assert project["chat_count"] == 1
        starter = c.get(f"/api/projects/{pid}/chats").json()["chats"][0]
        assert starter["title"] == "Untitled chat"
        assert starter["message_count"] == 0
        assert starter["pin_counts"] == {"reports": 0, "sources": 0}
        for _ in range(3):
            assert c.post(f"/api/projects/{pid}/draft-chat").json() == starter
        detail = c.post(
            f"/api/chats/{starter['id']}/messages",
            json={
                "content": "Please find promising oxide dielectric candidates "
                "for thin-film experiments. Prefer public evidence."
            },
        ).json()
        assert detail["chat"]["id"] == starter["id"]
        assert detail["chat"]["title"] == (
            "Oxide dielectric candidates for thin-film experiments"
        )
        assert detail["chat"]["message_count"] == 2
        assert c.get("/api/chats").json()["chats"] == [detail["chat"]]
        assert c.get("/api/projects").json()["projects"][0]["chat_count"] == 1
        next_draft = c.post(f"/api/projects/{pid}/draft-chat").json()
        assert next_draft["id"] != starter["id"]
        assert next_draft["title"] == "Untitled chat"
        assert next_draft["message_count"] == 0
        assert c.post(f"/api/projects/{pid}/draft-chat").json() == next_draft
    with TestClient(create_app(workspace_path=path), base_url="http://localhost") as c:
        assert c.get("/api/projects").json()["projects"][0]["chat_count"] == 2
        assert c.get(f"/api/chats/{starter['id']}").json() == detail
        assert c.post(f"/api/projects/{pid}/draft-chat").json() == next_draft


def test_failed_starter_insert_rolls_back_project_creation(tmp_path):
    store = WorkspaceStore(tmp_path / "workspace.sqlite3")
    with sqlite3.connect(store.path) as connection:
        connection.execute(
            "CREATE TRIGGER fail_chat BEFORE INSERT ON chats "
            "BEGIN SELECT RAISE(ABORT, 'test failure'); END"
        )
    with pytest.raises(sqlite3.IntegrityError):
        store.create_project("Must be atomic")
    assert store.list_projects() == []
    assert store.list_all_chats() == []


def test_legacy_empty_projects_backfill_without_rewriting_history(tmp_path):
    store = WorkspaceStore(tmp_path / "workspace.sqlite3")
    empty = store.create_project("Legacy empty")
    populated = store.create_project("Preserve history")
    chat = store.project_draft(populated["id"])
    detail = store.append_message(
        populated["id"], chat["id"], "Compare HfO2 and ZrO2", load_config()
    )
    standalone = store.create_global_chat("Untitled chat")
    with sqlite3.connect(store.path) as connection:
        # This fixture removes a starter to model a legacy empty project. Keep
        # its dependent identity row consistent, as ordinary store writes do.
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("DELETE FROM chats WHERE project_id=?", (empty["id"],))
        before_projects = connection.execute(
            "SELECT * FROM projects ORDER BY id"
        ).fetchall()
    with ThreadPoolExecutor(max_workers=4) as executor:
        stores = list(executor.map(lambda _: WorkspaceStore(store.path), range(4)))
    for reopened in stores:
        starters = reopened.list_chats(empty["id"])
        assert len(starters) == 1
        assert starters[0]["title"] == "Untitled chat"
        assert starters[0]["message_count"] == 0
        assert reopened.get_global_chat(chat["id"]) == detail
        assert reopened.list_chats(populated["id"]) == [detail["chat"]]
        assert reopened.get_global_chat(standalone["id"])["chat"] == standalone
    with sqlite3.connect(store.path) as connection:
        assert (
            connection.execute("SELECT * FROM projects ORDER BY id").fetchall()
            == before_projects
        )
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_concurrent_draft_requests_create_only_one_new_chat(tmp_path):
    store = WorkspaceStore(tmp_path / "workspace.sqlite3")
    project = store.create_project("Concurrent project")
    starter = store.project_draft(project["id"])
    store.append_message(project["id"], starter["id"], "First question", load_config())
    with ThreadPoolExecutor(max_workers=4) as executor:
        drafts = list(
            executor.map(lambda _: store.project_draft(project["id"]), range(12))
        )
    assert len({draft["id"] for draft in drafts}) == 1
    assert len(store.list_chats(project["id"])) == 2


def test_project_draft_rejects_missing_and_private_scopes(tmp_path):
    store = WorkspaceStore(tmp_path / "workspace.sqlite3")
    chat = store.create_global_chat("Untitled chat")
    with sqlite3.connect(store.path) as connection:
        scope = connection.execute(
            "SELECT project_id FROM chats WHERE id=?", (chat["id"],)
        ).fetchone()[0]
    for project_id in ("missing", scope):
        with pytest.raises(WorkspaceNotFound):
            store.project_draft(project_id)
    assert store.list_all_chats() == [chat]
    with TestClient(
        create_app(workspace_path=store.path), base_url="http://localhost"
    ) as c:
        assert c.post("/api/projects/missing/draft-chat").status_code == 404
        assert c.post(f"/api/projects/{scope}/draft-chat").status_code == 404


@pytest.mark.parametrize("title", ["Untitled chat", "My precise research title"])
def test_first_prompt_names_standalone_once_and_preserves_custom_titles(
    tmp_path, title
):
    store = WorkspaceStore(tmp_path / "workspace.sqlite3")
    chat = store.create_global_chat(title)
    first = store.append_global_message(
        chat["id"],
        "Could you please compare HfO2 and ZrO2 for gate dielectrics?",
        load_config(),
    )
    expected = (
        "Compare HfO2 and ZrO2 for gate dielectrics"
        if title == "Untitled chat"
        else title
    )
    assert first["chat"]["title"] == expected
    second = store.append_global_message(
        chat["id"], "Now compare polymers", load_config()
    )
    assert second["chat"]["title"] == expected
    assert second["chat"]["message_count"] == 4


def test_failed_research_write_does_not_rename_the_chat(tmp_path):
    store = WorkspaceStore(tmp_path / "workspace.sqlite3")
    project = store.create_project("Atomic naming")
    chat = store.project_draft(project["id"])
    with pytest.raises(ValueError, match="metadata"):
        store.append_research(
            chat["id"],
            project["id"],
            "Please compare oxides",
            {
                "stage": "partial",
                "answer": "No result",
                "pi_summary": "No result",
                "technical_audit": "No result",
                "sources": [{}],
            },
        )
    assert store.get_global_chat(chat["id"])["chat"] == chat
    assert store.get_global_chat(chat["id"])["messages"] == []


def test_prompt_title_is_bounded_metadata_and_never_report_evidence(tmp_path):
    store = WorkspaceStore(tmp_path / "workspace.sqlite3")
    chat = store.create_global_chat("Untitled chat")
    prompt = (
        "# Please find FAKE_MATERIAL with a 98765 eV gap "
        "https://invalid.test/token\u202e\n" + "long request " * 100
    )
    detail = store.append_global_message(chat["id"], prompt, load_config())
    assert len(detail["chat"]["title"]) <= 73
    assert "https" not in detail["chat"]["title"]
    assert "\u202e" not in detail["chat"]["title"]
    assert detail["chat"]["title"].startswith("FAKE_MATERIAL")
    reports = json.dumps(detail["reports"])
    assert "FAKE_MATERIAL" not in reports
    assert "98765" not in reports
    assert detail["sources"] == []
