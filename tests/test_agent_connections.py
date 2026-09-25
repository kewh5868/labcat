"""Account isolation and authorization; all credentials are inert test
fixtures."""

import base64
import copy
import json

import pytest

from labcat.agent_connections import _pack
from labcat.connections import DEFAULT_PROFILE, ConnectionManager
from labcat.credentials import ConnectionError


def auth_fixture():
    def token(payload):
        body = (
            base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
        )
        return "eyJhbGciOiJIUzI1NiJ9." + body + ".c2lnbmF0dXJl"

    return {
        "auth_mode": "chatgpt",
        "OPENAI_API_KEY": None,
        "tokens": {
            "access_token": token({"exp": 2_000_000_000}),
            "refresh_token": "fixture-not-an-actual-credential",
            "id_token": token({"test": "fixture"}),
            "account_id": "fixture-account",
        },
        "last_refresh": "2026-09-09T00:00:00Z",
    }


def add(manager, name="My ChatGPT account", provider="chatgpt"):
    return manager.save_account(
        {
            "label": name,
            "profile": {**DEFAULT_PROFILE, "provider": provider, "model": "test-model"},
            "secret_storage": "session",
        }
    )["active_account_id"]


class Broker:
    def __init__(self):
        self.state = "pending"
        self.takes = 0
        self.cancelled = []

    def start(self):
        return {
            "flow_id": "test-flow",
            "status": "pending",
            "verification_url": "https://auth.openai.com/codex/device",
            "user_code": "TEST-0000",
        }

    def poll(self, identifier):
        return {"flow_id": identifier, "status": self.state}

    def cancel(self, identifier):
        self.cancelled.append(identifier)

    def take_credentials(self, identifier):
        self.takes += 1
        return auth_fixture()

    def metadata(self, auth):
        refreshed = copy.deepcopy(auth)
        refreshed["tokens"]["refresh_token"] = "rotated-test-refresh-credential"
        return {
            "account_ready": True,
            "models": [{"id": "test-model", "label": "Test model"}],
            "rate_limits": None,
            "token_activity": None,
            "notices": [],
            "inference_tested": False,
        }, refreshed

    def close(self):
        pass


def test_login_is_bound_to_account_no_activation_or_secret_response(tmp_path):
    manager = ConnectionManager(tmp_path / "workspace.sqlite3")
    first = add(manager)
    second = add(manager, "Other account")
    broker = manager.agent._auth = Broker()
    public = manager.agent.start_login(first, {"secret_storage": "session"})
    with pytest.raises(ConnectionError):
        manager.agent.login_action(second, public["flow_id"], "poll")
    broker.state = "complete"
    manager.agent.login_action(first, public["flow_id"], "poll")
    manager.agent.login_action(first, public["flow_id"], "poll")
    assert broker.takes == 1
    assert manager.status()["active_account_id"] == second
    assert manager.status()["profile"]["allow_paid_inference"] is False
    assert manager.vault.get("oauth_" + first)
    assert manager.vault.get("oauth_" + second) is None
    assert "refresh_token" not in json.dumps(manager.status())
    assert not manager.vault.path.exists()
    # A completed flow must not prevent another explicit sign-in.
    manager.agent.start_login(second, {"secret_storage": "session"})


def test_encrypted_oauth_restart_lock_and_metadata_rotation(tmp_path):
    path = tmp_path / "workspace.sqlite3"
    manager = ConnectionManager(path)
    identifier = add(manager)
    manager.vault_action({"action": "create", "passphrase": "test vault passphrase"})
    broker = manager.agent._auth = Broker()
    manager.agent.start_login(identifier, {"secret_storage": "encrypted"})
    broker.state = "complete"
    manager.agent.login_action(identifier, "test-flow", "poll")
    disk = manager.vault.path.read_text()
    assert "fixture-not-an-actual-credential" not in disk
    assert _pack(auth_fixture()) not in disk
    restored = ConnectionManager(path)
    assert restored.status()["accounts"][0]["credential_state"] == "locked"
    with pytest.raises(ConnectionError):
        restored.agent.models()
    restored.vault_action({"action": "unlock", "passphrase": "test vault passphrase"})
    restored.agent._auth = Broker()
    assert restored.agent.models()["models"][0]["id"] == "test-model"
    assert (
        restored.agent._credential_snapshot(identifier)[0]["tokens"]["refresh_token"]
        == "rotated-test-refresh-credential"
    )
    restored.agent.forget_login(identifier)
    assert restored.vault.get("oauth_" + identifier) is None
    assert restored.status()["accounts"][0]["credential_state"] == "missing"


def test_external_key_oauth_restart_and_rotation_need_no_interactive_unlock(
    tmp_path, monkeypatch
):
    """A deployment key restores only encrypted credentials, including
    rotation."""
    from cryptography.fernet import Fernet

    key_file = tmp_path / "deployment-key"
    key = Fernet.generate_key()
    key_file.write_bytes(key)
    key_file.chmod(0o400)
    monkeypatch.delenv("LABCAT_VAULT_KEY", raising=False)
    monkeypatch.setenv("LABCAT_VAULT_KEY_FILE", str(key_file))
    workspace = tmp_path / "workspace" / "workspace.sqlite3"
    manager = ConnectionManager(workspace)
    identifier = add(manager)
    broker = manager.agent._auth = Broker()
    manager.agent.start_login(identifier, {"secret_storage": "encrypted"})
    broker.state = "complete"
    manager.agent.login_action(identifier, "test-flow", "poll")
    manager.agent.close()

    restarted = ConnectionManager(workspace)
    assert restarted.status()["vault"] == {
        "available": True,
        "locked": False,
        "key_source": "file",
        "exists": True,
        "can_create": False,
    }
    assert restarted.status()["accounts"][0]["credential_state"] == "encrypted"
    restarted.agent._auth = Broker()
    assert restarted.agent.metadata(identifier)["account_ready"] is True
    restarted.agent.close()

    after_rotation = ConnectionManager(workspace)
    assert (
        after_rotation.agent._credential_snapshot(identifier)[0]["tokens"][
            "refresh_token"
        ]
        == "rotated-test-refresh-credential"
    )
    for path in workspace.parent.iterdir():
        data = path.read_bytes()
        assert key not in data
        assert b"fixture-not-an-actual-credential" not in data
        assert b"rotated-test-refresh-credential" not in data
    assert "refresh_token" not in json.dumps(after_rotation.status())

    # Losing the deployment key must preserve ciphertext and stop credential use.
    ciphertext = after_rotation.vault.path.read_bytes()
    monkeypatch.delenv("LABCAT_VAULT_KEY_FILE")
    locked = ConnectionManager(workspace)
    assert locked.status()["vault"]["locked"] is True
    with pytest.raises(ConnectionError, match="Sign in"):
        locked.agent._credential_snapshot(identifier)
    assert locked.vault.path.read_bytes() == ciphertext
    monkeypatch.setenv("LABCAT_VAULT_KEY_FILE", str(key_file))
    restored = ConnectionManager(workspace)
    assert restored.status()["accounts"][0]["credential_state"] == "encrypted"


def test_lock_cancels_pending_signin_and_cannot_repopulate_session(tmp_path):
    manager = ConnectionManager(tmp_path / "workspace.sqlite3")
    identifier = add(manager)
    manager.vault_action({"action": "create", "passphrase": "test vault passphrase"})
    broker = manager.agent._auth = Broker()
    manager.agent.start_login(identifier, {"secret_storage": "session"})
    manager.vault_action({"action": "lock"})
    broker.state = "complete"
    with pytest.raises(ConnectionError):
        manager.agent.login_action(identifier, "test-flow", "poll")
    assert broker.cancelled == ["test-flow"]
    assert manager.vault.get("oauth_" + identifier) is None


def test_metadata_cannot_resurrect_concurrently_forgotten_login(tmp_path):
    manager = ConnectionManager(tmp_path / "workspace.sqlite3")
    identifier = add(manager)
    manager.vault.update({"oauth_" + identifier: _pack(auth_fixture())}, [], "session")

    class Changed(Broker):
        def metadata(self, auth):
            manager.agent.forget_login(identifier)
            return super().metadata(auth)

    manager.agent._auth = Changed()
    with pytest.raises(ConnectionError):
        manager.agent.metadata(identifier)
    assert manager.vault.get("oauth_" + identifier) is None


def test_usage_unavailable_and_tampered_cache_never_becomes_balance(tmp_path):
    manager = ConnectionManager(tmp_path / "workspace.sqlite3")
    identifier = add(manager, provider="openai")
    manager.agent.usage_path.write_text(
        json.dumps({identifier: {"tokens_remaining": 9000, "password": "private-test"}})
    )
    result = manager.agent.usage()
    assert result["rate_limits"] is None and result["last_run"] is None
    assert "private-test" not in json.dumps(result)


def test_unsigned_account_usage_explains_signin_without_provider_request(
    tmp_path, monkeypatch
):
    manager = ConnectionManager(tmp_path / "workspace.sqlite3")
    add(manager)
    monkeypatch.setattr(
        manager.agent, "metadata", lambda *args: pytest.fail("Unsigned account request")
    )
    result = manager.agent.usage()
    assert result["rate_limits"] is None and result["token_activity"] is None
    assert "Sign in" in result["notices"][0]
