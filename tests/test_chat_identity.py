"""Stable chat labels disambiguate names without changing UUIDs or saved
history."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from labcat.intake import decision, outcome
from labcat.web import create_app
from labcat.workspace import UNTITLED_CHAT, WorkspaceStore


def assert_identity(chat, *, number=None, title=None):
    assert type(chat["chat_number"]) is int and chat["chat_number"] > 0
    assert chat["display_title"] == f"{chat['title']} · #{chat['chat_number']}"
    if number is not None:
        assert chat["chat_number"] == number
    if title is not None:
        assert chat["title"] == title


def test_duplicate_and_unicode_names_are_distinct_without_renaming_older_labels(
    tmp_path,
):
    store = WorkspaceStore(tmp_path / "w.sqlite3")
    titles = [
        "Oxide study",
        "Oxide study",
        " oxide   study ",
        "Ｏｘｉｄｅ study",
        "OXIDE STUDY",
        "Oxide study · #1",
    ]
    created = []
    for title in titles:
        created.append(store.create_global_chat(title))
        for existing in created:
            assert store.get_global_chat(existing["id"])["chat"] == existing
    assert [chat["title"] for chat in created] == titles
    assert len({chat["display_title"] for chat in created}) == len(titles)
    assert [chat["chat_number"] for chat in created] == list(range(1, len(titles) + 1))
    for chat in created:
        assert_identity(chat)
    store.archive_chat(created[0]["id"])
    assert_identity(store.removed_items()["chats"][0], number=1, title=titles[0])


def test_legacy_backfill_is_deterministic_additive_and_idempotent(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    store = WorkspaceStore(path)
    project = store.create_project("Existing project")
    chats = [store.project_draft(project["id"])] + [
        store.create_global_chat("Same name") for _ in range(3)
    ]
    scope, _ = store.research_inputs(chats[1]["id"])
    store.append_research(
        chats[1]["id"],
        scope,
        "A vague test request",
        outcome(decision("clarification_required", "materials_scope_needed")),
    )
    store.archive_chat(chats[2]["id"])
    store.archive_project(project["id"])
    with store._connection(write=True) as connection:
        # Model the old schema and tied timestamps without modifying any UUID.
        connection.execute("DROP TABLE chat_identities")
        connection.execute("UPDATE chats SET created_at='2026-01-01T00:00:00Z'")
        expected_order = [
            row[0]
            for row in connection.execute("SELECT id FROM chats ORDER BY created_at,id")
        ]
        preserved_tables = (
            "chats",
            "projects",
            "messages",
            "message_intakes",
            "archived_chats",
            "archived_projects",
            "reports",
            "sources",
        )
        before = {
            table: [
                tuple(row)
                for row in connection.execute(f"SELECT * FROM {table} ORDER BY rowid")
            ]
            for table in preserved_tables
        }
    reopened = WorkspaceStore(path)
    reopened.initialize()
    with reopened._connection() as connection:
        assert [
            tuple(row)
            for row in connection.execute(
                "SELECT chat_id,chat_number FROM chat_identities ORDER BY chat_number"
            )
        ] == [(identifier, i + 1) for i, identifier in enumerate(expected_order)]
        for table, rows in before.items():
            assert [
                tuple(row)
                for row in connection.execute(f"SELECT * FROM {table} ORDER BY rowid")
            ] == rows
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    snapshot = reopened.removed_items()
    assert WorkspaceStore(path).removed_items() == snapshot


def test_identity_survives_first_prompt_rename_move_restore_and_draft_reuse(tmp_path):
    store = WorkspaceStore(tmp_path / "w.sqlite3")
    first = store.create_project("First project")
    second = store.create_project("Second project")
    chat = store.project_draft(first["id"])
    identifier, number = chat["id"], chat["chat_number"]
    assert store.project_draft(first["id"])["id"] == identifier
    response = store.append_research(
        identifier,
        first["id"],
        "Compare optical polymer coatings",
        outcome(decision("clarification_required", "research_details_needed")),
    )
    assert response["chat"]["title"] != UNTITLED_CHAT
    assert_identity(response["chat"], number=number)
    another_draft = store.project_draft(first["id"])
    assert another_draft["id"] != identifier
    assert another_draft["chat_number"] > number
    renamed = store.update_chat(identifier, title="Shared title")
    assert_identity(renamed["chat"], number=number, title="Shared title")
    for destination in (second["id"], None, first["id"]):
        moved = store.move_chat(identifier, destination)
        assert moved["chat"]["id"] == identifier
        assert moved["chat"]["project_id"] == destination
        assert_identity(moved["chat"], number=number, title="Shared title")
        assert moved["messages"] == response["messages"]
        assert sum(item["id"] == identifier for item in store.list_all_chats()) == 1
    store.archive_chat(identifier)
    assert_identity(store.removed_items()["chats"][0], number=number)
    restored = WorkspaceStore(store.path).restore_chat(identifier)
    assert_identity(restored["chat"], number=number, title="Shared title")
    assert restored["messages"] == response["messages"]
    store.archive_project(first["id"])
    reopened = WorkspaceStore(store.path)
    reopened.restore_project(first["id"])
    assert_identity(reopened.get_global_chat(identifier)["chat"], number=number)


def test_numbers_are_not_reused_after_highest_chat_or_project_is_purged(tmp_path):
    store = WorkspaceStore(tmp_path / "w.sqlite3")
    first = store.create_global_chat("Delete first")
    second = store.create_global_chat("Delete highest")
    for chat in (first, second):
        store.archive_chat(chat["id"])
        store.purge_chat(chat["id"], confirm=True)
    reopened = WorkspaceStore(store.path)
    third = reopened.create_global_chat("New chat")
    assert third["chat_number"] > second["chat_number"]
    project = reopened.create_project("Delete project")
    child = reopened.project_draft(project["id"])
    reopened.archive_project(project["id"])
    reopened.purge_project(project["id"], confirm=True)
    newest = WorkspaceStore(store.path).create_global_chat("Newest")
    assert newest["chat_number"] > child["chat_number"]
    with store._connection() as connection:
        assert (
            connection.execute("SELECT COUNT(*) FROM chat_identities").fetchone()[0]
            == 2
        )
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_concurrent_creation_assigns_unique_committed_numbers(tmp_path):
    store = WorkspaceStore(tmp_path / "concurrent.sqlite3")
    with ThreadPoolExecutor(max_workers=4) as executor:
        chats = list(
            executor.map(lambda _: store.create_global_chat("Same title"), range(12))
        )
    assert len({chat["id"] for chat in chats}) == 12
    assert sorted(chat["chat_number"] for chat in chats) == list(range(1, 13))
    assert len({chat["display_title"] for chat in chats}) == 12
    assert len(store.list_all_chats()) == 12


def test_concurrent_migration_does_not_assign_multiple_numbers_to_legacy_chats(
    tmp_path,
):
    path = tmp_path / "legacy-concurrent.sqlite3"
    store = WorkspaceStore(path)
    original = [store.create_global_chat("Same title") for _ in range(6)]
    with store._connection(write=True) as connection:
        connection.execute("DROP TABLE chat_identities")
    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(lambda _: WorkspaceStore(path), range(8)))
    after = store.list_all_chats()
    assert {chat["id"] for chat in after} == {chat["id"] for chat in original}
    assert sorted(chat["chat_number"] for chat in after) == list(range(1, 7))
    with store._connection() as connection:
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_chat_creation_and_number_assignment_roll_back_together(tmp_path):
    store = WorkspaceStore(tmp_path / "rollback.sqlite3")
    project = store.create_project("Keep")
    before = store.list_chats(project["id"])
    with store._connection(write=True) as connection:
        connection.execute(
            "CREATE TRIGGER fail_identity BEFORE INSERT ON chat_identities "
            "BEGIN SELECT RAISE(ABORT, 'TEST ONLY'); END"
        )
    with pytest.raises(sqlite3.IntegrityError):
        store.create_chat(project["id"], "Never created")
    assert store.list_chats(project["id"]) == before
    with store._connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM chats").fetchone()[0] == 1
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_api_uses_uuid_routing_with_stable_numbers_in_all_chat_shapes(tmp_path):
    with TestClient(
        create_app(workspace_path=tmp_path / "api.sqlite3"), base_url="http://localhost"
    ) as client:
        project = client.post("/api/projects", json={"name": "Test project"}).json()
        created = client.post("/api/chats", json={"title": "Same name"}).json()
        number, identifier = created["chat_number"], created["id"]
        project_id = project["id"]
        assert_identity(created)
        assert client.get(f"/api/chats/{number}").status_code == 404
        assert_identity(
            client.get(f"/api/chats/{identifier}").json()["chat"], number=number
        )
        moved = client.patch(
            f"/api/chats/{identifier}", json={"project_id": project_id}
        ).json()
        assert_identity(moved["chat"], number=number)
        for path, key in (
            ("/api/chats", "chats"),
            (f"/api/projects/{project_id}/chats", "chats"),
            (f"/api/projects/{project_id}/contents", "chats"),
            (f"/api/projects/{project_id}/context", "chats"),
        ):
            chat = next(
                item
                for item in client.get(path).json()[key]
                if item["id"] == identifier
            )
            assert_identity(chat, number=number)
        assert client.delete(f"/api/chats/{identifier}").status_code == 204
        assert_identity(client.get("/api/removed").json()["chats"][0], number=number)
        restored = client.post(f"/api/chats/{identifier}/restore").json()
        assert_identity(restored["chat"], number=number)
        for field in ("chat_number", "display_title"):
            assert (
                client.patch(
                    f"/api/chats/{identifier}", json={field: "changed"}
                ).status_code
                == 422
            )
            assert (
                client.post(
                    "/api/chats", json={"title": "New", field: "changed"}
                ).status_code
                == 422
            )
