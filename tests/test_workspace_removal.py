"""Recoverable sidebar management preserves history and excludes removed
context."""

import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from labcat.config import load_config
from labcat.research import research
from labcat.web import create_app
from labcat.workspace import SCHEMA_VERSION, WorkspaceNotFound, WorkspaceStore

pytestmark = pytest.mark.usefixtures(
    "authenticated_app_models", "authenticated_research"
)

PROMPT = "Find oxide dielectric candidates for thin-film experiments."


def assert_empty_removed(items):
    assert items["projects"] == []
    assert items["chats"] == []
    assert items["retention_days"] == 30
    assert len(items["snapshot"]) == 64


def test_removed_chat_hides_only_its_reports_context_and_source_associations(
    tmp_path, historical_property_fixture
):
    store = WorkspaceStore(tmp_path / "workspace.sqlite3")
    project = store.create_project("Oxides")
    first = store.project_draft(project["id"])
    second = store.create_chat(project["id"], "Interfaces")
    outcome = research(PROMPT, load_config())
    for chat, text in ((first, "FIRST_USER_CONTEXT"), (second, "SECOND_USER_CONTEXT")):
        store.append_research(chat["id"], project["id"], text, outcome)
    first_detail = store.get_global_chat(first["id"])
    report_id = first_detail["reports"][0]["id"]
    source_id = first_detail["sources"][0]["id"]
    store.set_pin(project["id"], "report", report_id)
    store.set_pin(project["id"], "source", source_id)
    first_detail = store.get_global_chat(first["id"])
    store.archive_chat(first["id"])
    assert [chat["id"] for chat in store.list_all_chats()] == [second["id"]]
    assert store.list_projects()[0]["pin_counts"] == {"reports": 0, "sources": 1}
    assert store.list_projects()[0]["chat_count"] == 1
    context = store.context(project["id"])
    assert "FIRST_USER_CONTEXT" not in json.dumps(context)
    assert "SECOND_USER_CONTEXT" in json.dumps(context)
    assert context["sources"][0]["chat_ids"] == [second["id"]]
    assert report_id not in context["sources"][0]["report_ids"]
    assert context["reports"] == []
    for operation in (
        lambda: store.get_global_chat(first["id"]),
        lambda: store.research_inputs(first["id"]),
        lambda: store.update_chat(first["id"], title="Hidden rename"),
        lambda: store.set_pin(project["id"], "report", report_id),
    ):
        with pytest.raises(WorkspaceNotFound):
            operation()
    store.archive_chat(second["id"])
    reopened = WorkspaceStore(store.path)
    assert reopened.contents(project["id"]) == {
        "chats": [],
        "reports": [],
        "sources": [],
    }
    assert reopened.context(project["id"])["messages"] == []
    assert reopened.list_projects()[0]["pin_counts"] == {"reports": 0, "sources": 0}
    assert len(reopened.removed_items()["chats"]) == 2
    assert reopened.restore_chat(first["id"]) == {
        **first_detail,
        "sources": [
            {**source, "chat_ids": [first["id"]], "report_ids": [report_id]}
            for source in first_detail["sources"]
        ],
    }
    assert reopened.list_projects()[0]["pin_counts"] == {"reports": 1, "sources": 1}


def test_project_removal_restore_and_removed_items_api_keep_child_state(tmp_path):
    path = tmp_path / "workspace.sqlite3"
    with TestClient(create_app(workspace_path=path), base_url="http://localhost") as c:
        first = c.post("/api/projects", json={"name": "First"}).json()
        second = c.post("/api/projects", json={"name": "Other"}).json()
        first_chat = c.post(f"/api/projects/{first['id']}/draft-chat").json()
        removed_child = c.post(
            "/api/chats", json={"title": "Removed first", "project_id": first["id"]}
        ).json()
        detail = c.post(
            f"/api/chats/{first_chat['id']}/messages", json={"content": PROMPT}
        ).json()
        assert c.delete(f"/api/chats/{removed_child['id']}").status_code == 204
        assert c.delete(f"/api/projects/{first['id']}").status_code == 204
        assert [p["id"] for p in c.get("/api/projects").json()["projects"]] == [
            second["id"]
        ]
        assert all(
            chat["project_id"] == second["id"]
            for chat in c.get("/api/chats").json()["chats"]
        )
        removed = c.get("/api/removed").json()
        assert [p["id"] for p in removed["projects"]] == [first["id"]]
        assert [chat["id"] for chat in removed["chats"]] == [removed_child["id"]]
        assert removed["projects"][0]["chat_count"] == 2
        for endpoint in ("chats", "contents", "context"):
            assert c.get(f"/api/projects/{first['id']}/{endpoint}").status_code == 404
        assert c.get(f"/api/chats/{first_chat['id']}").status_code == 404
        assert c.post(f"/api/projects/{first['id']}/draft-chat").status_code == 404
        assert c.post(f"/api/chats/{removed_child['id']}/restore").status_code == 409
        assert c.post(f"/api/projects/{first['id']}/restore").status_code == 200
        assert c.get(f"/api/chats/{first_chat['id']}").json() == detail
        assert c.get(f"/api/chats/{removed_child['id']}").status_code == 404
        restored = c.post(f"/api/chats/{removed_child['id']}/restore").json()
        assert restored["chat"] == removed_child
        assert_empty_removed(c.get("/api/removed").json())


def test_rename_metadata_preserves_reports_and_manual_untitled_name(tmp_path):
    store = WorkspaceStore(tmp_path / "workspace.sqlite3")
    project = store.create_project("Original", "Description")
    chat = store.project_draft(project["id"])
    renamed = store.update_chat(chat["id"], title="Untitled chat")
    assert renamed["chat"]["title"] == "Untitled chat"
    detail = store.append_message(
        project["id"], chat["id"], "Find promising oxides", load_config()
    )
    assert detail["chat"]["title"] == "Untitled chat"
    updated = store.update_project(project["id"], name="Renamed")
    assert updated["name"] == "Renamed"
    assert updated["description"] == "Description"
    updated_chat = store.update_chat(chat["id"], title="Gate oxide study")
    assert updated_chat["chat"]["title"] == "Gate oxide study"
    assert updated_chat["reports"] == detail["reports"]
    assert updated_chat["messages"] == detail["messages"]
    assert WorkspaceStore(store.path).get_global_chat(chat["id"]) == updated_chat


def test_combined_chat_rename_and_move_roll_back_together(tmp_path):
    store = WorkspaceStore(tmp_path / "workspace.sqlite3")
    chat = store.create_global_chat("Untitled chat")
    project = store.create_project("Destination")
    with sqlite3.connect(store.path) as connection:
        connection.execute(
            "CREATE TRIGGER fail_move BEFORE UPDATE OF project_id ON chats "
            "BEGIN SELECT RAISE(ABORT, 'test failure'); END"
        )
    with pytest.raises(sqlite3.IntegrityError):
        store.update_chat(chat["id"], project_id=project["id"], title="Changed title")
    assert store.get_global_chat(chat["id"])["chat"] == chat
    with sqlite3.connect(store.path) as connection:
        assert connection.execute("SELECT * FROM manual_chat_titles").fetchall() == []


@pytest.mark.parametrize(
    "kind, payload",
    [
        ("projects", {}),
        ("projects", {"name": ""}),
        ("projects", {"name": None}),
        ("projects", {"description": None}),
        ("projects", {"name": "x" * 121}),
        ("projects", {"name": "a", "role": "admin"}),
        ("chats", {"title": None}),
        ("chats", {"title": " "}),
        ("chats", {"title": "x" * 161}),
    ],
)
def test_rename_api_validates_metadata(tmp_path, kind, payload):
    with TestClient(
        create_app(workspace_path=tmp_path / "w.sqlite3"), base_url="http://localhost"
    ) as c:
        project = c.post("/api/projects", json={"name": "Original"}).json()
        chat = c.post(f"/api/projects/{project['id']}/draft-chat").json()
        identifier = project["id"] if kind == "projects" else chat["id"]
        assert c.patch(f"/api/{kind}/{identifier}", json=payload).status_code == 422
        assert c.get("/api/projects").json()["projects"][0]["name"] == "Original"
        assert c.get(f"/api/chats/{chat['id']}").json()["chat"] == chat


def test_v3_migration_adds_recovery_without_changing_saved_data(tmp_path):
    path = tmp_path / "workspace.sqlite3"
    store = WorkspaceStore(path)
    project = store.create_project("Preserve")
    chat = store.project_draft(project["id"])
    detail = store.append_message(
        project["id"], chat["id"], "Find oxides", load_config()
    )
    with sqlite3.connect(path) as connection:
        for view in ("visible_sources", "visible_reports", "visible_chats"):
            connection.execute(f"DROP VIEW {view}")
        for table in ("manual_chat_titles", "archived_chats", "archived_projects"):
            connection.execute(f"DROP TABLE {table}")
        connection.execute("PRAGMA user_version=3")
    migrated = WorkspaceStore(path)
    assert migrated.get_global_chat(chat["id"]) == detail
    assert_empty_removed(migrated.removed_items())
    migrated.archive_chat(chat["id"])
    assert WorkspaceStore(path).restore_chat(chat["id"]) == detail
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
