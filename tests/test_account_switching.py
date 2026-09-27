"""Optional saved storage never controls which account the user can
select."""

import json
import threading

import pytest
from cryptography.fernet import Fernet
from test_agent_connections import Broker, auth_fixture
from test_agent_login_recovery import RecoveryBroker

from labcat.agent_connections import _pack
from labcat.chatgpt_auth import goose_token_cache
from labcat.connections import DEFAULT_PROFILE, ConnectionManager
from labcat.credentials import ConnectionError
from labcat.models import Plan

PHRASE = "fixture-only switching vault password"
FIRST_KEY = "fixture-only-first-model-key"
SECOND_KEY = "fixture-only-second-model-key"


@pytest.fixture(autouse=True)
def offline_accounts(monkeypatch):
    monkeypatch.delenv("LABCAT_VAULT_KEY", raising=False)
    monkeypatch.delenv("LABCAT_VAULT_KEY_FILE", raising=False)
    monkeypatch.setattr(
        "labcat.connections.request_json",
        lambda *a, **k: {"data": [{"id": "test-model"}, {"id": "other-model"}]},
    )


def save(
    manager,
    provider="openai",
    key=FIRST_KEY,
    storage="session",
    identifier=None,
    model="test-model",
):
    return manager.save_account(
        {
            "label": "Fixture " + provider,
            "profile": {
                **DEFAULT_PROFILE,
                "provider": provider,
                "model": model,
                "allow_paid_inference": True,
            },
            "secret_storage": storage,
            **({"api_key": key} if key is not None else {}),
        },
        identifier,
    )["active_account_id"]


def test_locked_accounts_allow_switching_model_edits_and_new_provider_keys(
    tmp_path, monkeypatch
):
    path = tmp_path / "workspace.sqlite3"
    manager = ConnectionManager(path)
    manager.vault.create(PHRASE)
    first = save(manager, storage="encrypted")
    second = save(manager, "anthropic", SECOND_KEY, "encrypted")
    ciphertext = manager.vault.path.read_bytes()
    manager = ConnectionManager(path)
    manager.select_account(first)
    save(manager, key=None, storage="encrypted", identifier=first, model="other-model")
    assert manager.status()["profile"]["model"] == "other-model"
    assert manager.status()["accounts"][1]["credential_state"] == "locked"
    third = save(manager, key=SECOND_KEY)
    manager.select_account(second)
    assert manager.setup.status()["model"]["status"] == "credentials_locked"
    manager.select_account(third)
    captured = []
    monkeypatch.setattr(
        "labcat.connections.plan_with_model",
        lambda profile, key, *a, **k: captured.append((profile, key)) or Plan(),
    )
    manager.plan("Find materials")
    assert captured[0][1] == SECOND_KEY
    assert manager.status()["vault"]["locked"]
    manager.select_account(first)
    assert manager.status()["profile"]["model"] == "other-model"
    assert manager.vault.path.read_bytes() == ciphertext
    manager.vault.unlock(PHRASE)
    assert manager.get_secret("account_" + first) == FIRST_KEY
    assert manager.get_secret("account_" + second) == SECOND_KEY
    assert manager.get_secret("account_" + third) == SECOND_KEY


@pytest.mark.parametrize("vault_condition", ["corrupt", "external_key_missing"])
def test_unavailable_vault_does_not_block_session_keys_or_repeated_oauth(
    tmp_path, monkeypatch, vault_condition
):
    path = tmp_path / "workspace.sqlite3"
    vault_path = path.with_suffix(".credentials.enc.json")
    if vault_condition == "corrupt":
        vault_path.write_text("{invalid encrypted document")
    else:
        monkeypatch.setenv("LABCAT_VAULT_KEY", Fernet.generate_key().decode())
        original = ConnectionManager(path)
        original.vault.update({"openai": FIRST_KEY}, [], "encrypted")
        monkeypatch.delenv("LABCAT_VAULT_KEY")
    ciphertext = vault_path.read_bytes()
    manager = ConnectionManager(path)
    assert manager.vault.status()["locked"]
    first = save(manager)
    save(manager, key=SECOND_KEY, identifier=first)
    assert manager.setup.verify()["can_research"]
    monkeypatch.setenv("LABCAT_AGENT_ENGINE", "goose")
    oauth = save(manager, "chatgpt", None)
    broker = manager.agent._auth = Broker()
    for _ in range(2):
        broker.state = "pending"
        flow = manager.agent.start_login(oauth, {"secret_storage": "session"})
        broker.state = "complete"
        manager.agent.login_action(oauth, flow["flow_id"], "poll")
        assert manager.setup.verify()["can_research"]
        manager.agent.forget_login(oauth)
        assert manager.get_secret("oauth_" + oauth) is None
        assert manager.vault.path.read_bytes() == ciphertext
    manager.select_account(first)
    assert manager.setup.verify()["can_research"]
    assert manager.get_secret("account_" + first) == SECOND_KEY
    assert manager.vault.path.read_bytes() == ciphertext


def test_locked_oauth_logout_ends_only_session_and_retains_other_accounts(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LABCAT_AGENT_ENGINE", "goose")
    path = tmp_path / "workspace.sqlite3"
    manager = ConnectionManager(path)
    manager.vault.create(PHRASE)
    first = save(manager, "chatgpt", None)
    second = save(manager, "chatgpt", None)
    original = _pack(auth_fixture())
    manager.vault.update(
        {"oauth_" + first: original, "oauth_" + second: original}, [], "encrypted"
    )
    ciphertext = manager.vault.path.read_bytes()
    manager.vault_action({"action": "lock"})
    manager.vault.update(
        {"oauth_" + first: original, "oauth_" + second: original}, [], "session"
    )
    manager.select_account(first)
    broker = manager.agent._auth = Broker()
    assert manager.setup.verify()["can_research"]
    flow = manager.agent.start_login(first, {"secret_storage": "session"})
    public = manager.agent.forget_login(first)
    assert public["active_account_id"] == first
    states = {a["id"]: a["credential_state"] for a in public["accounts"]}
    assert states == {first: "locked", second: "session"}
    assert manager.setup.status()["model"]["status"] == "credentials_locked"
    assert manager.get_secret("oauth_" + first) is None
    assert manager.get_secret("oauth_" + second) == original
    assert flow["flow_id"] in broker.cancelled
    assert manager.vault.path.read_bytes() == ciphertext
    broker.state = "pending"
    fresh = manager.agent.start_login(first, {"secret_storage": "session"})
    broker.state = "complete"
    manager.agent.login_action(first, fresh["flow_id"], "poll")
    assert manager.setup.verify()["can_research"]
    restarted = ConnectionManager(path)
    restarted.vault.unlock(PHRASE)
    assert restarted.get_secret("oauth_" + first) == original
    assert restarted.get_secret("oauth_" + second) == original


def test_late_oauth_callbacks_never_activate_or_invalidate_another_account(tmp_path):
    manager = ConnectionManager(tmp_path / "workspace.sqlite3")
    first = save(manager, "chatgpt", None)
    second = save(manager, "chatgpt", None)
    active = save(manager)
    broker = manager.agent._auth = RecoveryBroker()
    cancelled = manager.agent.start_login(first, {"secret_storage": "session"})
    pending = manager.agent.start_login(second, {"secret_storage": "session"})
    assert manager.setup.verify()["can_research"]
    broker.state = "complete"
    with pytest.raises(ConnectionError, match="unavailable"):
        manager.agent.login_action(first, cancelled["flow_id"], "poll")
    assert broker.takes == 0
    assert manager.status()["active_account_id"] == active
    manager.agent.login_action(second, pending["flow_id"], "poll")
    assert broker.takes == 1
    assert manager.get_secret("oauth_" + first) is None
    assert manager.get_secret("oauth_" + second) is not None
    assert manager.status()["active_account_id"] == active
    assert manager.setup.status()["can_research"]
    manager.agent.forget_login(second)
    assert manager.setup.status()["can_research"]
    assert manager.get_secret("account_" + active) == FIRST_KEY


@pytest.mark.parametrize("engine", ["direct", "goose"])
def test_switch_between_verification_and_capture_requires_a_new_check(
    tmp_path, monkeypatch, engine
):
    manager = ConnectionManager(tmp_path / "workspace.sqlite3")
    first = save(manager)
    second = save(manager, "anthropic", SECOND_KEY)
    manager.select_account(first)
    assert manager.setup.verify()["can_research"]
    verified, release = threading.Event(), threading.Event()
    original = manager.setup.require_ready
    calls, errors = [], []

    def paused_verification():
        state = original()
        verified.set()
        assert release.wait(5)
        return state

    monkeypatch.setattr(manager.setup, "require_ready", paused_verification)
    monkeypatch.setattr(
        "labcat.connections.plan_with_model",
        lambda profile, key, *a, **k: calls.append((profile, key)) or Plan(),
    )
    monkeypatch.setattr(
        "labcat.goose_worker_client.run_remote_goose",
        lambda profile, key, *a, **k: (
            calls.append((profile, key)) or {"status": "completed", "usage": None}
        ),
    )

    def run():
        try:
            if engine == "direct":
                manager.plan("Find materials")
            else:
                manager.agent.run("Find materials", None, None)
        except BaseException as error:
            errors.append(error)

    runner = threading.Thread(target=run)
    runner.start()
    try:
        assert verified.wait(5)
        manager.select_account(second)
        assert manager.status()["active_account_id"] == second
    finally:
        release.set()
        runner.join(5)
    assert not runner.is_alive()
    assert len(errors) == 1 and isinstance(errors[0], ConnectionError)
    assert "changed" in str(errors[0])
    assert calls == []
    assert manager.status()["active_account_id"] == second


def test_inflight_oauth_refresh_and_usage_stay_with_original_account_after_switch(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LABCAT_AGENT_ENGINE", "goose")
    manager = ConnectionManager(tmp_path / "workspace.sqlite3")
    first = save(manager, "chatgpt", None)
    second = save(manager, "anthropic", SECOND_KEY)
    manager.vault.update({"oauth_" + first: _pack(auth_fixture())}, [], "session")
    manager.select_account(first)
    manager.agent._auth = Broker()
    refreshed = goose_token_cache(auth_fixture())
    refreshed["refresh_token"] = "fixture-refreshed-original-account"

    def worker(profile, secret, prompt, **kwargs):
        assert profile["provider"] == "chatgpt" and secret is None
        assert kwargs["chatgpt_tokens"]["account_id"] == "fixture-account"
        manager.select_account(second)
        return {
            "status": "completed",
            "usage": None,
            "refreshed_chatgpt_tokens": refreshed,
        }

    monkeypatch.setattr("labcat.goose_worker_client.run_remote_goose", worker)
    result = manager.agent.run("Find materials", None, None)
    assert result["account_id"] == first and result["provider"] == "chatgpt"
    assert manager.status()["active_account_id"] == second
    assert manager.get_secret("account_" + second) == SECOND_KEY
    assert (
        manager.agent._credential_snapshot(first)[0]["tokens"]["refresh_token"]
        == refreshed["refresh_token"]
    )
    usage = json.loads(manager.agent.usage_path.read_text())
    assert set(usage) == {first}
    assert usage[first]["provider"] == "chatgpt"
    assert "refresh_token" not in json.dumps(result) + json.dumps(usage)


def test_provider_metadata_does_not_block_selection_or_verify_a_new_account(
    tmp_path, monkeypatch
):
    manager = ConnectionManager(tmp_path / "workspace.sqlite3")
    first = save(manager)
    second = save(manager, "anthropic", SECOND_KEY)
    manager.select_account(first)
    entered, release = threading.Event(), threading.Event()
    results, requests = [], []

    def paused_metadata(url, **kwargs):
        requests.append((url, kwargs))
        entered.set()
        assert release.wait(5)
        return {"data": [{"id": "test-model"}]}

    monkeypatch.setattr("labcat.connections.request_json", paused_metadata)
    runner = threading.Thread(target=lambda: results.append(manager.setup.verify()))
    runner.start()
    try:
        assert entered.wait(5)
        manager.select_account(second)
        assert manager.status()["active_account_id"] == second
    finally:
        release.set()
        runner.join(5)
    assert not runner.is_alive()
    assert requests[0][1]["headers"] == {"Authorization": "Bearer " + FIRST_KEY}
    assert results[0]["model"]["account_id"] == second
    assert not results[0]["can_research"]
    assert manager.setup.status()["model"]["status"] == "verification_required"
