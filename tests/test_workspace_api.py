"""Router contract tests; host/origin protection belongs to the
containing app."""

import sqlite3
from dataclasses import replace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from labcat.config import load_config
from labcat.workspace import WorkspaceStore
from labcat.workspace_api import create_router


@pytest.fixture
def client(tmp_path):
    app = FastAPI()
    app.include_router(
        create_router(WorkspaceStore(tmp_path / "state.sqlite3"), load_config())
    )
    with TestClient(app) as test_client:
        yield test_client


def create_project_chat(client):
    project = client.post("/api/projects", json={"name": "Test project"})
    assert project.status_code == 201
    project_id = project.json()["id"]
    chat = client.post(
        f"/api/projects/{project_id}/chats", json={"title": "Test conversation"}
    )
    assert chat.status_code == 201
    return project_id, chat.json()["id"]


def test_full_project_message_report_and_pin_contract(client):
    assert client.get("/api/projects").json() == {"projects": []}
    project_id, chat_id = create_project_chat(client)
    route = f"/api/projects/{project_id}/chats/{chat_id}"
    detail = client.get(route).json()
    assert detail["messages"] == detail["reports"] == detail["sources"] == []
    response = client.post(
        route + "/messages", json={"content": "Public evidence only"}
    )
    assert response.status_code == 201
    detail = response.json()
    assert len(detail["messages"]) == 2
    report = detail["reports"][0]
    assert {"pi_summary", "technical_audit", "source_ids", "pinned"} <= report.keys()
    assert report["source_ids"] == []
    assert report["project_id"] == project_id
    assert report["chat_id"] == chat_id
    assert report["message_id"] == detail["messages"][1]["id"]
    pin_route = f"/api/projects/{project_id}/pins"
    for _ in range(2):
        assert (
            client.post(
                pin_route, json={"kind": "report", "target_id": report["id"]}
            ).status_code
            == 201
        )
    contents = client.get(f"/api/projects/{project_id}/contents").json()
    assert len(contents["chats"]) == 2  # Starter plus explicitly created chat.
    assert len(contents["reports"]) == 1
    assert contents["reports"][0]["pinned"] is True
    context = client.get(f"/api/projects/{project_id}/context").json()
    assert context["boundaries"]["user_context_is_evidence"] is False
    deleted = client.delete(pin_route + "/report/" + report["id"])
    assert deleted.status_code == 204
    assert deleted.content == b""


@pytest.mark.parametrize(
    "payload",
    [
        {"content": "request", "role": "assistant"},
        {"content": "request", "provenance_status": "verified"},
        {"content": "request", "sources": [{"value": 123}]},
        {"content": "   "},
        {"content": "x" * 20001},
    ],
)
def test_message_schema_rejects_authority_and_provenance_input(client, payload):
    project_id, chat_id = create_project_chat(client)
    route = f"/api/projects/{project_id}/chats/{chat_id}"
    assert client.post(route + "/messages", json=payload).status_code == 422
    assert client.get(route).json()["messages"] == []


@pytest.mark.parametrize(
    "payload", [{"name": " "}, {"name": "x" * 121}, {"name": "a", "role": "admin"}]
)
def test_project_schema_rejects_invalid_names_and_extra_fields(client, payload):
    assert client.post("/api/projects", json=payload).status_code == 422
    assert client.get("/api/projects").json() == {"projects": []}


def test_cross_project_access_and_unknown_ids_return_404(client):
    first_id, first_chat = create_project_chat(client)
    second_id, _ = create_project_chat(client)
    route = f"/api/projects/{second_id}/chats/{first_chat}"
    assert client.get(route).status_code == 404
    assert (
        client.post(route + "/messages", json={"content": "request"}).status_code == 404
    )
    assert client.get("/api/projects/missing/contents").status_code == 404
    assert client.get("/api/projects/missing/context").status_code == 404
    report = client.post(
        f"/api/projects/{first_id}/chats/{first_chat}/messages",
        json={"content": "request"},
    ).json()["reports"][0]
    assert (
        client.post(
            f"/api/projects/{second_id}/pins",
            json={"kind": "report", "target_id": report["id"]},
        ).status_code
        == 404
    )


def test_no_http_api_can_insert_scientific_sources(client):
    project_id, _ = create_project_chat(client)
    response = client.post(
        f"/api/projects/{project_id}/sources",
        json={"url": "https://example.invalid", "provenance_status": "verified"},
    )
    assert response.status_code == 404
    assert client.get(f"/api/projects/{project_id}/contents").json()["sources"] == []


def test_storage_errors_do_not_disclose_paths_or_internal_data(tmp_path, monkeypatch):
    store = WorkspaceStore(tmp_path / "state.sqlite3")

    def fail():
        raise sqlite3.OperationalError("PRIVATE_PATH_AND_INTERNAL_DETAILS")

    monkeypatch.setattr(store, "list_projects", fail)
    app = FastAPI()
    app.include_router(create_router(store, load_config()))
    with TestClient(app) as client:
        result = client.get("/api/projects")
    assert result.status_code == 503
    assert "PRIVATE_PATH" not in result.text


def test_global_standalone_chat_endpoints_preserve_history_when_attached_and_detached(
    client,
):
    assert client.get("/api/chats").json() == {"chats": []}
    standalone = client.post("/api/chats", json={"title": "Standalone"})
    assert standalone.status_code == 201
    chat = standalone.json()
    assert chat["project_id"] is None
    route = f"/api/chats/{chat['id']}"
    detail = client.post(
        route + "/messages", json={"content": "A saved request"}
    ).json()
    assert detail["reports"][0]["project_id"] is None
    assert client.get("/api/projects").json() == {"projects": []}
    project = client.post("/api/projects", json={"name": "Destination"}).json()
    moved = client.patch(route, json={"project_id": project["id"]})
    assert moved.status_code == 200
    assert moved.json()["messages"] == detail["messages"]
    assert moved.json()["chat"]["project_id"] == project["id"]
    old_project_route = f"/api/projects/{project['id']}/chats/{chat['id']}"
    assert client.get(old_project_route).status_code == 200
    detached = client.patch(route, json={"project_id": None})
    assert detached.status_code == 200
    assert detached.json()["chat"]["project_id"] is None
    assert client.get(old_project_route).status_code == 404
    assert client.get(route).json()["messages"] == detail["messages"]
    assert client.get("/api/chats").json()["chats"][0]["project_id"] is None


@pytest.mark.parametrize(
    "payload", [{}, {"project_id": 12}, {"project_id": None, "role": "admin"}]
)
def test_global_chat_move_schema_rejects_invalid_or_extra_fields(client, payload):
    chat = client.post("/api/chats", json={"title": "Standalone"}).json()
    response = client.patch(f"/api/chats/{chat['id']}", json=payload)
    assert response.status_code == 422
    assert client.get(f"/api/chats/{chat['id']}").json()["chat"]["project_id"] is None


def test_unknown_global_chat_or_project_cannot_be_used(client):
    assert client.get("/api/chats/missing").status_code == 404
    assert (
        client.post(
            "/api/chats/missing/messages", json={"content": "request"}
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/api/chats", json={"title": "Chat", "project_id": "missing"}
        ).status_code
        == 404
    )
    chat = client.post("/api/chats", json={"title": "Standalone"}).json()
    assert (
        client.patch(
            f"/api/chats/{chat['id']}", json={"project_id": "missing"}
        ).status_code
        == 404
    )


def test_internal_scope_ids_are_not_usable_through_project_api(tmp_path):
    store = WorkspaceStore(tmp_path / "state.sqlite3")
    chat = store.create_global_chat("Standalone")
    detail = store.append_global_message(chat["id"], "request", load_config())
    with sqlite3.connect(store.path) as connection:
        hidden = connection.execute("SELECT project_id FROM chats").fetchone()[0]
    app = FastAPI()
    app.include_router(create_router(store, load_config()))
    with TestClient(app) as client:
        for suffix in ("chats", "contents", "context", f"chats/{chat['id']}"):
            assert client.get(f"/api/projects/{hidden}/{suffix}").status_code == 404
        assert (
            client.post(
                f"/api/projects/{hidden}/chats", json={"title": "Forbidden"}
            ).status_code
            == 404
        )
        assert (
            client.post(
                f"/api/projects/{hidden}/pins",
                json={"kind": "report", "target_id": detail["reports"][0]["id"]},
            ).status_code
            == 404
        )
        assert (
            client.patch(
                f"/api/chats/{chat['id']}", json={"project_id": hidden}
            ).status_code
            == 404
        )


def test_report_settings_are_read_at_message_time_and_old_reports_are_preserved(
    tmp_path,
):
    current = {"config": load_config()}
    store = WorkspaceStore(tmp_path / "state.sqlite3")
    app = FastAPI()
    app.include_router(
        create_router(store, current["config"], lambda: current["config"])
    )
    with TestClient(app) as client:
        chat = client.post("/api/chats", json={"title": "Settings"}).json()
        route = f"/api/chats/{chat['id']}/messages"
        first = client.post(route, json={"content": "First request"}).json()["reports"][
            0
        ]
        current["config"] = replace(
            current["config"],
            presentation=replace(current["config"].presentation, format="json"),
        )
        reports = client.post(route, json={"content": "Second request"}).json()[
            "reports"
        ]
    assert reports[0] == first
    assert reports[1]["pi_summary"].lstrip().startswith("{")
    assert reports[1]["technical_audit"].lstrip().startswith("{")


def test_settings_read_failure_is_sanitized_before_saving_a_message(tmp_path):
    store = WorkspaceStore(tmp_path / "state.sqlite3")

    def fail():
        raise sqlite3.DatabaseError("PRIVATE_SETTINGS_DETAILS")

    app = FastAPI()
    app.include_router(create_router(store, load_config(), fail))
    with TestClient(app) as client:
        chat = client.post("/api/chats", json={"title": "Settings"}).json()
        route = f"/api/chats/{chat['id']}"
        failed = client.post(route + "/messages", json={"content": "Request"})
        assert failed.status_code == 503
        assert "PRIVATE_SETTINGS" not in failed.text
        assert client.get(route).json()["messages"] == []
