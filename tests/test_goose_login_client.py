"""Offline browser-login transport tests; all workers/accounts are
synthetic."""

import base64
import io
import json
from email.message import Message
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock
from urllib.parse import urlencode

import pytest
from fastapi.testclient import TestClient

from labcat import goose_login_client as client
from labcat import goose_worker
from labcat import goose_worker_client as transport
from labcat.agent_connections import AgentConnections
from labcat.chatgpt_auth import ChatGPTAuthError, ChatGPTSetupError
from labcat.connections import DEFAULT_PROFILE
from labcat.web import create_app

FLOW = "a" * 32
CHANNEL = "b" * 64
CALLBACK = "/auth/callback?code=SYNTHETIC_CODE&state=" + "s" * 32


def flow(**changes):
    return {
        "flow_id": FLOW,
        "status": "pending",
        "method": "browser",
        "user_code": None,
        "verification_url": "https://auth.openai.com/oauth/authorize?"
        + urlencode(
            {
                "client_id": "app_EMoamEEZ73f0CkXaXp7hrann",
                "redirect_uri": "http://localhost:1455/auth/callback",
                "response_type": "code",
                "code_challenge_method": "S256",
                "state": "s" * 32,
                "code_challenge": "c" * 43,
            }
        ),
        **changes,
    }


def auth_document():
    def token(payload):
        encoded = (
            base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
        )
        return "eyJhbGciOiJIUzI1NiJ9." + encoded + ".c2lnbmF0dXJl"

    return {
        "auth_mode": "chatgpt",
        "OPENAI_API_KEY": None,
        "tokens": {
            "access_token": token({"exp": 2_000_000_000}),
            "refresh_token": "SYNTHETIC_REFRESH_TOKEN",
            "id_token": token({"test": "synthetic"}),
            "account_id": "synthetic-account",
        },
        "last_refresh": "2026-09-10T00:00:00Z",
    }


@pytest.fixture
def broker(monkeypatch):
    metadata = Mock()
    monkeypatch.setattr(client, "ChatGPTAuthBroker", lambda: metadata)
    result = client.WorkerChatGPTAuthBroker()
    return result, metadata


@pytest.mark.parametrize(
    "remote,enabled,expected",
    [
        ("1", "1", True),
        ("0", "1", False),
        ("1", "0", False),
        ("true", "1", False),
        ("1", "true", False),
    ],
)
def test_browser_mode_requires_both_explicit_deployment_flags(
    monkeypatch, remote, enabled, expected
):
    monkeypatch.setenv("LABCAT_GOOSE_REMOTE", remote)
    monkeypatch.setenv("LABCAT_GOOSE_BROWSER_AUTH", enabled)
    assert client.browser_login_enabled() is expected


@pytest.mark.parametrize(
    "change",
    [
        {"flow_id": "../credentials"},
        {"flow_id": []},
        {"flow_id": "x" * 33},
        {"method": "device"},
        {"status": "invented"},
        {"status": []},
        {"user_code": "PRIVATE_CODE"},
        {"verification_url": "https://private.invalid"},
        {"verification_url": "https://auth.openai.com/oauth/token"},
        {"credentials": {"access_token": "PRIVATE_TOKEN"}},
    ],
)
def test_flow_rejects_unvalidated_fields_without_reflecting_them(change):
    with pytest.raises(ChatGPTAuthError) as error:
        client._flow(flow(**change))
    assert "PRIVATE" not in str(error.value)


@pytest.mark.parametrize(
    "status", ["pending", "complete", "cancelled", "expired", "error", "consumed"]
)
def test_flow_accepts_only_bounded_browser_metadata(status):
    value = flow(status=status)
    assert client._flow(value) == value
    with pytest.raises(ChatGPTAuthError):
        client._flow(value, "c" * 32)


def test_start_checks_callback_port_before_worker_and_tracks_flow(monkeypatch, broker):
    instance, metadata = broker
    request = Mock(return_value=flow())
    monkeypatch.setattr(client, "_worker_request", request)
    monkeypatch.setenv("LABCAT_OAUTH_CALLBACK_PORT", "9999")
    with pytest.raises(ChatGPTSetupError, match="local port 1455") as error:
        instance.start()
    assert error.value.code == "chatgpt_callback_unavailable"
    assert "LABCAT_OAUTH_CALLBACK_PORT=1455" in str(error.value)
    assert "Other providers remain usable" in str(error.value)
    request.assert_not_called()
    monkeypatch.setenv("LABCAT_OAUTH_CALLBACK_PORT", "1455")
    assert instance.start() == flow()
    assert instance.flow_id == FLOW
    request.assert_called_once_with("/auth/start", {})
    metadata.metadata.assert_not_called()


def test_callback_port_failure_is_a_safe_setup_response_not_a_credential_error(
    monkeypatch, tmp_path, broker
):
    instance, _ = broker
    monkeypatch.setattr(client, "start_callback_relay", lambda: None)
    monkeypatch.setenv("LABCAT_OAUTH_CALLBACK_PORT", "PRIVATE_UNSUPPORTED_VALUE")
    request = Mock()
    monkeypatch.setattr(client, "_worker_request", request)
    app = create_app(workspace_path=tmp_path / "workspace.sqlite3")
    manager = app.state.connections
    account = manager.save_account(
        {
            "label": "Synthetic ChatGPT account",
            "profile": {**DEFAULT_PROFILE, "provider": "chatgpt", "model": ""},
            "secret_storage": "session",
        }
    )["active_account_id"]
    manager.agent._auth = instance
    with TestClient(app, base_url="http://localhost") as api:
        token = api.get("/api/session").json()["csrf_token"]
        response = api.post(
            f"/api/connections/accounts/{account}/login",
            json={"secret_storage": "session"},
            headers={"X-CSRF-Token": token},
        )
        assert response.status_code == 503
        assert response.json() == {"detail": {"code": "chatgpt_callback_unavailable"}}
        assert "PRIVATE_UNSUPPORTED_VALUE" not in response.text
        assert not manager.agent._flows
        assert manager.status()["accounts"][0]["credential_state"] == "missing"
    request.assert_not_called()


@pytest.mark.parametrize("method", ["poll", "cancel"])
def test_flow_replies_cannot_switch_login_identity(monkeypatch, broker, method):
    instance, _ = broker
    request = Mock(return_value=flow(flow_id="c" * 32))
    monkeypatch.setattr(client, "_worker_request", request)
    with pytest.raises(ChatGPTAuthError):
        getattr(instance, method)(FLOW)
    request.assert_called_once_with("/auth/" + method, {"flow_id": FLOW})


def test_credentials_are_internal_validated_once_and_never_logged(
    monkeypatch, broker, capsys
):
    instance, metadata = broker
    document = auth_document()
    request = Mock(return_value={"credentials": document})
    monkeypatch.setattr(client, "_worker_request", request)
    assert instance.take_credentials(FLOW) == document
    request.assert_called_once_with("/auth/take", {"flow_id": FLOW})
    metadata.metadata.assert_not_called()
    for invalid in (
        {"credentials": document, "extra": "PRIVATE_TOKEN"},
        {"credentials": {"tokens": "PRIVATE_TOKEN"}},
    ):
        request.return_value = invalid
        with pytest.raises(ChatGPTAuthError) as error:
            instance.take_credentials(FLOW)
        assert "PRIVATE" not in str(error.value)
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize(
    "reply", [None, [], {"status": "failed", "error": "PRIVATE_TOKEN"}]
)
def test_worker_failures_are_fixed_and_never_retried(monkeypatch, reply):
    request = Mock(return_value=reply)
    monkeypatch.setattr(client, "_worker_request", request)
    with pytest.raises(ChatGPTAuthError) as error:
        client._request("/auth/start", {})
    assert "PRIVATE" not in str(error.value)
    request.assert_called_once()


def test_broker_close_still_closes_metadata_reader_when_worker_unavailable(
    monkeypatch, broker
):
    instance, metadata = broker
    instance.flow_id = FLOW
    request = Mock(side_effect=OSError("PRIVATE_TOKEN"))
    monkeypatch.setattr(client, "_worker_request", request)
    instance.close()
    request.assert_called_once_with("/auth/cancel", {"flow_id": FLOW})
    metadata.close.assert_called_once()


def callback_handler(path=CALLBACK, hosts=("localhost:1455",)):
    handler = client.CallbackHandler.__new__(client.CallbackHandler)
    handler.path = path
    handler.headers = Message()
    for host in hosts:
        handler.headers["Host"] = host
    handler.wfile = io.BytesIO()
    handler.response_headers = {}
    handler.send_response = lambda status: setattr(handler, "response_status", status)
    handler.send_header = lambda key, value: handler.response_headers.update(
        {key: value}
    )
    handler.end_headers = lambda: None
    return handler


@pytest.mark.parametrize("host", ["localhost:1455", "127.0.0.1:1455"])
@pytest.mark.parametrize("status", [200, 400, 403, 409, 502, 503])
def test_callback_forwards_to_fixed_private_rpc_and_returns_only_static_html(
    monkeypatch, capsys, host, status
):
    request = Mock(return_value={"callback_status": status, "html": "PRIVATE_TOKEN"})
    monkeypatch.setattr(client, "_request", request)
    handler = callback_handler(hosts=(host,))
    handler.do_GET()
    handler.log_message("PRIVATE_CODE")
    request.assert_called_once_with("/auth/callback", {"path": CALLBACK})
    assert handler.response_status == status
    raw = handler.wfile.getvalue()
    assert b"PRIVATE" not in raw and b"SYNTHETIC_CODE" not in raw
    assert b"connected successfully" not in raw
    assert handler.response_headers["Cache-Control"] == "no-store"
    assert handler.response_headers["Referrer-Policy"] == "no-referrer"
    assert "default-src 'none'" in handler.response_headers["Content-Security-Policy"]
    assert int(handler.response_headers["Content-Length"]) == len(raw)
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize(
    "path",
    [
        "/",
        "/auth/callback/",
        "/auth/%63allback",
        "/auth/callback#x",
        "https://private.invalid/auth/callback",
        "//private.invalid/auth/callback",
        CALLBACK + "\n",
        "\x00" + CALLBACK,
        CALLBACK + "é",
        "/auth/callback?" + "x" * 8192,
    ],
)
def test_invalid_callback_paths_are_rejected_before_private_rpc(monkeypatch, path):
    request = Mock()
    monkeypatch.setattr(client, "_request", request)
    handler = callback_handler(path)
    handler.do_GET()
    assert handler.response_status == 400
    request.assert_not_called()


@pytest.mark.parametrize(
    "hosts",
    [
        (),
        ("private.invalid",),
        ("localhost:1456",),
        ("localhost:1455", "localhost:1455"),
    ],
)
def test_callback_requires_single_expected_public_loopback_host(monkeypatch, hosts):
    request = Mock()
    monkeypatch.setattr(client, "_request", request)
    handler = callback_handler(hosts=hosts)
    handler.do_GET()
    assert handler.response_status == 403
    request.assert_not_called()


def test_callback_transport_error_is_generic_and_disconnected_browser_is_harmless(
    monkeypatch,
):
    monkeypatch.setattr(
        client, "_request", Mock(side_effect=RuntimeError("PRIVATE_TOKEN"))
    )
    handler = callback_handler()
    handler.do_GET()
    assert handler.response_status == 503
    assert b"PRIVATE" not in handler.wfile.getvalue()
    handler.wfile = Mock()
    handler.wfile.write.side_effect = BrokenPipeError
    handler.do_GET()


def test_callback_listener_only_starts_for_enabled_deployment(monkeypatch):
    server = Mock()
    factory = Mock(return_value=server)
    thread = Mock()
    monkeypatch.setattr(client, "ThreadingHTTPServer", factory)
    monkeypatch.setattr(client.threading, "Thread", thread)
    monkeypatch.setattr(client, "browser_login_enabled", lambda: False)
    assert client.start_callback_relay() is None
    factory.assert_not_called()
    monkeypatch.setattr(client, "browser_login_enabled", lambda: True)
    assert client.start_callback_relay() is server
    factory.assert_called_once_with(("0.0.0.0", 1456), client.CallbackHandler)
    assert server.daemon_threads is True
    thread.assert_called_once_with(target=server.serve_forever, daemon=True)
    thread.return_value.start.assert_called_once()


@pytest.mark.parametrize("enabled", [False, True])
def test_agent_selects_browser_broker_only_when_deployment_enables_it(
    monkeypatch, tmp_path, enabled
):
    from labcat import chatgpt_auth

    monkeypatch.setattr(transport, "initialize_channel", lambda: None)
    monkeypatch.setattr(client, "browser_login_enabled", lambda: enabled)
    browser = Mock(return_value=object())
    device = Mock(return_value=object())
    monkeypatch.setattr(client, "WorkerChatGPTAuthBroker", browser)
    monkeypatch.setattr(chatgpt_auth, "ChatGPTAuthBroker", device)
    agent = AgentConnections(SimpleNamespace(), tmp_path / "workspace.sqlite3")
    assert agent._broker() is (browser.return_value if enabled else device.return_value)
    assert agent._broker() is agent._auth
    assert browser.call_count == int(enabled)
    assert device.call_count == int(not enabled)


@pytest.mark.parametrize("fails", [False, True])
def test_app_shutdown_closes_callback_listener_even_when_broker_cleanup_fails(
    monkeypatch, tmp_path, fails
):
    relay = Mock()
    monkeypatch.setattr(client, "start_callback_relay", lambda: relay)
    app = create_app(workspace_path=tmp_path / "workspace.sqlite3")
    app.state.connections.agent.close = Mock(
        side_effect=ChatGPTAuthError("test cleanup failure") if fails else None
    )
    if fails:
        with (
            pytest.raises(ChatGPTAuthError),
            TestClient(app, base_url="http://localhost"),
        ):
            pass
    else:
        with TestClient(app, base_url="http://localhost"):
            pass
    relay.shutdown.assert_called_once()
    relay.server_close.assert_called_once()


@pytest.fixture
def worker_handler(monkeypatch):
    from labcat import goose_browser_auth

    broker = Mock()
    broker.start.return_value = flow()
    broker.poll.return_value = flow()
    broker.cancel.return_value = flow(status="cancelled")
    broker.take_credentials.return_value = auth_document()
    broker.relay_callback.return_value = (200, b"PRIVATE_PROVIDER_HTML")
    monkeypatch.setattr(goose_browser_auth, "GooseBrowserAuthBroker", lambda: broker)
    captured = {}

    def server(address, handler):
        captured["handler"] = handler
        return SimpleNamespace()

    monkeypatch.setattr(goose_worker, "ThreadingHTTPServer", server)
    monkeypatch.setattr(goose_worker, "_key", lambda: CHANNEL)
    goose_worker.make_server()

    def request(path, body, *, extra_headers=(), authenticated=True, raw=None):
        handler = captured["handler"].__new__(captured["handler"])
        raw = raw if raw is not None else json.dumps(body).encode()
        handler.path = path
        handler.headers = Message()
        if authenticated:
            handler.headers["Authorization"] = "Bearer " + CHANNEL
        handler.headers["Content-Length"] = str(len(raw))
        for name, value in extra_headers:
            handler.headers[name] = value
        handler.rfile = io.BytesIO(raw)
        handler.wfile = io.BytesIO()
        handler.send_response = lambda status: setattr(
            handler, "response_status", status
        )
        handler.send_header = lambda *_: None
        handler.end_headers = lambda: None
        handler.do_POST()
        return handler.response_status, json.loads(handler.wfile.getvalue())

    return broker, request


@pytest.mark.parametrize(
    "path,body,operation",
    [
        ("/auth/start", {}, "start"),
        ("/auth/poll", {"flow_id": FLOW}, "poll"),
        ("/auth/cancel", {"flow_id": FLOW}, "cancel"),
        ("/auth/take", {"flow_id": FLOW}, "take_credentials"),
        ("/auth/callback", {"path": CALLBACK}, "relay_callback"),
    ],
)
def test_private_auth_rpc_dispatch_is_explicit_and_callback_html_is_discarded(
    worker_handler, path, body, operation
):
    broker, request = worker_handler
    status, reply = request(path, body)
    assert status == 200
    getattr(broker, operation).assert_called_once()
    assert "PRIVATE_PROVIDER_HTML" not in json.dumps(reply)
    if operation != "take_credentials":
        assert "SYNTHETIC_REFRESH_TOKEN" not in json.dumps(reply)


@pytest.mark.parametrize(
    "headers,authenticated",
    [
        ((), False),
        ((("Authorization", "wrong"),), False),
        ((("Origin", "http://localhost"),), True),
        ((("Origin", ""),), True),
        ((("Authorization", "Bearer " + CHANNEL),), True),
    ],
)
def test_private_auth_rpc_requires_one_private_authorization_and_no_browser_origin(
    worker_handler, headers, authenticated
):
    broker, request = worker_handler
    assert (
        request(
            "/auth/take",
            {"flow_id": FLOW},
            extra_headers=headers,
            authenticated=authenticated,
        )[0]
        == 403
    )
    assert broker.mock_calls == []


@pytest.mark.parametrize(
    "path,body",
    [
        ("/auth/start", {"credentials": "PRIVATE_TOKEN"}),
        ("/auth/start", []),
        ("/auth/poll", {"flow_id": []}),
        ("/auth/poll", {"flow_id": "../token"}),
        ("/auth/take", {"flow_id": "x" * 200}),
        ("/auth/cancel", {"flow_id": FLOW, "extra": True}),
        ("/auth/callback", {"url": "http://private.invalid"}),
    ],
)
def test_private_auth_rpc_rejects_invalid_body_before_broker(
    worker_handler, path, body
):
    broker, request = worker_handler
    assert request(path, body) == (400, {"status": "failed"})
    assert broker.mock_calls == []


def test_private_auth_rpc_rejects_duplicate_json_keys_and_oversized_requests(
    worker_handler,
):
    broker, request = worker_handler
    for raw in (b'{"flow_id":"a","flow_id":"b"}', b" " * 12001):
        assert request("/auth/take", {}, raw=raw)[0] == 400
    assert (
        request("/auth/start", {}, extra_headers=(("Transfer-Encoding", "chunked"),))[0]
        == 400
    )
    assert broker.mock_calls == []


@pytest.mark.parametrize(
    "path",
    ["/auth/start", "/auth/poll", "/auth/cancel", "/auth/take", "/auth/callback"],
)
def test_auth_transport_uses_only_fixed_private_endpoint_and_channel_key(
    monkeypatch, path
):
    monkeypatch.setenv("LABCAT_GOOSE_REMOTE", "1")
    monkeypatch.setattr(transport, "_channel_key", lambda: CHANNEL)
    response = MagicMock()
    response.__enter__.return_value = response
    response.status = 200
    response.read.return_value = b'{"status":"pending"}'
    opener = Mock()
    opener.open.return_value = response
    factory = Mock(return_value=opener)
    monkeypatch.setattr(transport, "build_opener", factory)
    assert transport._worker_request(path, {}) == {"status": "pending"}
    request = opener.open.call_args.args[0]
    assert request.full_url == "http://goose-worker:8765" + path
    assert request.method == "POST"
    assert request.headers["Authorization"] == "Bearer " + CHANNEL
    assert factory.call_args.args[0].proxies == {}
    response.read.assert_called_once_with(transport.MAX_WIRE_BYTES + 1)
