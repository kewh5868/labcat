"""No real accounts, device codes, external requests, or inference in
this suite."""

import base64
import copy
import json
import textwrap
from pathlib import Path

import pytest

from labcat import chatgpt_auth as module
from labcat.chatgpt_auth import (
    CODEX_VERSION,
    VERIFICATION_URL,
    ChatGPTAuthBroker,
    ChatGPTAuthError,
    ChatGPTSetupError,
    goose_token_cache,
    update_from_goose_tokens,
    validate_auth_document,
)


def token(payload):
    encoded = (
        base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    )
    return "eyJhbGciOiJIUzI1NiJ9." + encoded + ".c2lnbmF0dXJl"


@pytest.fixture
def auth():
    return {
        "auth_mode": "chatgpt",
        "OPENAI_API_KEY": None,
        "tokens": {
            "access_token": token({"exp": 2_000_000_000}),
            "refresh_token": "test-refresh-token-not-a-real-secret",
            "id_token": token({"email": "private-test@example.invalid"}),
            "account_id": "test-account",
        },
        "last_refresh": "2026-09-09T00:00:00Z",
    }


class FakeSession:
    def __init__(self, auth):
        self.auth = copy.deepcopy(auth)
        self.events = []
        self.closed = False
        self.requests = []
        self.device = {
            "type": "chatgptDeviceCode",
            "loginId": "private-login-id",
            "verificationUrl": VERIFICATION_URL,
            "userCode": "TEST-0000",
        }
        self.failures = set()
        self.results = {
            "account/read": {"account": {"type": "chatgpt"}},
            "model/list": {
                "data": [
                    {
                        "id": "test-model",
                        "model": "test-model",
                        "displayName": "Test model",
                        "isDefault": True,
                        "supportedReasoningEfforts": [{"reasoningEffort": "low"}],
                    }
                ],
                "nextCursor": None,
            },
            "account/rateLimits/read": {
                "accountId": "test-account",
                "rateLimitsByLimitId": {
                    "test-bucket": {
                        "limitId": "test-bucket",
                        "limitName": "Test limits",
                        "primary": {
                            "usedPercent": 30,
                            "windowDurationMins": 300,
                            "resetsAt": 2000000000,
                        },
                        "secondary": None,
                    }
                },
            },
            "account/usage/read": {"summary": {"lifetimeTokens": 10}},
        }

    def request(self, method, params=None):
        self.requests.append((method, params))
        if method in self.failures:
            raise ChatGPTAuthError("upstream-secret-must-never-appear")
        return (
            self.device
            if method == "account/login/start"
            else copy.deepcopy(self.results[method])
        )

    def notifications(self):
        events, self.events = self.events, []
        return events

    def credentials(self):
        return validate_auth_document(self.auth)

    def close(self):
        self.closed = True


@pytest.fixture
def factory(auth):
    class Factory:
        def __init__(self):
            self.sessions = []
            self.callback = lambda _: None

        def __call__(self, binary, root, document=None):
            session = FakeSession(auth if document is None else document)
            self.callback(session)
            self.sessions.append(session)
            return session

    return Factory()


@pytest.fixture
def broker(factory, tmp_path):
    instance = ChatGPTAuthBroker(tmp_path / "codex", tmp_path, session_factory=factory)
    yield instance
    instance.close()


def complete(factory):
    factory.sessions[-1].events.append({"loginId": "private-login-id", "success": True})


def test_device_login_only_returns_safe_fields_and_consumes_once(broker, factory, auth):
    started = broker.start()
    assert set(started) == {"flow_id", "status", "verification_url", "user_code"}
    assert started["status"] == "pending"
    assert started["flow_id"] != "private-login-id"
    assert started["verification_url"] == VERIFICATION_URL
    assert factory.sessions[0].requests == [
        ("account/login/start", {"type": "chatgptDeviceCode"})
    ]
    assert broker.poll(started["flow_id"])["status"] == "pending"
    complete(factory)
    assert broker.poll(started["flow_id"])["status"] == "complete"
    assert broker.poll(started["flow_id"])["status"] == "complete"
    assert factory.sessions[0].closed
    assert broker.take_credentials(started["flow_id"]) == validate_auth_document(auth)
    with pytest.raises(ChatGPTAuthError):
        broker.take_credentials(started["flow_id"])


@pytest.mark.parametrize(
    "url",
    [
        "https://auth.openai.com.evil.invalid/codex/device",
        "http://auth.openai.com/codex/device",
        "https://auth.openai.com/codex/device?redirect=evil",
        "https://auth.openai.com:443/codex/device",
        "https://user:password@auth.openai.com/codex/device",
        "file:///private/credentials",
    ],
)
def test_signin_url_must_be_exact_provider_device_page(url, broker, factory):
    factory.callback = lambda s: s.device.update(verificationUrl=url)
    with pytest.raises(ChatGPTAuthError) as error:
        broker.start()
    assert url not in str(error.value)
    assert factory.sessions[-1].closed


@pytest.mark.parametrize(
    "code", ["ABC\nsecret", "<script>", "A" * 100, None, "https://bad"]
)
def test_untrusted_device_codes_fail_closed(code, broker, factory):
    factory.callback = lambda s: s.device.update(userCode=code)
    with pytest.raises(ChatGPTAuthError):
        broker.start()
    assert factory.sessions[-1].closed


def test_unrelated_notifications_cannot_complete_or_fail_login(broker, factory):
    flow = broker.start()["flow_id"]
    factory.sessions[-1].events = [
        {"loginId": "other-flow", "success": True},
        {"loginId": "other-flow", "success": False},
    ]
    assert broker.poll(flow)["status"] == "pending"
    factory.sessions[-1].events = [
        {
            "loginId": "private-login-id",
            "success": False,
            "error": "sensitive-upstream-error",
        }
    ]
    result = broker.poll(flow)
    assert result["status"] == "error"
    assert "sensitive-upstream-error" not in json.dumps(result)
    assert factory.sessions[-1].closed


def test_replacement_cancel_expiry_and_shutdown_discard_credentials(factory, tmp_path):
    now = [0]
    broker = ChatGPTAuthBroker(
        tmp_path / "codex", tmp_path, session_factory=factory, clock=lambda: now[0]
    )
    try:
        old = broker.start()["flow_id"]
        new = broker.start()["flow_id"]
        assert factory.sessions[0].closed
        with pytest.raises(ChatGPTAuthError):
            broker.poll(old)
        assert broker.cancel(new)["status"] == "cancelled"
        assert broker.poll(new)["status"] == "cancelled"
        assert factory.sessions[-1].closed
        expiring = broker.start()["flow_id"]
        now[0] = module.FLOW_TTL_SECONDS + 1
        assert broker.poll(expiring)["status"] == "expired"
        assert factory.sessions[-1].closed
        ready = broker.start()["flow_id"]
        complete(factory)
        assert broker.poll(ready)["status"] == "complete"
        broker.close()
        with pytest.raises(ChatGPTAuthError):
            broker.take_credentials(ready)
        assert all(s.closed for s in factory.sessions)
    finally:
        broker.close()


def test_completed_but_unclaimed_credentials_also_expire(broker, factory):
    flow = broker.start()["flow_id"]
    complete(factory)
    assert broker.poll(flow)["status"] == "complete"
    broker._expire()
    assert broker.poll(flow)["status"] == "expired"
    with pytest.raises(ChatGPTAuthError):
        broker.take_credentials(flow)


def test_malformed_auth_on_completion_returns_sanitized_error(broker, factory):
    flow = broker.start()["flow_id"]
    factory.sessions[-1].auth["OPENAI_API_KEY"] = "must-not-escape"
    complete(factory)
    assert broker.poll(flow)["status"] == "error"
    assert factory.sessions[-1].closed


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.update(auth_mode="apikey"),
        lambda d: d.update(OPENAI_API_KEY="private-token"),
        lambda d: d.update(agent_identity="secret"),
        lambda d: d["tokens"].update(account_id="../other"),
        lambda d: d["tokens"].update(access_token="not-a-jwt-token"),
        lambda d: d["tokens"].update(access_token=token({"exp": True})),
        lambda d: d["tokens"].update(access_token=token({"exp": -1})),
        lambda d: d["tokens"].update(access_token=token({"exp": 253402300800})),
        lambda d: d["tokens"].update(refresh_token="abc\ndefghij"),
        lambda d: d["tokens"].update(extra="another-secret"),
        lambda d: d.update(last_refresh="2026-09-09T12:00:00"),
    ],
)
def test_auth_document_rejects_other_identity_types_and_malformed_fields(auth, mutate):
    mutate(auth)
    with pytest.raises(ChatGPTAuthError) as error:
        validate_auth_document(auth)
    assert "private-token" not in str(error.value)
    assert "another-secret" not in str(error.value)


def test_goose_translation_and_rotated_token_round_trip(auth):
    cache = goose_token_cache(auth)
    assert set(cache) == {
        "access_token",
        "refresh_token",
        "id_token",
        "account_id",
        "expires_at",
    }
    assert cache["expires_at"] == "2033-05-18T03:33:20+00:00"
    cache["access_token"] = token({"exp": 2_000_000_001})
    cache["refresh_token"] = "rotated-not-a-real-secret"
    cache["id_token"] = None
    updated = update_from_goose_tokens(auth, cache)
    assert updated["tokens"]["refresh_token"] == cache["refresh_token"]
    assert updated["tokens"]["id_token"] == auth["tokens"]["id_token"]
    assert auth["tokens"]["refresh_token"] != cache["refresh_token"]
    cache["account_id"] = "other-account"
    with pytest.raises(ChatGPTAuthError):
        update_from_goose_tokens(auth, cache)


def test_metadata_has_real_window_semantics_and_separate_internal_credentials(
    broker, factory, auth
):
    public, refreshed = broker.metadata(auth)
    assert public["models"] == [
        {
            "id": "test-model",
            "label": "Test model",
            "default": True,
            "reasoning_efforts": ["low"],
        }
    ]
    assert public["rate_limits"] == [
        {
            "id": "test-bucket",
            "label": "Test limits",
            "primary": {
                "used_percent": 30,
                "remaining_percent": 70,
                "window_minutes": 300,
                "resets_at": 2000000000,
            },
            "secondary": None,
        }
    ]
    assert public["token_activity"]["lifetimeTokens"] == 10
    assert public["token_activity"]["peakDailyTokens"] is None
    assert not public["inference_tested"]
    assert refreshed == validate_auth_document(auth)
    assert factory.sessions[-1].closed
    rendered = json.dumps(public)
    assert auth["tokens"]["access_token"] not in rendered
    assert auth["tokens"]["refresh_token"] not in rendered
    assert "private-test@example.invalid" not in rendered
    assert all(
        method in module._ALLOWED_REQUESTS
        for method, _ in factory.sessions[-1].requests
    )


def test_partial_metadata_failures_still_return_rotated_credentials(
    broker, factory, auth
):
    def prepare(session):
        session.auth["tokens"]["refresh_token"] = "rotated-private-token"
        session.failures = {"account/rateLimits/read", "account/usage/read"}

    factory.callback = prepare
    public, updated = broker.metadata(auth)
    assert updated["tokens"]["refresh_token"] == "rotated-private-token"
    assert public["rate_limits"] is None
    assert public["token_activity"] is None
    assert len(public["notices"]) == 2
    assert "upstream-secret" not in json.dumps(public)
    assert public["models"]


def test_wrong_account_limits_and_invalid_percent_never_render(broker, factory, auth):
    def prepare(session):
        session.results["account/rateLimits/read"]["accountId"] = "other-account"

    factory.callback = prepare
    assert broker.metadata(auth)[0]["rate_limits"] is None
    for value in (True, -1, 101, float("nan"), "50"):
        with pytest.raises(ChatGPTAuthError):
            module._window({"usedPercent": value})


def test_refreshed_wrong_account_document_fails_closed(broker, factory, auth):
    factory.callback = lambda session: session.auth["tokens"].update(
        account_id="other-account"
    )
    with pytest.raises(ChatGPTAuthError):
        broker.metadata(auth)
    assert factory.sessions[-1].closed


def test_pagination_is_bounded_and_does_not_return_partial_model_catalog(
    broker, factory, auth
):
    factory.callback = lambda session: session.results["model/list"].update(
        nextCursor="never-ending"
    )
    public, _ = broker.metadata(auth)
    assert not public["models"]
    assert len([m for m, _ in factory.sessions[-1].requests if m == "model/list"]) == 8


def test_memory_backed_root_is_required_and_symlinks_are_rejected(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(module, "_is_tmpfs", lambda _: False)
    with pytest.raises(ChatGPTAuthError, match="memory-backed"):
        module._private_directory(tmp_path)
    monkeypatch.setattr(module, "_is_tmpfs", lambda _: True)
    link = tmp_path / "alias"
    link.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ChatGPTSetupError) as result:
        module._private_directory(link)
    assert result.value.code == "chatgpt_storage_unavailable"


def test_non_container_login_reports_setup_failure_without_starting_helper(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(module, "_is_tmpfs", lambda _: False)
    monkeypatch.setattr(
        module.subprocess,
        "Popen",
        lambda *args, **kwargs: pytest.fail("Helper must not start on disk storage"),
    )
    broker = ChatGPTAuthBroker(tmp_path / "codex", tmp_path)
    with pytest.raises(ChatGPTSetupError) as result:
        broker.start()
    assert result.value.code == "chatgpt_storage_unavailable"
    assert broker._flow is None
    assert not list(tmp_path.glob("labcat-chatgpt-*"))


@pytest.fixture
def fake_binary(tmp_path, auth, monkeypatch):
    """A real local subprocess implementing only a fake JSON-RPC
    peer."""
    monkeypatch.setattr(module, "_is_tmpfs", lambda _: True)
    binary = tmp_path / "fake-codex"
    record = tmp_path / "protocol-record.jsonl"
    script = """
        import json, os, sys
        from pathlib import Path
        if sys.argv[1:] == ["--version"]:
            print("codex-cli " + VERSION)
            raise SystemExit
        assert sys.argv[1:] == ["app-server", "--listen", "stdio://"]
        home = Path(os.environ["CODEX_HOME"])
        assert home == Path.cwd() and home == Path(os.environ["HOME"])
        assert "OPENAI_API_KEY" not in os.environ
        assert "HTTPS_PROXY" not in os.environ
        assert "AWS_SECRET_ACCESS_KEY" not in os.environ
        assert "CLAUDE_CODE_OAUTH_TOKEN" not in os.environ
        assert (home.stat().st_mode & 0o777) == 0o700
        assert ((home / "config.toml").stat().st_mode & 0o777) == 0o600
        def emit(value):
            print(json.dumps(value), flush=True)
        for line in sys.stdin:
            request = json.loads(line)
            with Path(RECORD).open("a") as log:
                log.write(json.dumps(request) + "\\n")
            if "error" in request:
                continue
            method = request["method"]
            if method == "initialized":
                continue
            if method == "initialize":
                emit({"id": request["id"], "result": {"userAgent": "test"}})
                emit({"id": "tool-attempt", "method": "item/tool/call",
                      "params": {"name": "shell"}})
            elif method == "account/login/start":
                assert request["params"] == {"type": "chatgptDeviceCode"}
                path = home / "auth.json"
                path.write_text(json.dumps(AUTH))
                path.chmod(0o600)
                emit({"id": request["id"], "result": {
                    "type": "chatgptDeviceCode", "loginId": "generated-login",
                    "verificationUrl": VERIFY, "userCode": "TEST-1234"}})
                emit({"method": "account/login/completed", "params": {
                    "loginId": "generated-login", "success": True}})
            else:
                emit({"id": request["id"], "error": {
                    "code": -32601, "message": "unsupported"}})
    """
    source = "#!/usr/bin/env python3\n" + "\n".join(
        (
            "VERSION = " + repr(CODEX_VERSION),
            "AUTH = " + repr(auth),
            "RECORD = " + repr(str(record)),
            "VERIFY = " + repr(VERIFICATION_URL),
            textwrap.dedent(script),
        )
    )
    # Explicit executable interpreter avoids depending on inherited PATH.
    import sys

    source = source.replace("#!/usr/bin/env python3", "#!" + sys.executable)
    binary.write_text(source)
    binary.chmod(0o700)
    return binary, record


def test_real_protocol_peer_env_isolation_tool_denial_and_temporary_cleanup(
    fake_binary, tmp_path, monkeypatch, auth
):
    import time

    binary, record = fake_binary
    for key in (
        "OPENAI_API_KEY",
        "HTTPS_PROXY",
        "AWS_SECRET_ACCESS_KEY",
        "CLAUDE_CODE_OAUTH_TOKEN",
    ):
        monkeypatch.setenv(key, "private-host-value")
    broker = ChatGPTAuthBroker(binary, tmp_path)
    try:
        flow = broker.start()["flow_id"]
        deadline = time.monotonic() + 2
        while broker.poll(flow)["status"] == "pending" and time.monotonic() < deadline:
            time.sleep(0.01)
        assert broker.poll(flow)["status"] == "complete"
        assert broker.take_credentials(flow) == validate_auth_document(auth)
        assert not list(tmp_path.glob("labcat-chatgpt-*"))
        records = [json.loads(line) for line in record.read_text().splitlines()]
        assert any(
            r.get("id") == "tool-attempt" and r.get("error", {}).get("code") == -32601
            for r in records
        )
        assert not any(
            r.get("method", "").startswith(("thread/", "turn/", "command/"))
            for r in records
        )
    finally:
        broker.close()


def test_protocol_disallows_agent_methods_even_if_called_by_client(
    fake_binary, tmp_path
):
    binary, _ = fake_binary
    session = module._CodexSession(binary, tmp_path)
    try:
        for method in (
            "turn/start",
            "thread/start",
            "command/exec",
            "mcpServer/tool/call",
        ):
            with pytest.raises(ChatGPTAuthError):
                session.request(method, {})
    finally:
        session.close()
    assert not list(tmp_path.glob("labcat-chatgpt-*"))


def test_unsupported_binary_version_never_starts_login_and_cleans_directory(
    fake_binary, tmp_path
):
    binary, record = fake_binary
    binary.write_text(binary.read_text().replace(CODEX_VERSION, "0.0.0"))
    broker = ChatGPTAuthBroker(binary, tmp_path)
    with pytest.raises(ChatGPTSetupError) as result:
        broker.start()
    assert result.value.code == "chatgpt_helper_unavailable"
    assert not record.exists()
    assert not list(tmp_path.glob("labcat-chatgpt-*"))


def test_an_old_expiry_callback_cannot_expire_a_new_flow(broker, factory):
    old = broker.start()["flow_id"]
    complete(factory)
    broker.take_credentials(old)
    new = broker.start()["flow_id"]
    broker._expire(old)
    assert broker.poll(new)["status"] == "pending"


def test_default_paths_are_explicit_application_settings(monkeypatch):
    monkeypatch.setenv("LABCAT_CODEX_BINARY", "/opt/labcat/codex")
    monkeypatch.setenv("LABCAT_AUTH_TMPDIR", "/run/labcat-auth")
    broker = ChatGPTAuthBroker()
    assert broker.binary == Path("/opt/labcat/codex")
    assert broker.temporary_root == Path("/run/labcat-auth")
    assert broker._flow is None
    broker.close()


def test_oversized_protocol_output_fails_safely_and_removes_temp(fake_binary, tmp_path):
    binary, _ = fake_binary
    binary.write_text(
        binary.read_text().replace(
            'emit({"id": request["id"], "result": {"userAgent": "test"}})',
            f'print("x" * {module.MAX_PROTOCOL_LINE + 1}, flush=True)',
        )
    )
    broker = ChatGPTAuthBroker(binary, tmp_path)
    with pytest.raises(ChatGPTAuthError) as error:
        broker.start()
    assert len(str(error.value)) < 150
    assert not list(tmp_path.glob("labcat-chatgpt-*"))
    broker.close()


def test_failed_account_read_cannot_promote_cached_models_to_readiness(
    broker, factory, auth
):
    factory.callback = lambda session: session.failures.add("account/read")
    public, _ = broker.metadata(auth)
    assert public["account_ready"] is False
    assert public["models"]
    factory.callback = lambda _: None
    assert broker.metadata(auth)[0]["account_ready"] is True


@pytest.mark.parametrize("readiness", [False, None, "true", 1])
def test_connection_model_test_rejects_unverified_cached_catalog(
    tmp_path, monkeypatch, readiness
):
    from labcat.connections import DEFAULT_PROFILE, ConnectionManager
    from labcat.credentials import ConnectionError

    manager = ConnectionManager(tmp_path / "workspace.sqlite3")
    manager.save_account(
        {
            "label": "Synthetic ChatGPT account",
            "profile": {
                **DEFAULT_PROFILE,
                "provider": "chatgpt",
                "model": "test-model",
            },
            "secret_storage": "session",
        }
    )
    metadata = {
        "account_ready": readiness,
        "models": [{"id": "test-model", "label": "Cached test model"}],
    }
    monkeypatch.setattr(manager.agent, "metadata", lambda _: metadata)
    with pytest.raises(ConnectionError, match="could not be verified"):
        manager.agent.models()
    assert manager.test("model")["status"] == "error"
    metadata["account_ready"] = True
    assert manager.agent.models()["models"][0]["id"] == "test-model"
    assert manager.test("model")["status"] == "ok"
