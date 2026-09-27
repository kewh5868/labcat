"""Password changes and credential reuse preserve unrelated saved
connections."""

import json

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from test_agent_connections import Broker, add, auth_fixture

from labcat.agent_connections import _pack
from labcat.connections import DEFAULT_PROFILE, ConnectionManager
from labcat.credentials import ConnectionError
from labcat.web import create_app

PHRASE = "fixture original vault password"
NEXT_PHRASE = "fixture replacement vault password"
WRONG_PHRASE = "fixture incorrect vault password"
SOURCE = "materials_project"
KEY = "fixture-original-source-key"
NEXT_KEY = "fixture-replacement-source-key"
MODEL_KEY = "fixture-model-api-key"
SESSION_KEY = "fixture-session-api-key"


@pytest.fixture(autouse=True)
def no_external_key(monkeypatch):
    monkeypatch.delenv("LABCAT_VAULT_KEY", raising=False)
    monkeypatch.delenv("LABCAT_VAULT_KEY_FILE", raising=False)
    monkeypatch.setattr(
        "labcat.science.sources.probe_connection", lambda key: {"records_checked": 1}
    )


@pytest.fixture
def manager(tmp_path):
    value = ConnectionManager(tmp_path / "workspace.sqlite3")
    value.vault.create(PHRASE)
    value.vault.update({SOURCE: KEY, "openai": MODEL_KEY}, [], "encrypted")
    return value


def reopen(manager):
    return ConnectionManager(
        manager.profile_path.with_suffix("").with_suffix(".sqlite3")
    )


def rotation(current=PHRASE, replacement=NEXT_PHRASE):
    return {
        "action": "change_passphrase",
        "current_passphrase": current,
        "new_passphrase": replacement,
    }


def account_body(storage="session", key=MODEL_KEY):
    return {
        "label": "Fixture model",
        "profile": {
            **DEFAULT_PROFILE,
            "provider": "openai",
            "model": "fixture-model",
            "allow_paid_inference": True,
        },
        "secret_storage": storage,
        **({"api_key": key} if key is not None else {}),
    }


@pytest.mark.parametrize("locked", [False, True])
def test_password_change_preserves_saved_and_session_keys_across_restart(
    manager, locked
):
    if locked:
        manager = reopen(manager)
    manager.vault.update({"kimi": SESSION_KEY, SOURCE: NEXT_KEY}, [], "session")
    before = json.loads(manager.vault.path.read_text())
    status = manager.vault_action(rotation())
    assert status["vault"]["available"] and not status["vault"]["locked"]
    assert manager.get_secret(SOURCE) == NEXT_KEY
    assert manager.get_secret("openai") == MODEL_KEY
    assert manager.get_secret("kimi") == SESSION_KEY
    after = json.loads(manager.vault.path.read_text())
    assert after["salt"] != before["salt"] and after["token"] != before["token"]
    assert after["slots"] == before["slots"]
    restarted = reopen(manager)
    with pytest.raises(ConnectionError):
        restarted.vault.unlock(PHRASE)
    restarted.vault.unlock(NEXT_PHRASE)
    assert restarted.get_secret(SOURCE) == KEY
    assert restarted.get_secret("openai") == MODEL_KEY
    assert restarted.get_secret("kimi") is None
    for secret in (PHRASE, NEXT_PHRASE, KEY, NEXT_KEY, MODEL_KEY, SESSION_KEY):
        assert secret not in manager.vault.path.read_text() + json.dumps(status)


@pytest.mark.parametrize("locked", [False, True])
@pytest.mark.parametrize("failure", ["wrong_password", "invalid_new", "write_failure"])
def test_password_change_failure_preserves_previous_usable_state(
    manager, monkeypatch, locked, failure
):
    if locked:
        manager = reopen(manager)
    manager.vault.update({"kimi": SESSION_KEY}, [], "session")
    before = manager.vault.checkpoint()
    key, salt = manager.vault._fernet, manager.vault._salt
    ciphertext = manager.vault.path.read_bytes()
    request = rotation()
    if failure == "wrong_password":
        request = rotation(current=WRONG_PHRASE)
    elif failure == "invalid_new":
        request = rotation(replacement="too short")
    else:

        def fail_replace(*args):
            raise OSError("fixture-only write failure")

        monkeypatch.setattr("labcat.credentials.os.replace", fail_replace)
    with pytest.raises(ConnectionError) as failure_info:
        manager.vault_action(request)
    assert manager.vault.checkpoint() == before
    assert manager.vault._fernet is key and manager.vault._salt == salt
    assert manager.vault.path.read_bytes() == ciphertext
    assert manager.get_secret("kimi") == SESSION_KEY
    assert not list(manager.vault.path.parent.glob(".labcat-*"))
    assert PHRASE not in str(failure_info.value)
    assert NEXT_PHRASE not in str(failure_info.value)
    restarted = reopen(manager)
    restarted.vault.unlock(PHRASE)
    assert restarted.get_secret(SOURCE) == KEY


def test_failed_password_actions_keep_verified_credentials_usable(
    tmp_path, authenticated_model_factory
):
    manager = authenticated_model_factory(tmp_path / "workspace.sqlite3")
    manager.vault.create(PHRASE)
    manager.vault.update({SOURCE: KEY}, [], "encrypted")
    assert manager.setup.verify()["can_research"]
    assert manager.test(SOURCE)["status"] == "ok"
    for request in (
        rotation(current=WRONG_PHRASE),
        {"action": "unlock", "passphrase": WRONG_PHRASE},
    ):
        with pytest.raises(ConnectionError):
            manager.vault_action(request)
        assert manager.setup.status()["can_research"]
        assert manager.materials_project_key("auto") == KEY
    manager.vault_action(rotation())
    assert not manager.setup.status()["can_research"]
    assert manager.source_connections()[SOURCE]["status"] == "verification_required"


def test_deployment_key_cannot_be_replaced_by_a_password(tmp_path, monkeypatch):
    monkeypatch.setenv("LABCAT_VAULT_KEY", Fernet.generate_key().decode())
    manager = ConnectionManager(tmp_path / "workspace.sqlite3")
    manager.vault.update({SOURCE: KEY}, [], "encrypted")
    ciphertext = manager.vault.path.read_bytes()
    with pytest.raises(ConnectionError, match="password-protected"):
        manager.vault_action(rotation())
    assert manager.get_secret(SOURCE) == KEY
    assert manager.vault.path.read_bytes() == ciphertext
    assert reopen(manager).get_secret(SOURCE) == KEY


@pytest.mark.parametrize("replacement", [KEY, NEXT_KEY])
def test_locked_source_accepts_session_override_without_changing_saved_keys(
    manager, replacement
):
    ciphertext = manager.vault.path.read_bytes()
    manager = reopen(manager)
    status = manager.configure_source(
        SOURCE, {"secret_storage": "session", "api_key": replacement}
    )
    assert status["vault"]["locked"]
    assert status["credentials"][SOURCE] == "session"
    assert status["credentials"]["openai"] == "locked"
    assert manager.get_secret(SOURCE) == replacement
    assert manager.test(SOURCE)["status"] == "ok"
    assert manager.materials_project_key("auto") == replacement
    assert manager.vault.path.read_bytes() == ciphertext
    manager.vault_action({"action": "unlock", "passphrase": PHRASE})
    assert manager.get_secret(SOURCE) == replacement
    assert manager.get_secret("openai") == MODEL_KEY
    assert manager.source_connections()[SOURCE]["status"] == "verification_required"
    restarted = reopen(manager)
    restarted.vault.unlock(PHRASE)
    assert restarted.get_secret(SOURCE) == KEY


def test_source_saved_key_is_reused_after_restart_and_unlock(manager):
    manager = reopen(manager)
    manager.vault_action({"action": "unlock", "passphrase": PHRASE})
    status = manager.configure_source(SOURCE, {"secret_storage": "encrypted"})
    assert status["credentials"][SOURCE] == "encrypted"
    assert manager.test(SOURCE)["status"] == "ok"
    assert manager.materials_project_key("auto") == KEY
    assert manager.get_secret("openai") == MODEL_KEY


@pytest.mark.parametrize("blank", [None, ""])
def test_model_session_key_can_be_saved_without_reentry_and_without_other_keys(
    manager, blank
):
    identifier = manager.save_account(account_body())["active_account_id"]
    other = manager.save_account({**account_body(), "label": "Other model"})[
        "active_account_id"
    ]
    manager.save_account(account_body("encrypted", blank), identifier)
    assert manager.status()["credentials"]["openai"] == "encrypted"
    assert manager.vault.slots()["account_" + other] == "session"
    restarted = reopen(manager)
    assert restarted.status()["credentials"]["openai"] == "locked"
    restarted.vault_action({"action": "unlock", "passphrase": PHRASE})
    assert restarted.get_secret("account_" + identifier) == MODEL_KEY
    assert restarted.get_secret("account_" + other) is None
    assert restarted.get_secret(SOURCE) == KEY
    restarted.save_account(account_body("encrypted", blank), identifier)
    assert restarted.get_secret("account_" + identifier) == MODEL_KEY


@pytest.mark.parametrize("replacement", [MODEL_KEY, SESSION_KEY])
def test_locked_model_accepts_metadata_edits_and_session_override(manager, replacement):
    identifier = manager.save_account(account_body("encrypted"))["active_account_id"]
    ciphertext = manager.vault.path.read_bytes()
    manager = reopen(manager)
    status = manager.save_account(account_body("encrypted", None), identifier)
    assert status["accounts"][0]["credential_state"] == "locked"
    assert manager.vault.path.read_bytes() == ciphertext
    assert not manager.pending_path.exists()
    manager.save_account(account_body("session", replacement), identifier)
    assert manager.get_secret("account_" + identifier) == replacement
    assert manager.vault.path.read_bytes() == ciphertext
    restarted = reopen(manager)
    restarted.vault.unlock(PHRASE)
    assert restarted.get_secret("account_" + identifier) == MODEL_KEY
    assert restarted.get_secret(SOURCE) == KEY


def test_locked_oauth_accepts_fresh_session_login_without_touching_ciphertext(
    manager, monkeypatch
):
    monkeypatch.setenv("LABCAT_AGENT_ENGINE", "goose")
    identifier = add(manager)
    manager.configure(
        {
            "profile": {**manager.status()["profile"], "allow_paid_inference": True},
            "secret_storage": "session",
        }
    )
    old_auth = auth_fixture()
    old_auth["tokens"]["refresh_token"] = "fixture-saved-old-login-token"
    manager.vault.update({"oauth_" + identifier: _pack(old_auth)}, [], "encrypted")
    ciphertext = manager.vault.path.read_bytes()
    manager = reopen(manager)
    broker = manager.agent._auth = Broker()
    flow = manager.agent.start_login(identifier, {"secret_storage": "session"})
    broker.state = "complete"
    public = manager.agent.login_action(identifier, flow["flow_id"], "poll")
    assert public["status"] == "complete"
    assert manager.status()["vault"]["locked"]
    assert manager.status()["accounts"][0]["credential_state"] == "session"
    assert manager.vault.path.read_bytes() == ciphertext
    assert manager.setup.verify()["can_research"]
    assert manager.vault.path.read_bytes() == ciphertext
    assert "refresh_token" not in json.dumps(public) + json.dumps(manager.status())
    restarted = reopen(manager)
    restarted.vault.unlock(PHRASE)
    assert restarted.agent._credential_snapshot(identifier)[0] == old_auth


def test_fresh_login_invalidates_previous_verification_even_if_tokens_are_unchanged(
    manager, monkeypatch
):
    identifier = add(manager)
    manager.vault.update({"oauth_" + identifier: _pack(auth_fixture())}, [], "session")
    invalidations = []
    monkeypatch.setattr(manager.setup, "invalidate", lambda: invalidations.append(True))
    broker = manager.agent._auth = Broker()
    flow = manager.agent.start_login(identifier, {"secret_storage": "session"})
    assert invalidations == []
    broker.state = "complete"
    manager.agent.login_action(identifier, flow["flow_id"], "poll")
    manager.agent.login_action(identifier, flow["flow_id"], "poll")
    assert invalidations == [True]


def test_confirmed_reset_clears_corrupt_vault_and_all_session_credentials(manager):
    manager.vault.path.write_text("{broken ciphertext")
    manager = reopen(manager)
    manager.vault.update(
        {"kimi": SESSION_KEY, "oauth_" + "a" * 32: _pack(auth_fixture())}, [], "session"
    )
    assert manager.status()["warnings"]
    with pytest.raises(ConnectionError):
        manager.vault_action({"action": "reset"})
    assert manager.vault.path.exists() and manager.get_secret("kimi") == SESSION_KEY
    status = manager.vault_action({"action": "reset", "confirm": True})
    assert status["vault"]["can_create"]
    assert set(status["credentials"].values()) == {"missing"}
    assert not manager.vault.session and not manager.vault.path.exists()
    manager.vault_action({"action": "create", "passphrase": NEXT_PHRASE})
    assert not manager.vault._encrypted


def test_vault_password_route_requires_csrf_and_never_echoes_credentials(
    tmp_path, caplog
):
    app = create_app(workspace_path=tmp_path / "workspace.sqlite3")
    manager = app.state.connections
    manager.vault.create(PHRASE)
    manager.vault.update({SOURCE: KEY}, [], "encrypted")
    ciphertext = manager.vault.path.read_bytes()
    with TestClient(app, base_url="http://127.0.0.1:8123") as client:
        route = "/api/connections/vault"
        token = client.get("/api/session").json()["csrf_token"]
        for headers in (
            {},
            {"X-CSRF-Token": token, "Origin": "https://attacker.invalid"},
        ):
            assert (
                client.post(route, json=rotation(), headers=headers).status_code == 403
            )
            assert manager.vault.path.read_bytes() == ciphertext
        headers = {"X-CSRF-Token": token, "Origin": "http://127.0.0.1:8123"}
        for body in (
            rotation(current=WRONG_PHRASE),
            rotation(replacement="short"),
            {**rotation(), "extra": KEY},
            {"action": "change_passphrase", "new_passphrase": NEXT_PHRASE},
        ):
            response = client.post(route, json=body, headers=headers)
            assert response.status_code == 422
            assert manager.vault.path.read_bytes() == ciphertext
            assert all(
                secret not in response.text
                for secret in (KEY, PHRASE, NEXT_PHRASE, WRONG_PHRASE)
            )
        response = client.post(
            route, json=rotation(replacement="x" * 25000), headers=headers
        )
        assert response.status_code == 413
        response = client.post(route, json=rotation(), headers=headers)
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert all(secret not in response.text for secret in (KEY, PHRASE, NEXT_PHRASE))
        assert (
            client.post(route, json={"action": "reset", "confirm": True}).status_code
            == 403
        )
        assert manager.get_secret(SOURCE) == KEY
        assert (
            client.post(
                route, json={"action": "reset", "confirm": True}, headers=headers
            ).status_code
            == 200
        )
        assert manager.get_secret(SOURCE) is None and not manager.vault.path.exists()
    assert all(
        secret not in caplog.text for secret in (KEY, PHRASE, NEXT_PHRASE, WRONG_PHRASE)
    )


def test_failed_reset_preserves_saved_session_keys_and_usable_vault(
    manager, monkeypatch
):
    manager.vault.update({"kimi": SESSION_KEY}, [], "session")
    assert manager.test(SOURCE)["status"] == "ok"
    before = manager.vault.checkpoint()
    ciphertext = manager.vault.path.read_bytes()
    fernet = manager.vault._fernet

    def fail_unlink(*args, **kwargs):
        raise OSError("fixture-only deletion denied")

    monkeypatch.setattr(type(manager.vault.path), "unlink", fail_unlink)
    with pytest.raises(ConnectionError, match="could not be reset") as failure:
        manager.vault_action({"action": "reset", "confirm": True})
    assert "fixture-only" not in str(failure.value)
    assert manager.vault.checkpoint() == before
    assert manager.vault._fernet is fernet
    assert manager.vault.path.read_bytes() == ciphertext
    assert manager.get_secret(SOURCE) == KEY
    assert manager.get_secret("openai") == MODEL_KEY
    assert manager.get_secret("kimi") == SESSION_KEY
    assert manager.materials_project_key("auto") == KEY
    restarted = reopen(manager)
    restarted.vault.unlock(PHRASE)
    assert restarted.get_secret(SOURCE) == KEY
    assert restarted.get_secret("openai") == MODEL_KEY
