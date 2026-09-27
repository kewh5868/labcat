"""Native subscription connections stay independent of the optional
vault."""

import json
from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock
from types import SimpleNamespace

import pytest

from labcat import claude_auth
from labcat.connections import DEFAULT_PROFILE, ConnectionManager
from labcat.credentials import ConnectionError, atomic_write

ACCOUNT = "a" * 32
SESSION = "b" * 32
NEXT = "c" * 32


@pytest.fixture
def native_store(tmp_path, monkeypatch):
    pytest.importorskip("fcntl")
    monkeypatch.setattr(claude_auth, "SESSION_ROOT", tmp_path / "native")
    monkeypatch.setattr("labcat.chatgpt_auth._is_tmpfs", lambda path: True)
    monkeypatch.setenv("LABCAT_GOOSE_ISOLATED", "1")
    monkeypatch.setattr(claude_auth.os, "access", lambda *a: True)
    return claude_auth._account(ACCOUNT)


def native_session(account, identifier=SESSION):
    folder = claude_auth._directory(account / identifier)
    atomic_write(account / "current.json", {"session_id": identifier})
    return folder


def test_native_status_filters_all_provider_details(native_store, monkeypatch):
    native_session(native_store)
    seen = []

    def run(command, **kwargs):
        seen.append((command, kwargs))
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                {
                    "loggedIn": True,
                    "email": "private@example.invalid",
                    "unexpected_token": "fixture-only-opaque-secret",
                }
            ).encode(),
        )

    monkeypatch.setattr(claude_auth.subprocess, "run", run)
    result = claude_auth.status(ACCOUNT)
    assert result["signed_in"] and result["session_id"] == SESSION
    assert "private" not in json.dumps(result)
    assert "fixture-only" not in json.dumps(result)
    assert seen[0][0] == [claude_auth.CLAUDE_BINARY, "auth", "status"]
    assert "ANTHROPIC_API_KEY" not in seen[0][1]["env"]


@pytest.mark.parametrize(
    "identifier", ["../other", "a" * 31, "x" * 32, "a" * 32 + ";whoami", None]
)
def test_native_paths_reject_untrusted_account_ids(identifier):
    with pytest.raises(ConnectionError):
        claude_auth.status(identifier)


def test_native_signin_requires_memory_backed_isolated_worker(tmp_path, monkeypatch):
    monkeypatch.setattr(claude_auth, "SESSION_ROOT", tmp_path / "native")
    monkeypatch.setattr("labcat.chatgpt_auth._is_tmpfs", lambda path: False)
    monkeypatch.setenv("LABCAT_GOOSE_ISOLATED", "1")
    with pytest.raises(ConnectionError, match="Docker"):
        claude_auth._account(ACCOUNT)
    assert not (tmp_path / "native").exists()


def test_new_session_and_logout_do_not_destroy_inflight_login(native_store):
    old = native_session(native_store)
    with claude_auth.session_environment(ACCOUNT, SESSION) as env:
        assert env["HOME"] == str(old)
        newer = native_session(native_store, NEXT)
        claude_auth._clean_inactive(native_store)
        assert old.exists() and newer.exists()
        with pytest.raises(ConnectionError, match="changed"):
            with claude_auth.session_environment(ACCOUNT, SESSION):
                pass
        assert not claude_auth.logout(ACCOUNT)["signed_in"]
        assert old.exists() and not newer.exists()
    assert not old.exists()


def test_failed_login_preserves_previous_native_session(native_store, monkeypatch):
    old = native_session(native_store)
    monkeypatch.setattr(claude_auth.os, "isatty", lambda fd: True)
    monkeypatch.setattr(
        claude_auth.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=1)
    )
    with pytest.raises(ConnectionError, match="previous connection"):
        claude_auth.login(ACCOUNT)
    assert claude_auth._current(native_store) == SESSION
    assert old.exists()
    assert len([p for p in native_store.iterdir() if len(p.name) == 32]) == 1


def test_login_keeps_native_terminal_stdio_and_never_reads_credentials(
    native_store, monkeypatch
):
    monkeypatch.setattr(claude_auth.os, "isatty", lambda fd: True)
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout=b'{"loggedIn":true}')

    monkeypatch.setattr(claude_auth.subprocess, "run", run)
    claude_auth.login(ACCOUNT)
    command, options = calls[0]
    assert command == [claude_auth.CLAUDE_BINARY, "auth", "login"]
    assert not {"stdin", "stdout", "stderr"} & options.keys()
    assert claude_auth.status(ACCOUNT)["signed_in"]
    assert not list(native_store.rglob("*.credentials.enc.json"))


def save(manager, provider="claude_code"):
    return manager.save_account(
        {
            "label": "Fixture Claude account",
            "profile": {
                **DEFAULT_PROFILE,
                "provider": provider,
                "model": "default",
                "allow_paid_inference": True,
            },
            "secret_storage": "session",
        }
    )["active_account_id"]


@pytest.fixture
def accounts(tmp_path, monkeypatch):
    monkeypatch.delenv("LABCAT_VAULT_KEY", raising=False)
    monkeypatch.delenv("LABCAT_VAULT_KEY_FILE", raising=False)
    monkeypatch.setenv("LABCAT_AGENT_ENGINE", "goose")
    state = {
        "available": True,
        "signed_in": True,
        "session_id": SESSION,
        "message": "Native CLI reports a sign-in.",
    }
    monkeypatch.setattr(
        "labcat.goose_worker_client._worker_request", lambda *a, **k: dict(state)
    )
    return ConnectionManager(tmp_path / "workspace.sqlite3"), state


def test_native_account_works_with_locked_vault_and_has_no_saved_secret(accounts):
    manager, state = accounts
    manager.vault.create("fixture-only vault passphrase")
    manager.vault.lock()
    identifier = save(manager)
    assert manager.status()["accounts"][0]["credential_state"] == "missing"
    public = manager.agent.claude_status(identifier)
    assert set(public) == {"available", "signed_in", "message"}
    assert manager.status()["accounts"][0]["credential_state"] == "session"
    assert manager.setup.verify()["can_research"]
    assert manager.vault.status()["locked"]
    assert manager._connection_snapshot()["secret"] is None
    assert manager._connection_snapshot()["claude_session_id"] == SESSION
    assert not any(
        "oauth_" in key or "account_" in key for key in manager.vault.slots()
    )


def test_native_reconnect_invalidates_only_selected_account_readiness(accounts):
    manager, state = accounts
    identifier = save(manager)
    assert manager.setup.verify()["can_research"]
    state["session_id"] = NEXT
    manager.agent.claude_status(identifier)
    assert not manager.setup.status()["can_research"]
    assert manager.setup.verify()["can_research"]
    assert manager._connection_snapshot()["claude_session_id"] == NEXT


def test_native_account_does_not_accept_api_keys_or_oauth_login(accounts):
    manager, _ = accounts
    identifier = save(manager)
    with pytest.raises(ConnectionError, match="ChatGPT"):
        manager.agent.start_login(identifier, {"secret_storage": "session"})
    with pytest.raises(ConnectionError, match="API key"):
        manager.save_account(
            {
                "label": "Fixture Claude account",
                "profile": manager.status()["profile"],
                "secret_storage": "session",
                "api_key": "fixture-only-key",
            },
            identifier,
        )


def test_native_research_passes_only_selected_local_generation(accounts, monkeypatch):
    manager, _ = accounts
    identifier = save(manager)
    manager.setup.verify()
    captures = []

    def run(profile, secret, prompt, **kwargs):
        captures.append((profile, secret, kwargs))
        return {"status": "completed", "usage": None}

    monkeypatch.setattr("labcat.goose_worker_client.run_remote_goose", run)
    manager.agent.run("Find oxide materials", None, object())
    _, secret, kwargs = captures[0]
    assert secret is None and kwargs["chatgpt_tokens"] is None
    assert kwargs["claude_account_id"] == identifier
    assert kwargs["claude_session_id"] == SESSION


def test_native_api_probes_hide_generation_and_logout_requires_csrf(
    tmp_path, monkeypatch
):
    from fastapi.testclient import TestClient

    from labcat.web import create_app

    state = {
        "available": True,
        "signed_in": True,
        "session_id": SESSION,
        "message": "Native CLI reports a sign-in.",
    }
    monkeypatch.setattr(
        "labcat.goose_worker_client._worker_request", lambda *a, **k: dict(state)
    )
    app = create_app(workspace_path=tmp_path / "workspace.sqlite3")
    identifier = save(app.state.connections)
    route = f"/api/connections/accounts/{identifier}/claude-code"
    with TestClient(app, base_url="http://127.0.0.1:8123") as client:
        token = client.get("/api/session").json()["csrf_token"]
        response = client.get(route)
        assert response.status_code == 200 and SESSION not in response.text
        assert client.post(route + "/logout", json={}).status_code == 403
        headers = {"X-CSRF-Token": token, "Origin": "http://127.0.0.1:8123"}
        assert (
            client.post(
                route + "/logout", json={"token": "fixture-only"}, headers=headers
            ).status_code
            == 422
        )
        assert (
            client.post(route + "/logout", json={}, headers=headers).status_code == 200
        )


class ObservedLock:
    """Expose the second caller's arrival without scheduling delays."""

    def __init__(self):
        self.lock = Lock()
        self.attempts_lock = Lock()
        self.attempts = 0
        self.second_entered = Event()

    def __enter__(self):
        with self.attempts_lock:
            self.attempts += 1
            if self.attempts == 2:
                self.second_entered.set()
        self.lock.acquire()

    def __exit__(self, *args):
        self.lock.release()


@pytest.mark.parametrize("session_changes", [False, True])
def test_concurrent_native_status_and_catalog_preserve_latest_session(
    accounts, monkeypatch, session_changes
):
    manager, state = accounts
    identifier = save(manager)
    assert manager.setup.verify()["can_research"]
    lock = ObservedLock()
    manager.agent._claude_locks[identifier] = lock
    entered, release = Event(), Event()
    calls = []

    def worker(path, payload):
        assert path == "/claude/status"
        assert payload == {"account_id": identifier}
        calls.append(path)
        result = dict(state)
        if len(calls) == 1:
            entered.set()
            assert release.wait(10), "The test did not release the first check"
        elif session_changes:
            result["session_id"] = NEXT
        return result

    monkeypatch.setattr("labcat.goose_worker_client._worker_request", worker)
    with ThreadPoolExecutor(max_workers=2) as pool:
        status = pool.submit(manager.agent.claude_status, identifier)
        try:
            assert entered.wait(5)
            catalog = pool.submit(manager.agent.claude_models, identifier)
            assert lock.second_entered.wait(5)
            assert calls == ["/claude/status"]
        finally:
            release.set()
        assert status.result(timeout=5)["signed_in"]
        assert catalog.result(timeout=5)["models"]
    assert len(calls) == 2
    assert manager._connection_snapshot()["claude_session_id"] == (
        NEXT if session_changes else SESSION
    )
    assert manager.setup.status()["can_research"] is not session_changes


@pytest.mark.parametrize("logout_first", [False, True])
def test_native_checks_and_logout_cannot_restore_an_ended_session(
    accounts, monkeypatch, logout_first
):
    manager, state = accounts
    identifier = save(manager)
    assert manager.setup.verify()["can_research"]
    lock = ObservedLock()
    manager.agent._claude_locks[identifier] = lock
    entered, release = Event(), Event()
    calls = []

    def worker(path, payload):
        assert payload == {"account_id": identifier}
        calls.append(path)
        if len(calls) == 1:
            entered.set()
            assert release.wait(10), "The test did not release the first check"
        if path == "/claude/logout":
            state.update(signed_in=False, session_id=None)
        return dict(state)

    monkeypatch.setattr("labcat.goose_worker_client._worker_request", worker)
    first_path = "/claude/logout" if logout_first else "/claude/status"
    second_path = "/claude/status" if logout_first else "/claude/logout"
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(
            manager.agent.claude_status, identifier, logout=logout_first
        )
        try:
            assert entered.wait(5)
            second = pool.submit(
                manager.agent.claude_status, identifier, logout=not logout_first
            )
            assert lock.second_entered.wait(5)
            assert calls == [first_path]
        finally:
            release.set()
        first.result(timeout=5)
        assert not second.result(timeout=5)["signed_in"]
    assert calls == [first_path, second_path]
    assert not manager.agent._claude_sessions[identifier]["signed_in"]
    assert not manager.setup.status()["can_research"]
