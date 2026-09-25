"""Recover abandoned sign-in views without duplicate auth or credential
reassignment."""

import base64

import pytest
from fastapi.testclient import TestClient

from labcat.connections import DEFAULT_PROFILE, ConnectionManager
from labcat.credentials import ConnectionError
from labcat.web import create_app


def _account(manager, label="Recovery test"):
    return manager.save_account(
        {
            "label": label,
            "profile": {**DEFAULT_PROFILE, "provider": "chatgpt"},
            "secret_storage": "session",
        }
    )["active_account_id"]


class RecoveryBroker:
    def __init__(self):
        self.starts = 0
        self.polls = 0
        self.takes = 0
        self.cancelled = []
        self.state = "pending"
        self.fail_poll = False

    def start(self):
        self.starts += 1
        self.state = "pending"
        self.public = {
            "flow_id": f"recovery-flow-{self.starts}",
            "status": "pending",
            "verification_url": "https://auth.openai.com/codex/device",
            "user_code": "TEST-1234",
        }
        return self.public.copy()

    def poll(self, identifier):
        self.polls += 1
        if self.fail_poll:
            raise ConnectionError("Test interrupted poll.")
        assert identifier == self.public["flow_id"]
        return {**self.public, "status": self.state}

    def cancel(self, identifier):
        self.cancelled.append(identifier)
        self.state = "cancelled"

    def take_credentials(self, identifier):
        self.takes += 1
        payload = base64.urlsafe_b64encode(b'{"exp":2000000000}').decode().rstrip("=")
        token = f"eyJhbGciOiJIUzI1NiJ9.{payload}.c2lnbmF0dXJl"
        return {
            "auth_mode": "chatgpt",
            "OPENAI_API_KEY": None,
            "tokens": {
                "access_token": token,
                "id_token": token,
                "refresh_token": "recovery-test-not-real",
                "account_id": "recovery-test-account",
            },
            "last_refresh": "2026-09-09T00:00:00Z",
        }


def _setup(tmp_path):
    manager = ConnectionManager(tmp_path / "workspace.sqlite3")
    identifier = _account(manager)
    broker = manager.agent._auth = RecoveryBroker()
    return manager, identifier, broker


def test_retry_after_closed_ui_or_lost_start_response_recovers_same_challenge(tmp_path):
    manager, account, broker = _setup(tmp_path)
    original = manager.agent.start_login(account, {"secret_storage": "session"})
    reopened = manager.agent.start_login(account, {"secret_storage": "session"})
    assert reopened == original
    assert broker.starts == 1
    assert broker.takes == 0
    assert manager.vault.get("oauth_" + account) is None


def test_recovery_after_provider_completion_saves_once_and_preserves_consent(tmp_path):
    manager, account, broker = _setup(tmp_path)
    original = manager.agent.start_login(account, {"secret_storage": "session"})
    broker.state = "complete"
    recovered = manager.agent.start_login(account, {"secret_storage": "session"})
    assert recovered["status"] == "complete"
    assert recovered["flow_id"] == original["flow_id"]
    assert broker.starts == broker.takes == 1
    assert manager.vault.get("oauth_" + account)
    manager.agent.login_action(account, original["flow_id"], "poll")
    assert broker.takes == 1
    assert manager.status()["profile"]["allow_paid_inference"] is False
    assert "tokens" not in recovered


@pytest.mark.parametrize("terminal", ["expired", "error", "cancelled"])
def test_terminal_abandoned_flow_cannot_block_new_login_forever(tmp_path, terminal):
    manager, account, broker = _setup(tmp_path)
    first = manager.agent.start_login(account, {"secret_storage": "session"})
    broker.state = terminal
    next_flow = manager.agent.start_login(account, {"secret_storage": "session"})
    assert next_flow["flow_id"] != first["flow_id"]
    assert next_flow["status"] == "pending"
    assert broker.starts == 2
    assert broker.takes == 0
    assert first["flow_id"] not in manager.agent._flows


def test_other_account_cannot_receive_pending_challenge_or_credentials(tmp_path):
    manager, first, broker = _setup(tmp_path)
    second = _account(manager, "Second recovery test")
    original = manager.agent.start_login(first, {"secret_storage": "session"})
    with pytest.raises(ConnectionError, match="other saved"):
        manager.agent.start_login(second, {"secret_storage": "session"})
    assert broker.starts == 1
    assert broker.takes == 0
    assert manager.agent.start_login(first, {"secret_storage": "session"}) == original
    broker.state = "expired"
    next_flow = manager.agent.start_login(second, {"secret_storage": "session"})
    assert next_flow["flow_id"] != original["flow_id"]
    assert manager.agent._flows[next_flow["flow_id"]]["account_id"] == second


def test_new_storage_choice_replaces_pending_flow_without_rebinding_it(tmp_path):
    manager, account, broker = _setup(tmp_path)
    manager.vault_action({"action": "create", "passphrase": "test recovery passphrase"})
    original = manager.agent.start_login(account, {"secret_storage": "session"})
    next_flow = manager.agent.start_login(account, {"secret_storage": "encrypted"})
    assert broker.cancelled == [original["flow_id"]]
    assert broker.starts == 2
    assert original["flow_id"] not in manager.agent._flows
    assert manager.agent._flows[next_flow["flow_id"]]["storage"] == "encrypted"
    assert manager.vault.get("oauth_" + account) is None


def test_interrupted_recovery_does_not_restart_or_discard_pending_login(tmp_path):
    manager, account, broker = _setup(tmp_path)
    original = manager.agent.start_login(account, {"secret_storage": "session"})
    broker.fail_poll = True
    with pytest.raises(ConnectionError):
        manager.agent.start_login(account, {"secret_storage": "session"})
    assert broker.starts == 1
    assert original["flow_id"] in manager.agent._flows
    broker.fail_poll = False
    assert manager.agent.start_login(account, {"secret_storage": "session"}) == original


def test_build_plan_preview_does_not_claim_a_request_was_rejected(tmp_path):
    with TestClient(
        create_app(workspace_path=tmp_path / "workspace.sqlite3"),
        base_url="http://localhost",
    ) as client:
        response = client.get("/api/research-plan")
    assert response.status_code == 200
    assert response.json()["request_allowed"] is None
    assert response.json()["scope"] == "workspace_preview"
    assert response.json()["steps"]
