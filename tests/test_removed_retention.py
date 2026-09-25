"""Thirty-day recovery and bulk deletion use disposable SQLite databases
only."""

import re
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta, timezone
from threading import Barrier, Event

import pytest
from fastapi.testclient import TestClient

from labcat.web import create_app
from labcat.workspace import (
    WorkspaceNotFound,
    WorkspaceRemovedConflict,
    WorkspaceRestoreConflict,
    WorkspaceStore,
)


def removal_time(store, kind, identifier, timestamp):
    table, key = (
        ("archived_projects", "project_id")
        if kind == "project"
        else ("archived_chats", "chat_id")
    )
    with store._connection(write=True) as connection:
        connection.execute(
            f"UPDATE {table} SET archived_at=? WHERE {key}=?",
            (
                timestamp.isoformat() if isinstance(timestamp, datetime) else timestamp,
                identifier,
            ),
        )


def ids(store, table):
    with store._connection() as connection:
        return {row[0] for row in connection.execute(f"SELECT id FROM {table}")}


def assert_integrity(store):
    with store._connection() as connection:
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


@pytest.mark.parametrize("kind", ["project", "chat"])
def test_retention_cutoff_exactly_thirty_days_and_timezone_offsets(tmp_path, kind):
    store = WorkspaceStore(tmp_path / "w.sqlite3")
    create = store.create_project if kind == "project" else store.create_global_chat
    archive = store.archive_project if kind == "project" else store.archive_chat
    removed_at = datetime(2026, 1, 31, 20, 45, tzinfo=timezone(timedelta(hours=-7)))
    cutoff = removed_at.astimezone(UTC) + timedelta(days=30)
    items = [create(f"TEST ONLY {i}") for i in range(4)]
    for item, age in zip(items[:3], [-1, 0, 1], strict=True):
        archive(item["id"])
        removal_time(store, kind, item["id"], removed_at + timedelta(microseconds=age))
    # An old created_at is never a removal timestamp.
    with store._connection(write=True) as connection:
        connection.execute(f"UPDATE {kind}s SET created_at='1900-01-01T00:00:00Z'")
    assert store.purge_expired(cutoff - timedelta(microseconds=2)) == {
        "projects": 0,
        "chats": 0,
    }
    assert store.purge_expired(cutoff) == {
        "projects": 2 if kind == "project" else 0,
        "chats": 2,
    }
    assert ids(store, f"{kind}s") == {item["id"] for item in items[2:]}
    assert store.purge_expired(cutoff + timedelta(microseconds=1)) == {
        "projects": 1 if kind == "project" else 0,
        "chats": 1,
    }
    assert ids(store, f"{kind}s") == {items[3]["id"]}
    assert_integrity(store)


@pytest.mark.parametrize(
    "timestamp",
    [
        "TEST ONLY invalid",
        "",
        "2020-01-01",
        "2020-01-01T00:00:00",
        "9999-12-31T00:00:00Z",
    ],
)
@pytest.mark.parametrize("kind", ["project", "chat"])
def test_bad_removal_times_are_preserved_without_preventing_other_cleanup(
    tmp_path, timestamp, kind
):
    store = WorkspaceStore(tmp_path / "w.sqlite3")
    create = store.create_project if kind == "project" else store.create_global_chat
    archive = store.archive_project if kind == "project" else store.archive_chat
    unknown = create("TEST ONLY malformed age")
    expired = create("TEST ONLY expired")
    for item in (unknown, expired):
        archive(item["id"])
    removal_time(store, kind, unknown["id"], timestamp)
    removal_time(store, kind, expired["id"], datetime.now(UTC) - timedelta(days=31))
    items = store.removed_items()
    assert [item["id"] for item in items[f"{kind}s"]] == [unknown["id"]]
    assert items[f"{kind}s"][0]["expires_at"] is None
    assert items[f"{kind}s"][0]["archived_at"] == timestamp
    assert expired["id"] not in ids(store, f"{kind}s")
    restore = store.restore_project if kind == "project" else store.restore_chat
    restore(unknown["id"])
    assert unknown["id"] in ids(store, f"{kind}s")
    assert_integrity(store)


@pytest.mark.parametrize("child_first", [False, True])
def test_project_and_individual_child_use_earlier_deadline(tmp_path, child_first):
    store = WorkspaceStore(tmp_path / "w.sqlite3")
    project = store.create_project("TEST ONLY parent")
    child = store.project_draft(project["id"])
    sibling = store.create_chat(project["id"], "TEST ONLY hidden sibling")
    store.archive_chat(child["id"])
    store.archive_project(project["id"])
    now = datetime.now(UTC)
    first, later = now - timedelta(days=29), now - timedelta(days=5)
    child_time, project_time = (first, later) if child_first else (later, first)
    removal_time(store, "chat", child["id"], child_time)
    removal_time(store, "project", project["id"], project_time)
    items = store.removed_items()
    assert items["chats"][0]["expires_at"] == (first + timedelta(days=30)).isoformat()
    assert (
        items["projects"][0]["expires_at"]
        == (project_time + timedelta(days=30)).isoformat()
    )
    counts = store.purge_expired(first + timedelta(days=30))
    assert child["id"] not in ids(store, "chats")
    if child_first:
        assert counts == {"projects": 0, "chats": 1}
        store.restore_project(project["id"])
        assert store.get_global_chat(sibling["id"])["chat"]["id"] == sibling["id"]
    else:
        assert counts == {"projects": 1, "chats": 2}
        assert sibling["id"] not in ids(store, "chats")
    assert_integrity(store)


@pytest.mark.parametrize("kind", ["project", "chat"])
def test_restore_commits_expiration_before_not_found(tmp_path, kind):
    store = WorkspaceStore(tmp_path / "w.sqlite3")
    item = (
        store.create_project("TEST ONLY expire on restore")
        if kind == "project"
        else store.create_global_chat("TEST ONLY expire on restore")
    )
    archive = store.archive_project if kind == "project" else store.archive_chat
    restore = store.restore_project if kind == "project" else store.restore_chat
    archive(item["id"])
    removal_time(store, kind, item["id"], datetime.now(UTC) - timedelta(days=31))
    with pytest.raises(WorkspaceNotFound):
        restore(item["id"])
    assert item["id"] not in ids(WorkspaceStore(store.path), f"{kind}s")
    assert_integrity(store)


def test_parent_expiration_cannot_be_bypassed_by_restoring_a_recent_child(tmp_path):
    store = WorkspaceStore(tmp_path / "w.sqlite3")
    project = store.create_project("TEST ONLY expired parent")
    child = store.project_draft(project["id"])
    store.archive_chat(child["id"])
    store.archive_project(project["id"])
    removal_time(
        store, "project", project["id"], datetime.now(UTC) - timedelta(days=31)
    )
    with pytest.raises(WorkspaceNotFound):
        store.restore_chat(child["id"])
    assert ids(store, "projects") == set()
    assert ids(store, "chats") == set()


def test_parent_restore_conflict_still_commits_unrelated_expiration(tmp_path):
    store = WorkspaceStore(tmp_path / "w.sqlite3")
    project = store.create_project("TEST ONLY parent")
    child = store.project_draft(project["id"])
    expired = store.create_global_chat("TEST ONLY expired")
    for chat in (child, expired):
        store.archive_chat(chat["id"])
    store.archive_project(project["id"])
    removal_time(store, "chat", expired["id"], datetime.now(UTC) - timedelta(days=31))
    with pytest.raises(WorkspaceRestoreConflict):
        store.restore_chat(child["id"])
    assert expired["id"] not in ids(store, "chats")
    assert child["id"] in ids(store, "chats")


@pytest.mark.parametrize("kind", ["project", "chat"])
def test_reopening_preserves_removal_age_but_restoring_then_removing_starts_again(
    tmp_path, kind
):
    store = WorkspaceStore(tmp_path / "w.sqlite3")
    create = store.create_project if kind == "project" else store.create_global_chat
    item = create("TEST ONLY remove again")
    getattr(store, f"archive_{kind}")(item["id"])
    old_time = datetime.now(UTC) - timedelta(days=29)
    removal_time(store, kind, item["id"], old_time)
    store = WorkspaceStore(store.path)
    before = store.removed_items()
    assert before[f"{kind}s"][0]["archived_at"] == old_time.isoformat()
    with pytest.raises(WorkspaceNotFound):
        getattr(store, f"archive_{kind}")(item["id"])
    assert store.removed_items() == before
    getattr(store, f"restore_{kind}")(item["id"])
    getattr(store, f"archive_{kind}")(item["id"])
    after = store.removed_items()
    assert after["snapshot"] != before["snapshot"]
    assert datetime.fromisoformat(
        after[f"{kind}s"][0]["expires_at"]
    ) > old_time + timedelta(days=58)
    assert store.purge_expired(old_time + timedelta(days=30)) == {
        "projects": 0,
        "chats": 0,
    }


def test_bulk_empty_is_valid_and_does_not_reset_chat_numbers(tmp_path):
    store = WorkspaceStore(tmp_path / "w.sqlite3")
    empty = store.removed_items()
    assert empty["retention_days"] == 30
    assert re.fullmatch("[0-9a-f]{64}", empty["snapshot"])
    assert store.purge_removed(confirm=True, snapshot=empty["snapshot"]) == {
        "projects": 0,
        "chats": 0,
    }
    chat = store.create_global_chat("TEST ONLY removed")
    store.archive_chat(chat["id"])
    assert store.purge_removed(
        confirm=True, snapshot=store.removed_items()["snapshot"]
    ) == {"projects": 0, "chats": 1}
    assert store.removed_items() == empty
    next_chat = store.create_global_chat("TEST ONLY preserved numbering")
    assert next_chat["chat_number"] > chat["chat_number"]


def test_bulk_counts_project_children_once_and_preserves_active_scopes(tmp_path):
    store = WorkspaceStore(tmp_path / "w.sqlite3")
    project = store.create_project("TEST ONLY removed project")
    child = store.create_chat(project["id"], "TEST ONLY individually removed child")
    general = store.create_global_chat("TEST ONLY removed standalone")
    active = store.create_project("TEST ONLY active project")
    sibling = store.create_chat(active["id"], "TEST ONLY removed sibling")
    preserved = store.project_draft(active["id"])
    for chat in (child, general, sibling):
        store.archive_chat(chat["id"])
    store.archive_project(project["id"])
    assert store.purge_removed(
        confirm=True, snapshot=store.removed_items()["snapshot"]
    ) == {"projects": 1, "chats": 4}
    assert ids(store, "projects") == {active["id"]}
    assert ids(store, "chats") == {preserved["id"]}
    assert store.get_global_chat(preserved["id"])["chat"] == preserved
    assert_integrity(store)


@pytest.mark.parametrize("confirm", [False, None, 0, 1, "true"])
def test_bulk_store_confirmation_is_strict(tmp_path, confirm):
    store = WorkspaceStore(tmp_path / "w.sqlite3")
    chat = store.create_global_chat("TEST ONLY preserve")
    store.archive_chat(chat["id"])
    before = store.removed_items()
    with pytest.raises(ValueError, match="confirmation"):
        store.purge_removed(confirm=confirm, snapshot=before["snapshot"])
    assert store.removed_items() == before


def test_bulk_rejects_changed_snapshot_and_newly_removed_items(tmp_path):
    store = WorkspaceStore(tmp_path / "w.sqlite3")
    first = store.create_global_chat("TEST ONLY reviewed")
    second = store.create_global_chat("TEST ONLY new removal")
    store.archive_chat(first["id"])
    snapshot = store.removed_items()["snapshot"]
    WorkspaceStore(store.path).archive_chat(second["id"])
    with pytest.raises(WorkspaceRemovedConflict):
        store.purge_removed(confirm=True, snapshot=snapshot)
    assert ids(store, "chats") == {first["id"], second["id"]}


def test_bulk_and_restore_serialize_without_deleting_restored_history(tmp_path):
    store = WorkspaceStore(tmp_path / "w.sqlite3")
    chat = store.create_global_chat("TEST ONLY restore race")
    store.archive_chat(chat["id"])
    snapshot = store.removed_items()["snapshot"]
    other = WorkspaceStore(store.path)
    barrier = Barrier(2)

    def restore():
        barrier.wait(timeout=5)
        try:
            other.restore_chat(chat["id"])
            return "restored"
        except WorkspaceNotFound:
            return "deleted"

    def purge():
        barrier.wait(timeout=5)
        try:
            store.purge_removed(confirm=True, snapshot=snapshot)
            return "deleted"
        except WorkspaceRemovedConflict:
            return "restored"

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(restore), pool.submit(purge)]
        results = [future.result(timeout=10) for future in futures]
    assert results in (["restored", "restored"], ["deleted", "deleted"])
    assert (chat["id"] in ids(store, "chats")) == (results[0] == "restored")
    assert_integrity(store)


def test_removal_waiting_on_bulk_lock_survives_the_reviewed_purge(
    tmp_path, monkeypatch
):
    store = WorkspaceStore(tmp_path / "w.sqlite3")
    first = store.create_global_chat("TEST ONLY reviewed")
    second = store.create_global_chat("TEST ONLY newly removed")
    store.archive_chat(first["id"])
    snapshot = store.removed_items()["snapshot"]
    other = WorkspaceStore(store.path)
    checked, proceed, removal_started = Event(), Event(), Event()
    original = store._removed_items

    def pause_snapshot(connection):
        result = original(connection)
        checked.set()
        assert proceed.wait(timeout=5)
        return result

    def remove_new():
        removal_started.set()
        other.archive_chat(second["id"])

    monkeypatch.setattr(store, "_removed_items", pause_snapshot)
    with ThreadPoolExecutor(max_workers=2) as pool:
        purge = pool.submit(store.purge_removed, confirm=True, snapshot=snapshot)
        assert checked.wait(timeout=5)
        removal = pool.submit(remove_new)
        assert removal_started.wait(timeout=5)
        proceed.set()
        assert purge.result(timeout=10) == {"projects": 0, "chats": 1}
        removal.result(timeout=10)
    assert ids(store, "chats") == {second["id"]}
    assert other.removed_items()["chats"][0]["id"] == second["id"]
    assert_integrity(store)


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {},
        {"confirm": True},
        {"confirm": False, "snapshot": "0" * 64},
        {"confirm": 1, "snapshot": "0" * 64},
        {"confirm": "true", "snapshot": "0" * 64},
        {"confirm": True, "snapshot": "bad"},
        {"confirm": True, "snapshot": "0" * 64, "force": True},
    ],
)
def test_bulk_api_rejects_missing_or_coerced_confirmation_and_snapshot(
    tmp_path, payload
):
    with TestClient(
        create_app(workspace_path=tmp_path / "w.sqlite3"), base_url="http://localhost"
    ) as client:
        token = client.get("/api/session").json()["csrf_token"]
        client.headers["X-CSRF-Token"] = token
        response = client.request("DELETE", "/api/removed", json=payload)
        assert response.status_code == 422


def test_bulk_api_needs_session_and_current_snapshot_and_preserves_active_items(
    tmp_path,
):
    path = tmp_path / "w.sqlite3"
    with TestClient(
        create_app(workspace_path=path), base_url="http://localhost"
    ) as client:
        active = client.post("/api/chats", json={"title": "TEST ONLY active"}).json()
        removed = client.post("/api/chats", json={"title": "TEST ONLY removed"}).json()
        assert client.delete(f"/api/chats/{removed['id']}").status_code == 204
        snapshot = client.get("/api/removed").json()["snapshot"]
        payload = {"confirm": True, "snapshot": snapshot}
        assert client.request("DELETE", "/api/removed", json=payload).status_code == 403
        token = client.get("/api/session").json()["csrf_token"]
        assert client.request("DELETE", "/api/removed", json=payload).status_code == 403
        client.headers["X-CSRF-Token"] = token
        assert (
            client.request(
                "DELETE",
                "/api/removed",
                json=payload,
                headers={"Origin": "https://example.invalid"},
            ).status_code
            == 403
        )
        assert (
            client.request(
                "DELETE", "/api/removed", json={"confirm": True, "snapshot": "0" * 64}
            ).status_code
            == 409
        )
        assert client.get(f"/api/chats/{active['id']}").status_code == 200
        response = client.request("DELETE", "/api/removed", json=payload)
        assert response.status_code == 204 and response.content == b""
        assert client.post(f"/api/chats/{removed['id']}/restore").status_code == 404
        assert client.get(f"/api/chats/{active['id']}").status_code == 200
    assert_integrity(WorkspaceStore(path))


def test_bulk_failure_rolls_back_every_removed_item(tmp_path):
    store = WorkspaceStore(tmp_path / "w.sqlite3")
    project = store.create_project("TEST ONLY removed project")
    chat = store.create_global_chat("TEST ONLY late failure")
    store.archive_project(project["id"])
    store.archive_chat(chat["id"])
    before = store.removed_items()
    with store._connection(write=True) as connection:
        connection.execute(
            "CREATE TRIGGER fail_bulk BEFORE DELETE ON chats "
            f"WHEN old.id='{chat['id']}' "
            "BEGIN SELECT RAISE(ABORT, 'TEST ONLY: deletion failure'); END"
        )
    with pytest.raises(sqlite3.IntegrityError):
        store.purge_removed(confirm=True, snapshot=before["snapshot"])
    assert store.removed_items() == before
    assert project["id"] in ids(store, "projects")
    assert_integrity(store)
