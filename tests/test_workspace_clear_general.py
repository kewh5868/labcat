"""Confirmed, recoverable bulk removal uses only disposable local
workspaces."""

import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from labcat.config import load_config
from labcat.research_progress import ResearchProgress
from labcat.web import create_app
from labcat.workspace import (
    WorkspaceGeneralChatsConflict,
    WorkspaceNotFound,
    WorkspaceStore,
)
from labcat.workspace_api import create_router


def saved_report(store, chat):
    """Save test-only report metadata without material facts or public
    evidence."""
    scope, _ = store.research_inputs(chat["id"])
    return store.append_research(
        chat["id"],
        scope,
        "TEST ONLY: navigation history",
        {
            "stage": "complete",
            "answer": "TEST ONLY: saved response",
            "pi_summary": "TEST ONLY: saved summary",
            "technical_audit": "TEST ONLY: saved detail",
            "sources": [],
            "result": {"stage": "complete"},
        },
    )


def persistent_rows(store):
    with store._connection() as connection:
        names = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
        ]
        return {
            name: [tuple(row) for row in connection.execute(f'SELECT * FROM "{name}"')]
            for name in names
            if name != "archived_chats"
        }


def test_bulk_clear_preserves_all_saved_rows_and_project_pins_and_restores(tmp_path):
    store = WorkspaceStore(tmp_path / "workspace.sqlite3")
    first = store.create_global_chat("First general")
    second = store.create_global_chat("Second general")
    first_detail = saved_report(store, first)
    second_detail = saved_report(store, second)
    old_removed = store.create_global_chat("Already removed")
    store.archive_chat(old_removed["id"])
    project = store.create_project("Keep project")
    project_chat = store.project_draft(project["id"])
    detail = saved_report(store, project_chat)
    store.set_pin(project["id"], "report", detail["reports"][0]["id"])
    store.set_report_tracking(project["id"], project_chat["id"])
    project_detail = store.get_global_chat(project_chat["id"])
    archived_project = store.create_project("Already removed project")
    store.archive_project(archived_project["id"])
    store.save_workspace_preferences(confirm_removal=False)
    with store._connection(write=True) as connection:
        connection.execute("INSERT INTO app_settings VALUES(1,?)", ('{"test":true}',))
    before = persistent_rows(store)
    previously_removed = store.removed_items()

    assert store.archive_general_chats(
        confirm=True, snapshot=[second["id"], first["id"]]
    ) == {"removed_chats": 2}
    assert persistent_rows(store) == before
    assert store.workspace_preferences() == {"confirm_removal": False}
    assert [chat["id"] for chat in store.list_all_chats()] == [project_chat["id"]]
    assert store.get_global_chat(project_chat["id"]) == project_detail
    removed = store.removed_items()
    assert removed["projects"] == previously_removed["projects"]
    assert next(row for row in removed["chats"] if row["id"] == old_removed["id"]) == (
        previously_removed["chats"][0]
    )
    assert {row["id"] for row in removed["chats"]} == {
        first["id"],
        second["id"],
        old_removed["id"],
    }
    for chat in (first, second):
        with pytest.raises(WorkspaceNotFound):
            store.get_global_chat(chat["id"])
    reopened = WorkspaceStore(store.path)
    assert reopened.restore_chat(first["id"]) == first_detail
    assert reopened.restore_chat(second["id"]) == second_detail
    assert reopened.removed_items() == previously_removed
    with reopened._connection() as connection:
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


@pytest.mark.parametrize("change", ["new", "removed", "moved_in", "moved_out"])
def test_changed_general_membership_rejects_every_removal(tmp_path, change):
    store = WorkspaceStore(tmp_path / "workspace.sqlite3")
    first = store.create_global_chat("First")
    second = store.create_global_chat("Second")
    project = store.create_project("Keep project")
    project_chat = store.project_draft(project["id"])
    snapshot = [first["id"], second["id"]]
    if change == "new":
        store.create_global_chat("New since confirmation")
    elif change == "removed":
        store.archive_chat(first["id"])
    elif change == "moved_in":
        store.update_chat(project_chat["id"], project_id=None)
    else:
        store.update_chat(first["id"], project_id=project["id"])
    visible = store.list_all_chats()
    removed = store.removed_items()
    with pytest.raises(WorkspaceGeneralChatsConflict, match="General chats changed"):
        store.archive_general_chats(confirm=True, snapshot=snapshot)
    assert store.list_all_chats() == visible
    assert store.removed_items() == removed


def test_archive_failure_rolls_back_every_general_chat(tmp_path):
    store = WorkspaceStore(tmp_path / "workspace.sqlite3")
    chats = [store.create_global_chat(title) for title in ("First", "Second")]
    with store._connection(write=True) as connection:
        connection.execute(
            "CREATE TRIGGER fail_second_archive BEFORE INSERT ON archived_chats "
            "WHEN EXISTS(SELECT 1 FROM archived_chats) "
            "BEGIN SELECT RAISE(ABORT, 'TEST ONLY: archive failure'); END"
        )
    before = store.list_all_chats()
    with pytest.raises(sqlite3.IntegrityError, match="archive failure"):
        store.archive_general_chats(
            confirm=True, snapshot=[chat["id"] for chat in chats]
        )
    assert store.list_all_chats() == before
    assert store.removed_items()["chats"] == []


@pytest.mark.parametrize("confirm", [False, None, 0, 1, "true"])
def test_store_requires_literal_confirmation(tmp_path, confirm):
    store = WorkspaceStore(tmp_path / "workspace.sqlite3")
    chat = store.create_global_chat("Keep")
    with pytest.raises(ValueError, match="explicit confirmation"):
        store.archive_general_chats(confirm=confirm, snapshot=[chat["id"]])
    assert store.get_global_chat(chat["id"])["chat"] == chat


@pytest.fixture
def signed_client(tmp_path):
    with TestClient(
        create_app(workspace_path=tmp_path / "workspace.sqlite3"),
        base_url="http://localhost",
    ) as client:
        token = client.get("/api/session").json()["csrf_token"]
        client.headers["X-CSRF-Token"] = token
        yield client


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"snapshot": []},
        {"confirm": False, "snapshot": []},
        {"confirm": "true", "snapshot": []},
        {"confirm": 1, "snapshot": []},
        {"confirm": True},
        {"confirm": True, "snapshot": None},
        {"confirm": True, "snapshot": "all"},
        {"confirm": True, "snapshot": [""]},
        {"confirm": True, "snapshot": ["x" * 65]},
        {"confirm": True, "snapshot": [123]},
        {"confirm": True, "snapshot": ["duplicate", "duplicate"]},
        {"confirm": True, "snapshot": [], "project_id": "other"},
    ],
)
def test_bulk_api_requires_confirmation_and_valid_reviewed_snapshot(
    signed_client, payload
):
    client = signed_client
    chat = client.post("/api/chats", json={"title": "Keep"}).json()
    response = client.request("DELETE", "/api/general-chats", json=payload)
    assert response.status_code == 422
    assert client.get("/api/chats").json()["chats"] == [chat]
    assert client.get("/api/removed").json()["chats"] == []


def test_bulk_api_stale_confirmation_success_restore_and_empty_case(signed_client):
    client = signed_client
    project = client.post("/api/projects", json={"name": "Keep project"}).json()
    project_chat = client.post(f"/api/projects/{project['id']}/draft-chat").json()
    chat = client.post("/api/chats", json={"title": "Remove"}).json()
    assert (
        client.put(
            "/api/workspace/preferences", json={"confirm_removal": False}
        ).status_code
        == 200
    )
    response = client.request(
        "DELETE", "/api/general-chats", json={"confirm": True, "snapshot": []}
    )
    assert response.status_code == 409
    assert "General chats changed" in response.json()["detail"]
    response = client.request(
        "DELETE",
        "/api/general-chats",
        json={"confirm": True, "snapshot": [chat["id"]]},
    )
    assert response.status_code == 200
    assert response.json() == {"removed_chats": 1}
    assert client.get("/api/chats").json()["chats"] == [project_chat]
    assert client.get(f"/api/chats/{chat['id']}").status_code == 404
    assert client.get("/api/workspace/preferences").json() == {"confirm_removal": False}
    assert client.request(
        "DELETE", "/api/general-chats", json={"confirm": True, "snapshot": []}
    ).json() == {"removed_chats": 0}
    assert client.post(f"/api/chats/{chat['id']}/restore").json()["chat"] == chat


@pytest.mark.parametrize(
    "attack", ["no_token", "bad_token", "no_cookie", "origin", "site"]
)
def test_bulk_api_requires_same_origin_session_and_csrf(signed_client, attack):
    client = signed_client
    chat = client.post("/api/chats", json={"title": "Keep"}).json()
    headers = {}
    if attack == "no_token":
        del client.headers["X-CSRF-Token"]
    elif attack == "bad_token":
        client.headers["X-CSRF-Token"] = "incorrect"
    elif attack == "no_cookie":
        client.cookies.clear()
    elif attack == "origin":
        headers["Origin"] = "https://attacker.invalid"
    else:
        headers["Sec-Fetch-Site"] = "cross-site"
    response = client.request(
        "DELETE",
        "/api/general-chats",
        json={"confirm": True, "snapshot": [chat["id"]]},
        headers=headers,
    )
    assert response.status_code == 403
    assert client.get("/api/chats").json()["chats"] == [chat]
    assert client.get("/api/removed").json()["chats"] == []


def test_bulk_api_refuses_running_general_research_but_ignores_project_research(
    tmp_path,
):
    store = WorkspaceStore(tmp_path / "workspace.sqlite3")
    general = store.create_global_chat("General")
    project = store.create_project("Project")
    project_chat = store.project_draft(project["id"])
    running = {general["id"], project_chat["id"]}
    workflow = SimpleNamespace(
        progress=SimpleNamespace(busy=lambda chat_id: chat_id in running)
    )
    app = FastAPI()
    app.include_router(create_router(store, load_config(), research_workflow=workflow))
    with TestClient(app) as client:
        payload = {"confirm": True, "snapshot": [general["id"]]}
        response = client.request("DELETE", "/api/general-chats", json=payload)
        assert response.status_code == 409
        assert "still researching" in response.json()["detail"]
        assert store.get_global_chat(general["id"])["chat"] == general
        assert store.removed_items()["chats"] == []
        running.remove(general["id"])
        response = client.request("DELETE", "/api/general-chats", json=payload)
        assert response.status_code == 200
        assert response.json() == {"removed_chats": 1}
        assert store.get_global_chat(project_chat["id"])["chat"] == project_chat


def test_bulk_api_cannot_archive_a_chat_awaiting_model_readiness(tmp_path):
    store = WorkspaceStore(tmp_path / "workspace.sqlite3")
    chat = store.create_global_chat("Untitled chat")
    progress = ResearchProgress()
    app = FastAPI()
    app.include_router(
        create_router(
            store, load_config(), research_workflow=SimpleNamespace(progress=progress)
        )
    )
    verifying, verified = threading.Event(), threading.Event()

    def readiness():
        verifying.set()
        assert verified.wait(5)

    def request():
        with progress.track(chat["id"], before_start=readiness):
            pass

    with TestClient(app) as client, ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(request)
        payload = {"confirm": True, "snapshot": [chat["id"]]}
        try:
            assert verifying.wait(2)
            assert progress.snapshot(chat["id"])["status"] == "idle"
            assert progress.running() == []
            response = client.request("DELETE", "/api/general-chats", json=payload)
            assert response.status_code == 409
            assert store.get_global_chat(chat["id"])["chat"] == chat
            assert store.removed_items()["chats"] == []
        finally:
            verified.set()
        pending.result(timeout=2)
        assert not progress.busy(chat["id"])
        assert client.request("DELETE", "/api/general-chats", json=payload).json() == {
            "removed_chats": 1
        }
