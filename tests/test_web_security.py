"""The local workspace accepts browser writes only from its own
origin."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from labcat import web


@pytest.fixture
def client(tmp_path):
    app = web.create_app(workspace_path=tmp_path / "workspace.sqlite3")
    with TestClient(app, base_url="http://127.0.0.1:8123") as test_client:
        yield test_client


@pytest.mark.parametrize(
    "headers",
    [
        {"Origin": "https://attacker.invalid"},
        {"Origin": "null"},
        {"Origin": "http://127.0.0.1:8124"},
        {"Origin": "http://localhost:8123"},
        {"Origin": "https://127.0.0.1:8123"},
        {"Origin": "http://127.0.0.1:8123/"},
        {"Sec-Fetch-Site": "cross-site"},
        {"Sec-Fetch-Site": "same-site"},
        {"Sec-Fetch-Site": "unknown"},
        {"Origin": "http://127.0.0.1:8123", "Sec-Fetch-Site": "cross-site"},
    ],
)
def test_untrusted_browser_writes_are_rejected_without_mutating_state(client, headers):
    response = client.post("/api/projects", json={"name": "Injected"}, headers=headers)
    assert response.status_code == 403
    assert "same-origin" in response.json()["detail"]
    assert response.headers["cache-control"] == "no-store"
    assert "access-control-allow-origin" not in response.headers
    assert client.get("/api/projects").json() == {"projects": []}


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Origin": "http://127.0.0.1:8123", "Sec-Fetch-Site": "same-origin"},
        {"Origin": "http://127.0.0.1:8123"},
        {"Sec-Fetch-Site": "none"},
    ],
)
def test_local_browser_and_command_line_clients_can_write(client, headers):
    response = client.post("/api/projects", json={"name": "Local"}, headers=headers)
    assert response.status_code == 201
    assert (
        client.get("/api/projects").json()["projects"][0]["id"] == response.json()["id"]
    )


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_every_mutating_method_checks_browser_origin(client, method):
    assert (
        client.request(
            method, "/api/projects", headers={"Origin": "https://attacker.invalid"}
        ).status_code
        == 403
    )


@pytest.mark.parametrize(
    "host", ["attacker.invalid", "127.0.0.1.attacker.invalid", "0.0.0.0", "testserver"]
)
def test_dns_rebinding_and_nonlocal_hosts_are_rejected(client, host):
    for method, path in [("GET", "/health"), ("POST", "/api/projects")]:
        response = client.request(
            method, path, headers={"Host": host}, json={"name": "Injected"}
        )
        assert response.status_code == 400
        assert response.headers["x-content-type-options"] == "nosniff"
    assert client.get("/api/projects").json() == {"projects": []}


def test_forwarded_headers_cannot_replace_origin_checks(client):
    response = client.post(
        "/api/projects",
        json={"name": "Injected"},
        headers={
            "Origin": "https://attacker.invalid",
            "X-Forwarded-Host": "attacker.invalid",
            "X-Forwarded-Proto": "https",
        },
    )
    assert response.status_code == 403


def test_duplicate_security_headers_are_rejected(client):
    for headers in (
        [("Origin", "http://127.0.0.1:8123"), ("Origin", "https://attacker.invalid")],
        [("Sec-Fetch-Site", "same-origin"), ("Sec-Fetch-Site", "cross-site")],
    ):
        response = client.post(
            "/api/projects", json={"name": "Injected"}, headers=headers
        )
        assert response.status_code == 403
    assert client.get("/api/projects").json() == {"projects": []}


def test_no_cross_origin_access_or_preflight_permissions(client):
    headers = {"Origin": "https://attacker.invalid"}
    read = client.get("/api/projects", headers=headers)
    assert read.status_code == 200
    preflight = client.options(
        "/api/projects",
        headers={**headers, "Access-Control-Request-Method": "POST"},
    )
    assert preflight.status_code == 405
    for response in (read, preflight):
        assert "access-control-allow-origin" not in response.headers
        assert "access-control-allow-credentials" not in response.headers


def test_development_proxy_can_preserve_its_local_origin(client):
    response = client.post(
        "/api/projects",
        json={"name": "Development"},
        headers={
            "Host": "localhost:5173",
            "Origin": "http://localhost:5173",
            "Sec-Fetch-Site": "same-origin",
        },
    )
    assert response.status_code == 201


@pytest.mark.parametrize("kind", ["projects", "chats"])
def test_permanent_deletion_requires_confirmed_same_origin_session(client, kind):
    body = (
        {"name": "Disposable project"}
        if kind == "projects"
        else {"title": "Disposable chat"}
    )
    item = client.post(f"/api/{kind}", json=body).json()
    assert client.delete(f"/api/{kind}/{item['id']}").status_code == 204
    assert (
        client.put(
            "/api/workspace/preferences", json={"confirm_removal": False}
        ).status_code
        == 200
    )
    path = f"/api/removed/{kind}/{item['id']}"
    token = client.get("/api/session").json()["csrf_token"]
    for headers in (
        {},
        {"X-CSRF-Token": "incorrect"},
        {"X-CSRF-Token": token, "Origin": "https://attacker.invalid"},
        {"X-CSRF-Token": token, "Sec-Fetch-Site": "cross-site"},
    ):
        response = client.request(
            "DELETE", path, json={"confirm": True}, headers=headers
        )
        assert response.status_code == 403
        assert item["id"] in {
            row["id"] for row in client.get("/api/removed").json()[kind]
        }
    headers = {"X-CSRF-Token": token, "Origin": "http://127.0.0.1:8123"}
    assert (
        client.request(
            "DELETE", path, json={"confirm": False}, headers=headers
        ).status_code
        == 422
    )
    assert (
        client.request(
            "DELETE", path, json={"confirm": True}, headers=headers
        ).status_code
        == 204
    )
    assert item["id"] not in {
        row["id"] for row in client.get("/api/removed").json()[kind]
    }
    assert client.post(f"/api/{kind}/{item['id']}/restore").status_code == 404


def test_workspace_starts_during_lifespan_and_survives_app_restart(tmp_path):
    database = tmp_path / "data" / "workspace.sqlite3"
    first = web.create_app(workspace_path=database)
    assert not database.exists()
    assert first.state.workspace_path == database
    with TestClient(first, base_url="http://localhost") as client:
        assert database.is_file()
        project = client.post("/api/projects", json={"name": "Persistent"}).json()
    second = web.create_app(workspace_path=database)
    with TestClient(second, base_url="http://localhost") as client:
        assert client.get("/api/projects").json()["projects"] == [project]


def test_site_data_directory_is_selected_without_creating_files(tmp_path, monkeypatch):
    directory = tmp_path / "configured"
    monkeypatch.setenv("LABCAT_DATA_DIR", str(directory))
    app = web.create_app()
    assert app.state.workspace_path == directory / "workspace.sqlite3"
    assert not directory.exists()


@pytest.mark.parametrize(
    ("platform", "expected"),
    [
        ("darwin", "Library/Application Support/Labcat/workspace.sqlite3"),
        ("win32", "AppData/Local/Labcat/workspace.sqlite3"),
        ("linux", ".local/share/labcat/workspace.sqlite3"),
    ],
)
def test_platform_data_directory_defaults(tmp_path, monkeypatch, platform, expected):
    for key in ("LABCAT_DATA_DIR", "LOCALAPPDATA", "XDG_DATA_HOME"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(web.sys, "platform", platform)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    assert web.default_workspace_path() == tmp_path / expected


@pytest.mark.parametrize(
    ("platform", "variable", "suffix"),
    [
        ("win32", "LOCALAPPDATA", "Labcat"),
        ("linux", "XDG_DATA_HOME", "labcat"),
    ],
)
def test_platform_data_directory_overrides(
    tmp_path, monkeypatch, platform, variable, suffix
):
    monkeypatch.delenv("LABCAT_DATA_DIR", raising=False)
    monkeypatch.setattr(web.sys, "platform", platform)
    monkeypatch.setenv(variable, str(tmp_path))
    assert web.default_workspace_path() == tmp_path / suffix / "workspace.sqlite3"
