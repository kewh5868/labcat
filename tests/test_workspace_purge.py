"""Explicit, scoped permanent deletion tested only on disposable
workspaces."""

import sqlite3
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from labcat.config import load_config
from labcat.intake import decision, outcome
from labcat.research import research
from labcat.structures import StructureStore
from labcat.web import create_app
from labcat.workspace import WorkspaceNotFound, WorkspaceStore

pytestmark = pytest.mark.usefixtures("authenticated_research")
PROMPT = "Find oxide dielectric candidates for thin-film experiments."


def assert_empty_removed(items):
    assert items["projects"] == []
    assert items["chats"] == []
    assert items["retention_days"] == 30
    assert len(items["snapshot"]) == 64


def signed_client(path):
    client = TestClient(create_app(workspace_path=path), base_url="http://localhost")
    token = client.get("/api/session").json()["csrf_token"]
    client.headers["X-CSRF-Token"] = token
    return client


def assert_integrity(store):
    with store._connection() as connection:
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def delete_removed(store, kind, identifier, mode):
    if mode == "individual":
        getattr(store, f"purge_{kind}")(identifier, confirm=True)
    elif mode == "bulk":
        store.purge_removed(confirm=True, snapshot=store.removed_items()["snapshot"])
    else:
        key = "project_id" if kind == "project" else "chat_id"
        with store._connection(write=True) as connection:
            connection.execute(
                f"UPDATE archived_{kind}s SET archived_at=? WHERE {key}=?",
                ((datetime.now(UTC) - timedelta(days=31)).isoformat(), identifier),
            )
        store.purge_expired()


def navigation_source(connection, project_id, source_id, chat_id=None, *, pinned=False):
    """Unverified placeholder metadata solely for testing association
    cleanup."""
    connection.execute(
        "INSERT INTO sources VALUES (?,?,?,?,?,?,?,?)",
        (
            source_id,
            project_id,
            "TEST ONLY: source placeholder",
            "https://example.invalid/test-resource/" + source_id,
            "TEST ONLY",
            "public",
            "unverified",
            "2026-01-01T00:00:00Z",
        ),
    )
    connection.execute(
        "INSERT INTO source_records VALUES (?,?,?)",
        (project_id, source_id, source_id),
    )
    connection.execute(
        "INSERT INTO source_annotations VALUES (?,?,?)", (source_id, project_id, "{}")
    )
    if chat_id:
        connection.execute(
            "INSERT INTO chat_sources VALUES (?,?,?)",
            (project_id, chat_id, source_id),
        )
    if pinned:
        connection.execute(
            "INSERT INTO source_pins VALUES (?,?,?)",
            (project_id, source_id, "2026-01-01T00:00:00Z"),
        )


def test_preferences_are_strict_persistent_and_separate_from_science_settings(tmp_path):
    path = tmp_path / "workspace.sqlite3"
    with signed_client(path) as client:
        original = client.get("/api/settings").json()
        assert client.get("/api/workspace/preferences").json() == {
            "confirm_removal": True
        }
        assert client.put(
            "/api/workspace/preferences", json={"confirm_removal": False}
        ).json() == {"confirm_removal": False}
        assert client.get("/api/settings").json() == original
    with signed_client(path) as client:
        assert client.get("/api/workspace/preferences").json() == {
            "confirm_removal": False
        }
        assert client.put(
            "/api/workspace/preferences", json={"confirm_removal": True}
        ).json() == {"confirm_removal": True}
    assert WorkspaceStore(path).workspace_preferences() == {"confirm_removal": True}


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"confirm_removal": None},
        {"confirm_removal": 0},
        {"confirm_removal": 1},
        {"confirm_removal": "false"},
        {"confirm_removal": []},
        {"confirm_removal": False, "ranking": {}},
    ],
)
def test_preference_api_rejects_coercion_and_unknown_fields(tmp_path, payload):
    with signed_client(tmp_path / "w.sqlite3") as client:
        response = client.put("/api/workspace/preferences", json=payload)
        assert response.status_code == 422
        assert client.get("/api/workspace/preferences").json() == {
            "confirm_removal": True
        }


@pytest.mark.parametrize("kind", ["projects", "chats"])
@pytest.mark.parametrize(
    "payload",
    [
        None,
        {},
        {"confirm": False},
        {"confirm": 1},
        {"confirm": "true"},
        {"confirm": True, "force": True},
    ],
)
def test_permanent_delete_requires_literal_confirmation_even_when_prompts_skipped(
    tmp_path, kind, payload
):
    path = tmp_path / "w.sqlite3"
    with signed_client(path) as client:
        if kind == "projects":
            item = client.post("/api/projects", json={"name": "Delete test"}).json()
        else:
            item = client.post("/api/chats", json={"title": "Delete test"}).json()
        client.put("/api/workspace/preferences", json={"confirm_removal": False})
        assert client.delete(f"/api/{kind}/{item['id']}").status_code == 204
        before = client.get("/api/removed").json()
        response = client.request(
            "DELETE", f"/api/removed/{kind}/{item['id']}", json=payload
        )
        assert response.status_code == 422
        assert client.get("/api/removed").json() == before
    assert_integrity(WorkspaceStore(path))


@pytest.mark.parametrize("kind", ["projects", "chats"])
def test_purge_api_rejects_active_or_restored_items_and_deletes_only_removed(
    tmp_path, kind
):
    path = tmp_path / "w.sqlite3"
    with signed_client(path) as client:
        body = {"name": "Project"} if kind == "projects" else {"title": "Chat"}
        item = client.post(f"/api/{kind}", json=body).json()
        delete_path = f"/api/removed/{kind}/{item['id']}"
        assert (
            client.request("DELETE", delete_path, json={"confirm": True}).status_code
            == 404
        )
        assert client.delete(f"/api/{kind}/{item['id']}").status_code == 204
        assert client.post(f"/api/{kind}/{item['id']}/restore").status_code == 200
        assert (
            client.request("DELETE", delete_path, json={"confirm": True}).status_code
            == 404
        )
        assert client.delete(f"/api/{kind}/{item['id']}").status_code == 204
        response = client.request("DELETE", delete_path, json={"confirm": True})
        assert response.status_code == 204 and response.content == b""
        assert_empty_removed(client.get("/api/removed").json())
        assert client.post(f"/api/{kind}/{item['id']}/restore").status_code == 404
        assert (
            client.request("DELETE", delete_path, json={"confirm": True}).status_code
            == 404
        )
    assert_empty_removed(WorkspaceStore(path).removed_items())
    assert_integrity(WorkspaceStore(path))


def test_removed_api_rows_keep_complete_navigation_shape_and_parent_state(tmp_path):
    path = tmp_path / "w.sqlite3"
    store = WorkspaceStore(path)
    project = store.create_project("Removed project")
    child = store.create_chat(project["id"], "Explicitly removed child")
    general = store.create_global_chat("Removed general chat")
    store.archive_chat(child["id"])
    store.archive_chat(general["id"])
    store.archive_project(project["id"])
    with signed_client(path) as client:
        items = client.get("/api/removed").json()
        assert len(items["projects"]) == 1 and len(items["chats"]) == 2
        for original in (general, child):
            row = next(item for item in items["chats"] if item["id"] == original["id"])
            assert {key: row[key] for key in original} == original
            assert isinstance(row["archived_at"], str)
        assert items["projects"][0]["chat_count"] == 2
        assert client.post(f"/api/chats/{child['id']}/restore").status_code == 409
        # An explicitly removed child can be deleted without restoring its parent.
        assert (
            client.request(
                "DELETE", f"/api/removed/chats/{child['id']}", json={"confirm": True}
            ).status_code
            == 204
        )
        assert client.post(f"/api/projects/{project['id']}/restore").status_code == 200
        assert (
            len(client.get(f"/api/projects/{project['id']}/chats").json()["chats"]) == 1
        )
        assert client.post(f"/api/chats/{general['id']}/restore").status_code == 200
    assert_integrity(store)


def test_chat_purge_keeps_shared_sources_and_archived_sibling_history(
    tmp_path, historical_property_fixture
):
    store = WorkspaceStore(tmp_path / "w.sqlite3")
    project = store.create_project("First")
    other = store.create_project("Other")
    first = store.project_draft(project["id"])
    second = store.create_chat(project["id"], "Keep sibling")
    outsider = store.project_draft(other["id"])
    result = research(PROMPT, load_config())
    for chat, scope in ((first, project), (second, project), (outsider, other)):
        store.append_research(chat["id"], scope["id"], PROMPT, result)
    first_detail = store.get_global_chat(first["id"])
    second_detail = store.get_global_chat(second["id"])
    other_detail = store.get_global_chat(outsider["id"])
    source_id = first_detail["sources"][0]["id"]
    report_id = first_detail["reports"][0]["id"]
    store.set_pin(project["id"], "source", source_id)
    store.set_pin(project["id"], "report", report_id)
    store.archive_chat(first["id"])
    store.archive_chat(second["id"])
    store.purge_chat(first["id"], confirm=True)
    restored = WorkspaceStore(store.path).restore_chat(second["id"])
    assert restored["messages"] == second_detail["messages"]
    assert restored["reports"] == second_detail["reports"]
    assert {item["id"] for item in restored["sources"]} == {
        item["id"] for item in second_detail["sources"]
    }
    assert next(item for item in restored["sources"] if item["id"] == source_id)[
        "pinned"
    ]
    assert store.get_global_chat(outsider["id"]) == other_detail
    with store._connection() as connection:
        for table in ("reports", "report_pins", "research_runs"):
            key = "id" if table == "reports" else "report_id"
            assert (
                connection.execute(
                    f"SELECT 1 FROM {table} WHERE {key}=?", (report_id,)
                ).fetchone()
                is None
            )
    assert_integrity(store)


@pytest.mark.parametrize("mode", ["individual", "bulk", "expired"])
def test_chat_cleanup_is_limited_to_its_unreferenced_unpinned_sources(tmp_path, mode):
    store = WorkspaceStore(tmp_path / "w.sqlite3")
    project = store.create_project("Cleanup")
    chat = store.project_draft(project["id"])
    sibling = store.create_chat(project["id"], "Keep active shared source")
    with store._connection(write=True) as connection:
        navigation_source(connection, project["id"], "unique", chat["id"])
        navigation_source(connection, project["id"], "pinned", chat["id"], pinned=True)
        navigation_source(connection, project["id"], "unrelated-orphan")
        navigation_source(connection, project["id"], "shared", chat["id"])
        connection.execute(
            "INSERT INTO chat_sources VALUES (?,?,?)",
            (project["id"], sibling["id"], "shared"),
        )
    store.archive_chat(chat["id"])
    delete_removed(store, "chat", chat["id"], mode)
    with store._connection() as connection:
        for table in ("sources", "source_records", "source_annotations"):
            key = "id" if table == "sources" else "source_id"
            assert {
                row[0] for row in connection.execute(f"SELECT {key} FROM {table}")
            } == {"pinned", "unrelated-orphan", "shared"}
    assert {source["id"] for source in store.contents(project["id"])["sources"]} == {
        "pinned",
    }
    assert [
        source["id"] for source in store.get_global_chat(sibling["id"])["sources"]
    ] == ["shared"]
    assert_integrity(store)


@pytest.mark.parametrize("mode", ["individual", "bulk", "expired"])
def test_project_purge_cascades_only_current_children_and_preserves_moved_chat(
    tmp_path, historical_property_fixture, mode
):
    store = WorkspaceStore(tmp_path / "w.sqlite3")
    project = store.create_project("Remove this")
    other = store.create_project("Keep this")
    chat = store.project_draft(project["id"])
    moved = store.create_chat(project["id"], "Move before removal")
    result = research(PROMPT, load_config())
    for item in (chat, moved):
        store.append_research(item["id"], project["id"], PROMPT, result)
    store.update_chat(chat["id"], title="Manually renamed")
    store.append_research(
        chat["id"],
        project["id"],
        "Vague",
        outcome(decision("clarification_required", "materials_scope_needed")),
    )
    detail = store.get_global_chat(chat["id"])
    store.set_pin(project["id"], "report", detail["reports"][0]["id"])
    store.set_pin(project["id"], "source", detail["sources"][0]["id"])
    preserved = store.move_chat(moved["id"], other["id"])
    StructureStore(store, None, lambda: {}).initialize()
    with store._connection(write=True) as connection:
        # Opaque TEST ONLY cache content tests foreign-key ownership, not structures.
        connection.execute(
            "INSERT INTO report_structures SELECT id,'TEST ONLY','{}','TEST ONLY' "
            "FROM reports"
        )
    store.archive_project(project["id"])
    # Hidden by a parent does not mean explicitly removed as an individual item.
    with pytest.raises(WorkspaceNotFound):
        store.purge_chat(chat["id"], confirm=True)
    delete_removed(store, "project", project["id"], mode)
    assert store.get_global_chat(moved["id"]) == preserved
    with store._connection() as connection:
        for table in (
            "chats",
            "messages",
            "reports",
            "sources",
            "chat_sources",
            "report_sources",
            "report_pins",
            "source_pins",
            "research_runs",
            "source_records",
            "source_annotations",
            "archived_projects",
        ):
            assert (
                connection.execute(
                    f"SELECT 1 FROM {table} WHERE project_id=?", (project["id"],)
                ).fetchone()
                is None
            )
        assert connection.execute("SELECT 1 FROM message_intakes").fetchone() is None
        assert connection.execute("SELECT 1 FROM manual_chat_titles").fetchone() is None
        assert {
            row[0]
            for row in connection.execute("SELECT report_id FROM report_structures")
        } == {report["id"] for report in preserved["reports"]}
    assert_integrity(store)


def test_standalone_purge_removes_only_its_internal_scope(tmp_path):
    store = WorkspaceStore(tmp_path / "w.sqlite3")
    first = store.create_global_chat("Delete")
    second = store.create_global_chat("Keep")
    scope, _ = store.research_inputs(first["id"])
    store.archive_chat(first["id"])
    # Even an unexpected internal-scope archive marker cannot make that scope
    # addressable through the public project deletion operation.
    with store._connection(write=True) as connection:
        connection.execute(
            "INSERT INTO archived_projects VALUES (?,?)", (scope, "TEST ONLY")
        )
    with pytest.raises(WorkspaceNotFound):
        store.purge_project(scope, confirm=True)
    store.purge_chat(first["id"], confirm=True)
    assert store.get_global_chat(second["id"])["chat"] == second
    with store._connection() as connection:
        assert (
            connection.execute("SELECT 1 FROM projects WHERE id=?", (scope,)).fetchone()
            is None
        )
    with pytest.raises(WorkspaceNotFound):
        store.append_research(
            first["id"],
            scope,
            "Vague",
            outcome(decision("clarification_required", "materials_scope_needed")),
        )
    assert_integrity(store)


def test_chat_purge_failure_rolls_back_archival_history_and_source_deletion(tmp_path):
    store = WorkspaceStore(tmp_path / "w.sqlite3")
    project = store.create_project("Rollback")
    chat = store.project_draft(project["id"])
    result = outcome(decision("clarification_required", "materials_scope_needed"))
    detail = store.append_research(chat["id"], project["id"], "Help", result)
    with store._connection(write=True) as connection:
        navigation_source(connection, project["id"], "unique", chat["id"])
        connection.execute(
            "CREATE TRIGGER fail_purge BEFORE DELETE ON sources "
            "BEGIN SELECT RAISE(ABORT, 'TEST ONLY: deletion failure'); END"
        )
    store.archive_chat(chat["id"])
    before = store.removed_items()
    with pytest.raises(sqlite3.IntegrityError):
        store.purge_chat(chat["id"], confirm=True)
    assert store.removed_items() == before
    restored = store.restore_chat(chat["id"])
    assert restored["messages"] == detail["messages"]
    assert restored["sources"][0]["id"] == "unique"
    assert_integrity(store)


@pytest.mark.parametrize("confirm", [False, None, 1, "true"])
def test_store_confirmation_cannot_be_coerced(tmp_path, confirm):
    store = WorkspaceStore(tmp_path / "w.sqlite3")
    project = store.create_project("Preserve")
    chat = store.project_draft(project["id"])
    store.archive_chat(chat["id"])
    store.archive_project(project["id"])
    before = store.removed_items()
    for operation, identifier in (
        (store.purge_chat, chat["id"]),
        (store.purge_project, project["id"]),
    ):
        with pytest.raises(ValueError, match="confirmation"):
            operation(identifier, confirm=confirm)
    assert store.removed_items() == before


def test_existing_workspace_adds_default_preferences_without_rewriting_history(
    tmp_path,
):
    store = WorkspaceStore(tmp_path / "w.sqlite3")
    project = store.create_project("Existing workspace")
    chat = store.project_draft(project["id"])
    expected = store.get_global_chat(chat["id"])
    with store._connection(write=True) as connection:
        connection.execute("DROP TABLE workspace_preferences")
    reopened = WorkspaceStore(store.path)
    assert reopened.workspace_preferences() == {"confirm_removal": True}
    assert reopened.get_global_chat(chat["id"]) == expected
    with pytest.raises(ValueError):
        reopened.save_workspace_preferences(confirm_removal=1)
    assert_integrity(reopened)
