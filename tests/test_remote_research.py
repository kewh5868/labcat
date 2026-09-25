"""The headless client reuses the local server without importing account
secrets."""

import io
import json
from collections import deque
from unittest.mock import Mock

import pytest

from labcat.cli import main
from labcat.remote_research import (
    MAX_RESPONSE_BYTES,
    ServerResearchError,
    run_server_research,
)

TOKEN = "local-service-session-token-for-tests-only-1234"
REPORT = {
    "pi_summary": "No verified properties.",
    "technical_audit": "No evidence.",
    "sources": [],
}


class Response:
    def __init__(self, value=None, *, status=200, headers=None, raw=None):
        self.status = status
        self.headers = {"Content-Type": "application/json", **(headers or {})}
        self.stream = io.BytesIO(json.dumps(value).encode() if raw is None else raw)

    def getheader(self, name, default=None):
        return self.headers.get(name, default)

    def read(self, limit):
        return self.stream.read(limit)


@pytest.fixture
def local_service(monkeypatch):
    responses, connections, requests = deque(), [], []

    class Connection:
        def __init__(self, host, port, timeout):
            assert (host, port, timeout) == ("127.0.0.1", 8000, 180)
            self.closed = False
            connections.append(self)

        def request(self, method, path, body=None, headers=None):
            requests.append((method, path, body, headers))

        def getresponse(self):
            value = responses.popleft()
            if isinstance(value, Exception):
                raise value
            return value

        def close(self):
            self.closed = True

    monkeypatch.setattr("labcat.remote_research.http.client.HTTPConnection", Connection)
    responses.append(
        Response(
            {"csrf_token": TOKEN},
            headers={
                "Set-Cookie": (
                    f"labcat_session={TOKEN}; HttpOnly; SameSite=strict; Path=/"
                )
            },
        )
    )
    return responses, connections, requests


def test_one_stateless_run_reuses_fixed_local_session_and_selected_profile(
    local_service, monkeypatch
):
    responses, connections, requests = local_service
    monkeypatch.setenv("HTTP_PROXY", "http://private-proxy.invalid")
    monkeypatch.setenv("LABCAT_SERVER_URL", "https://untrusted.invalid")
    responses.append(Response(REPORT))
    prompt = "Research alloys; https://example.invalid/ is only prompt text"
    assert run_server_research(prompt, "profile_test") == REPORT
    assert len(requests) == 2
    assert requests[0][:3] == ("GET", "/api/session", None)
    method, path, body, headers = requests[1]
    assert (method, path) == ("POST", "/api/research")
    assert json.loads(body) == {"prompt": prompt, "ranking_profile_id": "profile_test"}
    assert headers == {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "X-CSRF-Token": TOKEN,
        "Cookie": f"labcat_session={TOKEN}",
    }
    assert all(connection.closed for connection in connections)


def test_default_server_request_infers_profile_without_changing_workspace_default(
    local_service,
):
    responses, _, requests = local_service
    responses.append(Response(REPORT))
    run_server_research("Find alloys")
    assert json.loads(requests[-1][2])["ranking_profile_id"] == "infer"


@pytest.mark.parametrize("status", [302, 403, 409, 422, 500, 502, 504])
def test_failures_never_follow_redirects_retry_or_print_server_body(
    local_service, status
):
    responses, connections, requests = local_service
    responses.append(
        Response(
            {"detail": "PRIVATE_PROVIDER_SECRET"},
            status=status,
            headers={"Location": "https://untrusted.invalid"},
        )
    )
    with pytest.raises(ServerResearchError) as failure:
        run_server_research("Find alloys")
    assert "PRIVATE_PROVIDER_SECRET" not in str(failure.value)
    assert len(requests) == 2
    assert all(connection.closed for connection in connections)


@pytest.mark.parametrize(
    "token,cookie",
    [
        (TOKEN, "missing=token"),
        (TOKEN, "labcat_session=different"),
        ("x\r\nInjected: true", f"labcat_session={TOKEN}"),
        (None, f"labcat_session={TOKEN}"),
    ],
)
def test_invalid_session_never_submits_research(local_service, token, cookie):
    responses, connections, requests = local_service
    responses.clear()
    responses.append(Response({"csrf_token": token}, headers={"Set-Cookie": cookie}))
    with pytest.raises(ServerResearchError, match="session was unavailable"):
        run_server_research("Find alloys")
    assert len(requests) == 1
    assert all(connection.closed for connection in connections)


@pytest.mark.parametrize(
    "response",
    [
        Response(REPORT, headers={"Content-Encoding": "gzip"}),
        Response(REPORT, headers={"Content-Type": "text/html"}),
        Response(REPORT, headers={"Content-Length": str(MAX_RESPONSE_BYTES + 1)}),
        Response(raw=b"x" * (MAX_RESPONSE_BYTES + 1)),
        Response(raw=b"invalid json"),
        Response([]),
        Response({"pi_summary": 1, "technical_audit": "invalid"}),
    ],
)
def test_invalid_or_unbounded_responses_are_rejected(local_service, response):
    responses, connections, requests = local_service
    responses.append(response)
    with pytest.raises(ServerResearchError):
        run_server_research("Find alloys")
    assert len(requests) == 2
    assert all(connection.closed for connection in connections)


def test_unavailable_local_service_has_actionable_redacted_error(local_service):
    responses, connections, requests = local_service
    responses.clear()
    responses.append(OSError("PRIVATE_PATH"))
    with pytest.raises(ServerResearchError, match="Start Labcat") as failure:
        run_server_research("Find alloys")
    assert "PRIVATE_PATH" not in str(failure.value)
    assert len(requests) == 1
    assert all(connection.closed for connection in connections)


@pytest.mark.parametrize(
    "prompt,profile",
    [
        ("", None),
        (" ", None),
        ("x" * 20001, None),
        ("Find alloys", "../../private"),
        ("Find alloys", "a\r\nheader"),
    ],
)
def test_invalid_inputs_fail_before_session_request(local_service, prompt, profile):
    _, _, requests = local_service
    with pytest.raises(ServerResearchError):
        run_server_research(prompt, profile)
    assert requests == []


def test_cli_server_does_not_open_vault_or_run_local_research(monkeypatch, capsys):
    client = Mock(return_value=REPORT)
    monkeypatch.setattr("labcat.remote_research.run_server_research", client)
    manager = Mock(side_effect=AssertionError("Client cannot load credentials"))
    local = Mock(side_effect=AssertionError("Client cannot run fallback research"))
    monkeypatch.setattr("labcat.research.research", local)
    monkeypatch.setattr("labcat.connections.ConnectionManager", manager)
    assert (
        main(
            [
                "research",
                "Find alloys",
                "--server",
                "--ranking-profile",
                "profile_test",
                "--format",
                "json",
            ]
        )
        == 0
    )
    client.assert_called_once_with("Find alloys", "profile_test")
    assert json.loads(capsys.readouterr().out) == REPORT
    manager.assert_not_called()
    local.assert_not_called()


def test_cli_rejects_server_and_file_credentials_together(capsys):
    with pytest.raises(SystemExit) as failure:
        main(["research", "Find alloys", "--server", "--connections", "/not-read"])
    assert failure.value.code == 2
    assert "not allowed" in capsys.readouterr().err


def test_cli_server_error_does_not_fall_back(monkeypatch, capsys):
    client = Mock(side_effect=ServerResearchError("Connect a model first."))
    monkeypatch.setattr("labcat.remote_research.run_server_research", client)
    with pytest.raises(SystemExit) as failure:
        main(["research", "Find alloys", "--server"])
    assert failure.value.code == 2
    output = capsys.readouterr()
    assert "Connect a model first" in output.err
    assert not output.out
    client.assert_called_once()
