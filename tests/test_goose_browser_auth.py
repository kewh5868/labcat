"""Offline OAuth fixtures only: no provider, browser, credential or
model calls."""

import base64
import copy
import json
import os
import shlex
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlencode

import pytest

from labcat import goose_browser_auth as module
from labcat.chatgpt_auth import (
    ChatGPTAuthError,
    ChatGPTSetupError,
    goose_token_cache,
)


def token(value):
    payload = base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")
    return "eyJhbGciOiJIUzI1NiJ9." + payload + ".c2lnbmF0dXJl"


@pytest.fixture
def auth():
    return {
        "auth_mode": "chatgpt",
        "OPENAI_API_KEY": None,
        "tokens": {
            "access_token": token(
                {
                    "exp": 2_000_000_000,
                    "https://api.openai.com/auth": {
                        "chatgpt_account_id": "test-account"
                    },
                }
            ),
            "refresh_token": "offline-refresh-token-not-a-credential",
            "id_token": token(
                {"https://api.openai.com/auth": {"chatgpt_account_id": "test-account"}}
            ),
            "account_id": "test-account",
        },
        "last_refresh": "2026-09-09T00:00:00Z",
    }


@pytest.fixture
def url():
    return "https://auth.openai.com/oauth/authorize?" + urlencode(
        {
            "client_id": module.CLIENT_ID,
            "redirect_uri": module.REDIRECT,
            "response_type": "code",
            "code_challenge_method": "S256",
            "state": "offline-state-1234567890",
            "code_challenge": "offline-challenge-1234567890",
            "scope": "openid email profile offline_access",
        }
    )


class FakeSession:
    def __init__(self, url, auth):
        self.url = url
        self.auth = copy.deepcopy(auth)
        self.status = "pending"
        self.closed = False

    def start(self):
        return self.url

    def poll(self):
        return self.status

    def credentials(self):
        return self.auth

    def close(self):
        self.closed = True
        self.auth = None


@pytest.fixture
def broker(tmp_path, url, auth):
    sessions = []
    clock = [100]

    def factory(root):
        assert root == tmp_path
        session = FakeSession(url, auth)
        sessions.append(session)
        return session

    result = module.GooseBrowserAuthBroker(
        tmp_path, session_factory=factory, clock=lambda: clock[0]
    )
    yield result, sessions, clock
    result.close()


def test_flow_is_public_only_until_one_private_credential_handoff(broker, url, auth):
    value, sessions, _ = broker
    flow = value.start()
    assert flow == {
        "flow_id": flow["flow_id"],
        "status": "pending",
        "method": "browser",
        "verification_url": url,
        "user_code": None,
    }
    with pytest.raises(ChatGPTAuthError):
        value.take_credentials(flow["flow_id"])
    sessions[-1].status = "complete"
    public = value.poll(flow["flow_id"])
    assert public["status"] == "complete"
    assert sessions[-1].closed
    assert "token" not in json.dumps(public)
    assert value.take_credentials(flow["flow_id"]) == auth
    assert value.poll(flow["flow_id"])["status"] == "consumed"
    with pytest.raises(ChatGPTAuthError):
        value.take_credentials(flow["flow_id"])


@pytest.mark.parametrize("complete", [False, True])
def test_five_minute_expiry_removes_session_and_completed_credentials(broker, complete):
    value, sessions, clock = broker
    flow = value.start()["flow_id"]
    if complete:
        sessions[-1].status = "complete"
        assert value.poll(flow)["status"] == "complete"
    clock[0] += module.FLOW_TTL_SECONDS
    assert value.poll(flow)["status"] == "expired"
    assert sessions[-1].closed
    assert value._flow["credentials"] is None
    with pytest.raises(ChatGPTAuthError):
        value.take_credentials(flow)


def test_cancel_restart_and_stale_timer_cannot_complete_or_consume_another_flow(broker):
    value, sessions, _ = broker
    old = value.start()["flow_id"]
    current = value.start()["flow_id"]
    assert old != current and sessions[0].closed
    value._expire(old)
    assert value.poll(current)["status"] == "pending"
    with pytest.raises(ChatGPTAuthError):
        value.poll(old)
    assert value.cancel(current)["status"] == "cancelled"
    sessions[-1].status = "complete"  # late provider completion after cancellation
    assert value.poll(current)["status"] == "cancelled"
    with pytest.raises(ChatGPTAuthError):
        value.take_credentials(current)


def test_cancel_also_discards_completed_but_unconsumed_credentials(broker):
    value, sessions, _ = broker
    flow = value.start()["flow_id"]
    sessions[-1].status = "complete"
    assert value.poll(flow)["status"] == "complete"
    assert value.cancel(flow)["status"] == "cancelled"
    assert value._flow["credentials"] is None


def test_errors_are_fixed_and_startup_always_closes_session(tmp_path, url, auth):
    session = FakeSession("https://attacker.invalid/secret-credential", auth)
    value = module.GooseBrowserAuthBroker(tmp_path, session_factory=lambda _: session)
    with pytest.raises(ChatGPTAuthError, match="Goose could not complete") as raised:
        value.start()
    assert "secret-credential" not in str(raised.value)
    assert session.closed

    def unavailable(_):
        raise ChatGPTSetupError("chatgpt_storage_unavailable")

    value = module.GooseBrowserAuthBroker(tmp_path, session_factory=unavailable)
    with pytest.raises(ChatGPTSetupError) as raised:
        value.start()
    assert raised.value.code == "chatgpt_storage_unavailable"


@pytest.mark.parametrize(
    "change",
    [
        lambda url: url.replace("auth.openai.com", "auth.openai.com.attacker.invalid"),
        lambda url: url.replace("https://", "http://"),
        lambda url: url.replace("auth.openai.com", "user:secret@auth.openai.com"),
        lambda url: url + "#fragment",
        lambda url: url + "&state=duplicate",
        lambda url: url.replace("S256", "plain"),
        lambda url: url.replace("localhost%3A1455", "attacker.invalid%3A1455"),
        lambda url: url + "\n",
        lambda url: url + "&bad",
    ],
)
def test_authorization_urls_reject_redirects_duplicates_and_unsafe_input(url, change):
    assert module.validate_authorize_url(url) == url
    with pytest.raises(ChatGPTAuthError):
        module.validate_authorize_url(change(url))


def test_only_active_exact_state_callback_is_relayed_and_upstream_text_is_discarded(
    broker, monkeypatch
):
    value, _, _ = broker
    requests = []

    class Response:
        status = 200

        def read(self, limit):
            assert limit == 64_001
            return b"<script>private-oauth-code; malicious-reflection</script>"

    class Connection:
        def __init__(self, host, port, timeout):
            assert (host, port, timeout) == ("127.0.0.1", 1455, 10)

        def request(self, method, path, headers):
            requests.append((method, path, headers))

        def getresponse(self):
            return Response()

        def close(self):
            pass

    monkeypatch.setattr(module.http.client, "HTTPConnection", Connection)
    path = "/auth/callback?state=offline-state-1234567890&code=offline-code"
    assert value.relay_callback(path)[0] == 409
    flow = value.start()["flow_id"]
    for bad in (
        "https://attacker.invalid" + path,
        "//127.0.0.1:9999" + path,
        path.replace("/auth/callback", "/auth/callback/"),
        path + "#secret",
        path + "\r\nHost:attacker.invalid",
        path.replace("offline-state-1234567890", "stale-state-12345678900"),
        path + "&code=duplicate",
        path + "&next=http://attacker.invalid",
        path + "&error=access_denied",
        path.replace("offline-code", "%0aInjected"),
        path.replace("offline-code", ""),
    ):
        assert value.relay_callback(bad)[0] == 400
    assert requests == []
    status, body = value.relay_callback(path)
    assert status == 200
    assert "private" not in body.decode() and "script" not in body.decode()
    assert requests == [("GET", path, {"Host": "localhost:1455"})]
    assert value.poll(flow)["status"] == "pending", "callback receipt is not success"
    value.cancel(flow)
    assert value.relay_callback(path)[0] == 409
    assert len(requests) == 1


def private_root(tmp_path):
    root = Path(tempfile.mkdtemp(prefix="labcat-chatgpt-", dir=tmp_path))
    root.chmod(0o700)
    return root


def write_cache(root, cache):
    directory = root / "config/chatgpt_codex"
    directory.mkdir(parents=True, mode=0o700)
    (root / "config").chmod(0o700)
    directory.chmod(0o700)
    path = directory / "tokens.json"
    path.write_text(json.dumps(cache))
    path.chmod(0o600)
    return path


@pytest.mark.skipif(os.name != "posix", reason="Private POSIX worker filesystem")
def test_provider_cache_requires_owned_private_files_valid_identity_and_expiry(
    tmp_path, auth, monkeypatch
):
    root = private_root(tmp_path)
    cache = goose_token_cache(auth)
    path = write_cache(root, cache)
    path.write_text(json.dumps({**cache, "expires_at": "2033-05-18T03:33:25.123456Z"}))
    result = module._cache_credentials(root)
    assert result["tokens"] == auth["tokens"]
    assert datetime.fromisoformat(result["last_refresh"]).tzinfo == UTC
    path.chmod(0o644)
    with pytest.raises(ChatGPTAuthError):
        module._cache_credentials(root)
    path.chmod(0o600)
    original = module.os.getuid()
    with monkeypatch.context() as patch:
        patch.setattr(module.os, "getuid", lambda: original + 1)
        with pytest.raises(ChatGPTAuthError):
            module._cache_credentials(root)
    for update in (
        {"account_id": "another-account"},
        {"expires_at": "2000-01-01T00:00:00Z"},
        {"expires_at": "2033-05-18T03:33:20"},
        {"id_token": None},
        {"extra_secret": "not-allowed"},
    ):
        path.write_text(json.dumps({**cache, **update}))
        with pytest.raises(ChatGPTAuthError):
            module._cache_credentials(root)
    path.write_text('{"access_token":"one","access_token":"two"}')
    with pytest.raises(ChatGPTAuthError):
        module._cache_credentials(root)
    path.unlink()
    target = root / "outside-tokens"
    target.write_text(json.dumps(cache))
    target.chmod(0o600)
    path.symlink_to(target)
    with pytest.raises(ChatGPTAuthError):
        module._cache_credentials(root)
    assert target.read_text() == json.dumps(cache)


@pytest.mark.skipif(os.name != "posix", reason="Private POSIX worker filesystem")
def test_browser_capture_is_atomic_private_memory_only_and_never_prints(
    tmp_path, url, monkeypatch, capsys
):
    root = private_root(tmp_path)
    monkeypatch.setenv(module.FLOW_DIRECTORY_ENV, str(root))
    monkeypatch.setattr(module, "_is_tmpfs", lambda _: False)
    with pytest.raises(ChatGPTAuthError):
        module._capture_browser(url)
    assert not (root / "browser-url").exists()
    monkeypatch.setattr(module, "_is_tmpfs", lambda _: True)
    module._capture_browser(url)
    assert (root / "browser-url").read_text() == url
    assert (root / "browser-url").stat().st_mode & 0o777 == 0o600
    module._capture_browser(url)
    with pytest.raises(ChatGPTAuthError):
        module._capture_browser(url.replace("offline-state", "another-state"))
    assert list(root.iterdir()) == [root / "browser-url"]
    monkeypatch.setattr(sys, "argv", ["helper", "capture", "https://secret.invalid"])
    assert module.main() == 1
    assert capsys.readouterr() == ("", "")


@pytest.mark.skipif(os.name != "posix", reason="Goose worker requires a POSIX PTY")
def test_actual_pty_answers_only_two_menus_stops_before_inference_and_cleans_files(
    tmp_path, auth, url, monkeypatch
):
    roots = []
    calls = []
    writes = []

    def directory(root):
        result = private_root(root)
        roots.append(result)
        return result

    class Binary:
        def is_file(self):
            return True

        def __str__(self):
            return "/usr/local/bin/goose"

    script = "\n".join(
        [
            "import sys, time, os, json",
            "from pathlib import Path",
            "print('What would you like to configure?', flush=True)",
            "assert sys.stdin.readline() == '\\n'",
            "print('Which model provider should we use?', flush=True)",
            "assert sys.stdin.readline() == '\\n'",
            "root = Path(os.environ['GOOSE_PATH_ROOT'])",
            f"(root / 'browser-url').write_text({url!r})",
            "(root / 'browser-url').chmod(0o600)",
            "time.sleep(0.2)",
            "directory = root / 'config/chatgpt_codex'",
            "directory.mkdir(mode=0o700)",
            "(directory / 'tokens.json').write_text("
            f"{json.dumps(goose_token_cache(auth))!r})",
            "(directory / 'tokens.json').chmod(0o600)",
            "print('Select a model:', flush=True)",
            "sys.stdin.readline()",
            "raise RuntimeError('Model selection must never be answered')",
        ]
    )

    def process(args, **kwargs):
        calls.append((args, kwargs))
        assert not (Path(kwargs["cwd"]) / "capture-browser").exists()
        return subprocess.Popen([sys.executable, "-I", "-c", script], **kwargs)

    original_write = os.write

    def write(descriptor, value):
        writes.append(value)
        return original_write(descriptor, value)

    monkeypatch.setattr(module, "_private_directory", directory)
    monkeypatch.setattr(module, "GOOSE_BINARY", Binary())
    monkeypatch.setattr(module.os, "write", write)
    monkeypatch.setenv("OPENAI_API_KEY", "do-not-inherit")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "do-not-inherit")
    monkeypatch.setenv("HTTPS_PROXY", "http://attacker.invalid")
    session = module._GooseConfigureSession(tmp_path, process_factory=process)
    try:
        assert session.start() == url
        deadline = time.monotonic() + 5
        while session.poll() == "pending" and time.monotonic() < deadline:
            time.sleep(0.02)
        assert session.poll() == "complete"
        assert session.credentials()["tokens"] == auth["tokens"]
        assert session.process.poll() is not None
        assert not roots[0].exists()
        assert writes == [b"\r", b"\r"]
        assert calls[0][0] == ["/usr/local/bin/goose", "configure"]
        env = calls[0][1]["env"]
        assert "OPENAI_API_KEY" not in env and "AWS_SECRET_ACCESS_KEY" not in env
        assert env["HTTPS_PROXY"] == "http://goose-egress:8780"
        assert env["NO_PROXY"] == "127.0.0.1,localhost"
        assert env["HOME"] == env["GOOSE_PATH_ROOT"] == str(roots[0])
        assert shlex.split(env["BROWSER"]) == [
            sys.executable,
            "-I",
            "-m",
            "labcat.goose_browser_auth",
            "capture",
            "%s",
        ]
        assert str(roots[0]) not in env["BROWSER"]
        assert calls[0][1]["umask"] == 0o077
    finally:
        session.close()
    with pytest.raises(ChatGPTAuthError):
        session.credentials()


def test_non_memory_root_is_rejected_and_missing_helper_preserves_safe_setup_error(
    tmp_path, monkeypatch
):
    from labcat import chatgpt_auth

    monkeypatch.setattr(chatgpt_auth, "_is_tmpfs", lambda _: False)
    with pytest.raises(ChatGPTSetupError) as raised:
        module.GooseBrowserAuthBroker(tmp_path).start()
    assert raised.value.code == "chatgpt_storage_unavailable"
    roots = []

    def directory(root):
        result = private_root(root)
        roots.append(result)
        return result

    monkeypatch.setattr(module, "_private_directory", directory)
    monkeypatch.setattr(module, "GOOSE_BINARY", tmp_path / "absent")
    with pytest.raises(ChatGPTSetupError) as raised:
        module.GooseBrowserAuthBroker(tmp_path).start()
    assert raised.value.code == "chatgpt_helper_unavailable"
    assert not roots[0].exists()


@pytest.mark.skipif(os.name != "posix", reason="Goose worker requires a POSIX PTY")
@pytest.mark.parametrize("scenario", ["cancel", "expire", "overflow", "exit"])
def test_pty_cancel_expiry_output_overflow_and_early_exit_cleanup(
    tmp_path, url, monkeypatch, scenario
):
    roots = []
    clock = [100]

    def directory(root):
        result = private_root(root)
        roots.append(result)
        return result

    script = (
        "import os, time\nfrom pathlib import Path\n"
        "root = Path(os.environ['GOOSE_PATH_ROOT'])\n"
        f"(root / 'browser-url').write_text({url!r})\n"
        "(root / 'browser-url').chmod(0o600)\n"
        "time.sleep(0.2)\n"
        + (
            "print('x' * 260000, flush=True)\ntime.sleep(10)\n"
            if scenario == "overflow"
            else "raise SystemExit(0)\n" if scenario == "exit" else "time.sleep(10)\n"
        )
    )
    monkeypatch.setattr(module, "_private_directory", directory)
    monkeypatch.setattr(module, "GOOSE_BINARY", Path(sys.executable))
    session = module._GooseConfigureSession(
        tmp_path,
        process_factory=lambda _, **kwargs: subprocess.Popen(
            [sys.executable, "-I", "-c", script], **kwargs
        ),
        clock=lambda: clock[0],
    )
    try:
        assert session.start() == url
        if scenario == "cancel":
            session.close()
        elif scenario == "expire":
            clock[0] += module.FLOW_TTL_SECONDS
        deadline = time.monotonic() + 3
        while session.poll() == "pending" and time.monotonic() < deadline:
            time.sleep(0.02)
        expected = {"cancel": "cancelled", "expire": "expired"}.get(scenario, "error")
        assert session.poll() == expected
        assert session.process.poll() is not None
        assert not roots[0].exists()
        with pytest.raises(ChatGPTAuthError):
            session.credentials()
    finally:
        session.close()


def test_callback_failures_never_relay_upstream_redirects_or_oversized_text(
    broker, monkeypatch
):
    value, _, _ = broker
    value.start()
    path = "/auth/callback?state=offline-state-1234567890&code=offline-code"

    class Response:
        status = 302

        def read(self, _):
            return b"secret-provider-response"

    class Connection:
        def __init__(self, *args, **kwargs):
            pass

        def request(self, *args, **kwargs):
            pass

        def getresponse(self):
            return Response()

        def close(self):
            pass

    monkeypatch.setattr(module.http.client, "HTTPConnection", Connection)
    status, body = value.relay_callback(path)
    assert status == 502 and b"secret" not in body
    Response.status = 200
    monkeypatch.setattr(Response, "read", lambda *_: b"x" * 64_001)
    assert value.relay_callback(path)[0] == 502

    def fail(*args, **kwargs):
        raise OSError("credential-looking upstream failure")

    monkeypatch.setattr(Connection, "request", fail)
    status, body = value.relay_callback(path)
    assert status == 503 and b"credential" not in body
