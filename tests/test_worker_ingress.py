"""The Goose worker may use its job callback, never the general
workspace API."""

import socket

from fastapi.testclient import TestClient

from labcat.web import _worker_peer_blocked, create_app


def test_worker_identity_uses_socket_peer_not_forged_headers(tmp_path, monkeypatch):
    app = create_app(workspace_path=tmp_path / "workspace.sqlite3")
    monkeypatch.setenv("LABCAT_GOOSE_REMOTE", "1")
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("172.19.0.3", 8765))
        ],
    )
    with TestClient(
        app, base_url="http://127.0.0.1", client=("172.19.0.3", 12345)
    ) as client:
        headers = {
            "X-Forwarded-For": "127.0.0.1",
            "Forwarded": "for=127.0.0.1",
            "Host": "127.0.0.1",
        }
        for path in ("/api/session", "/api/connections", "/api/projects", "/"):
            response = client.get(path, headers=headers)
            assert response.status_code == 403
            assert "csrf_token" not in response.text
    with TestClient(
        app, base_url="http://127.0.0.1", client=("172.19.0.1", 12345)
    ) as client:
        assert client.get("/api/session").status_code == 200


def test_worker_replacement_and_dns_failure_fail_closed(monkeypatch):
    monkeypatch.setenv("LABCAT_GOOSE_REMOTE", "1")
    addresses = iter(("172.19.0.3", "172.19.0.4"))
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", (next(addresses), 8765))
        ],
    )
    assert _worker_peer_blocked("172.19.0.3")
    assert _worker_peer_blocked("172.19.0.4")

    def unavailable(*args, **kwargs):
        raise OSError("DNS unavailable")

    monkeypatch.setattr(socket, "getaddrinfo", unavailable)
    assert _worker_peer_blocked("172.19.0.1")
    assert _worker_peer_blocked(None)
    assert not _worker_peer_blocked("127.0.0.1")
