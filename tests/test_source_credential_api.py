"""Inline source credentials remain separate from accounts and report
history."""

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from labcat.connections import DEFAULT_PROFILE, ConnectionManager
from labcat.connections_api import create_connections_router
from labcat.credentials import ConnectionError

SOURCE = "materials_project"
KEY = "fixture-only-source-api-key"
NEXT_KEY = "fixture-only-replacement-source-key"
MODEL_KEY = "fixture-only-model-api-key"
LOGIN = "fixture_only_account_login_credential"
PHRASE = "fixture-only source vault passphrase"


@pytest.fixture
def manager(tmp_path, monkeypatch):
    monkeypatch.delenv("LABCAT_VAULT_KEY", raising=False)
    monkeypatch.delenv("LABCAT_VAULT_KEY_FILE", raising=False)
    monkeypatch.setattr(
        "labcat.science.sources.probe_connection",
        lambda key: {"records_checked": 1, "id_format": "legacy"},
    )
    return ConnectionManager(tmp_path / "workspace.sqlite3")


def save(manager, key=KEY, storage="session"):
    return manager.configure_source(
        SOURCE,
        {"secret_storage": storage, **({"api_key": key} if key is not None else {})},
    )


def reopen(manager):
    return ConnectionManager(
        manager.profile_path.with_suffix("").with_suffix(".sqlite3")
    )


def test_source_card_does_not_configure_a_model_or_write_session_keys(manager):
    status = save(manager)
    assert not status["configured"]
    assert not manager.profile_path.exists()
    assert not manager.pending_path.exists()
    assert not manager.vault.path.exists()
    assert status["credentials"][SOURCE] == "session"
    assert status["source_connections"][SOURCE]["status"] == "verification_required"
    assert manager.materials_project_key("auto") is None
    assert KEY not in json.dumps(status)
    assert reopen(manager).get_secret(SOURCE) is None


def test_source_edit_preserves_all_accounts_auth_and_model_readiness(
    manager, monkeypatch
):
    manager.vault_action({"action": "create", "passphrase": PHRASE})
    openai = manager.save_account(
        {
            "label": "OpenAI",
            "profile": {
                **DEFAULT_PROFILE,
                "provider": "openai",
                "model": "fixture-model",
                "allow_paid_inference": True,
            },
            "api_key": MODEL_KEY,
            "secret_storage": "encrypted",
        }
    )["active_account_id"]
    chatgpt = manager.save_account(
        {
            "label": "ChatGPT",
            "profile": {
                **DEFAULT_PROFILE,
                "provider": "chatgpt",
                "model": "fixture-account-model",
                "allow_paid_inference": True,
            },
            "secret_storage": "session",
        }
    )["active_account_id"]
    manager.vault.update({"oauth_" + chatgpt: LOGIN}, [], "session")
    before = manager.status()
    profile_bytes = manager.profile_path.read_bytes()
    monkeypatch.setattr(
        manager.setup, "invalidate", lambda: pytest.fail("Model readiness invalidated")
    )
    monkeypatch.setattr(
        manager.agent, "cancel_pending", lambda: pytest.fail("Account login cancelled")
    )
    for key, storage in [(KEY, "session"), (None, "encrypted"), (NEXT_KEY, "session")]:
        status = save(manager, key, storage)
        assert manager.test(SOURCE)["status"] == "ok"
        for field in ("profile", "accounts", "active_account_id", "configured"):
            assert status[field] == before[field]
        assert manager.profile_path.read_bytes() == profile_bytes
        assert manager.get_secret("account_" + openai) == MODEL_KEY
        assert manager.get_secret("oauth_" + chatgpt) == LOGIN
        assert not manager.pending_path.exists()
    manager.configure_source(SOURCE, {"forget": True})
    assert manager.get_secret(SOURCE) is None
    assert manager.get_secret("account_" + openai) == MODEL_KEY
    assert manager.get_secret("oauth_" + chatgpt) == LOGIN
    assert manager.profile_path.read_bytes() == profile_bytes


def test_source_key_promotion_restart_demotion_and_forgetting(manager):
    manager.vault_action({"action": "create", "passphrase": PHRASE})
    save(manager)
    assert manager.test(SOURCE)["status"] == "ok"
    status = save(manager, None, "encrypted")
    assert status["credentials"][SOURCE] == "encrypted"
    assert status["source_connections"][SOURCE]["status"] == "verification_required"
    for path in manager.profile_path.parent.iterdir():
        assert KEY.encode() not in path.read_bytes()
        assert PHRASE.encode() not in path.read_bytes()
    restarted = reopen(manager)
    assert restarted.status()["credentials"][SOURCE] == "locked"
    for body in [
        {"secret_storage": "encrypted"},
        {"secret_storage": "session", "api_key": NEXT_KEY},
        {"forget": True},
    ]:
        with pytest.raises(ConnectionError, match="[Uu]nlock"):
            restarted.configure_source(SOURCE, body)
    restarted.vault_action({"action": "unlock", "passphrase": PHRASE})
    assert restarted.get_secret(SOURCE) == KEY
    assert not restarted.status()["source_connections"][SOURCE]["selectable"]
    assert restarted.test(SOURCE)["status"] == "ok"
    save(restarted, None, "session")
    assert restarted.status()["credentials"][SOURCE] == "session"
    assert SOURCE not in json.loads(restarted.vault.path.read_text())["slots"]
    again = reopen(restarted)
    again.vault_action({"action": "unlock", "passphrase": PHRASE})
    assert again.get_secret(SOURCE) is None
    save(restarted, NEXT_KEY, "encrypted")
    restarted.configure_source(SOURCE, {"forget": True})
    final = reopen(restarted)
    final.vault_action({"action": "unlock", "passphrase": PHRASE})
    assert final.get_secret(SOURCE) is None


def test_source_save_cannot_reuse_a_probe_for_an_old_key(manager, monkeypatch):
    save(manager)

    def delayed_probe(key):
        save(manager, NEXT_KEY)
        save(manager, KEY)
        return {"records_checked": 1, "id_format": "legacy"}

    monkeypatch.setattr("labcat.science.sources.probe_connection", delayed_probe)
    assert manager.test(SOURCE)["status"] == "error"
    assert manager.materials_project_key("auto") is None


def test_failed_source_persistence_preserves_model_and_previous_vault(
    manager, monkeypatch
):
    manager.vault_action({"action": "create", "passphrase": PHRASE})
    manager.vault.update({"openai": MODEL_KEY}, [], "encrypted")
    save(manager, storage="encrypted")
    ciphertext = manager.vault.path.read_bytes()
    before = manager.status()

    def fail_write(*args):
        raise ConnectionError("Fixture write failed safely.")

    monkeypatch.setattr("labcat.credentials.atomic_write", fail_write)
    with pytest.raises(ConnectionError):
        save(manager, NEXT_KEY, "encrypted")
    assert manager.vault.path.read_bytes() == ciphertext
    assert manager.get_secret(SOURCE) == KEY
    assert manager.get_secret("openai") == MODEL_KEY
    assert manager.status()["profile"] == before["profile"]
    assert not manager.status()["using_local_defaults"]


@pytest.mark.parametrize(
    "body",
    [
        [],
        {},
        {"secret_storage": "plain", "api_key": KEY},
        {"secret_storage": "encrypted"},
        {"secret_storage": "session", "api_key": ""},
        {"secret_storage": "session", "api_key": {"value": KEY}},
        {"secret_storage": "session", "api_key": KEY, "profile": DEFAULT_PROFILE},
        {"forget": 1},
        {"forget": False},
        {"forget": True, "api_key": KEY},
    ],
)
def test_source_request_errors_do_not_echo_credentials_or_accept_extra_fields(
    manager, body
):
    app = FastAPI()
    app.include_router(create_connections_router(manager))
    with TestClient(app) as client:
        response = client.put("/api/connections/sources/materials_project", json=body)
        assert response.status_code == 422
        assert KEY not in response.text
        assert manager.get_secret(SOURCE) is None
        unknown = client.put(
            "/api/connections/sources/openai",
            json={"secret_storage": "session", "api_key": MODEL_KEY},
        )
        assert unknown.status_code == 422
        assert MODEL_KEY not in unknown.text
        assert manager.get_secret("openai") is None


def test_source_route_saves_then_verifies_and_redacts_every_response(manager):
    app = FastAPI()
    app.include_router(create_connections_router(manager))
    with TestClient(app) as client:
        response = client.put(
            "/api/connections/sources/materials_project",
            json={"api_key": KEY, "secret_storage": "session"},
        )
        assert response.status_code == 200
        assert not response.json()["source_connections"][SOURCE]["selectable"]
        assert KEY not in response.text
        result = client.post("/api/connections/test", json={"target": SOURCE})
        assert result.status_code == 200
        assert result.json()["status"] == "ok"
        assert not result.json()["inference_tested"]
        status = client.get("/api/connections")
        assert status.json()["source_connections"][SOURCE]["selectable"]
        assert KEY not in status.text + result.text
        response = client.put(
            "/api/connections/sources/materials_project", json={"forget": True}
        )
        assert response.status_code == 200
        assert response.json()["credentials"][SOURCE] == "missing"


def test_source_route_requires_same_origin_csrf_and_never_records_key_in_chats(
    tmp_path,
):
    from labcat.web import create_app

    app = create_app(workspace_path=tmp_path / "workspace.sqlite3")
    with TestClient(app, base_url="http://127.0.0.1:8123") as client:
        path = "/api/connections/sources/materials_project"
        token = client.get("/api/session").json()["csrf_token"]
        body = {"secret_storage": "session", "api_key": KEY}
        for headers in [
            {},
            {"X-CSRF-Token": "incorrect"},
            {"X-CSRF-Token": token, "Origin": "https://attacker.invalid"},
        ]:
            response = client.put(path, json=body, headers=headers)
            assert response.status_code == 403
            assert KEY not in response.text
            assert client.get("/api/connections").json()["credentials"][SOURCE] == (
                "missing"
            )
        headers = {"X-CSRF-Token": token, "Origin": "http://127.0.0.1:8123"}
        response = client.put(path, json=body, headers=headers)
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert KEY not in response.text
        assert client.get("/api/chats").json() == {"chats": []}
        for path in tmp_path.iterdir():
            if path.is_file():
                assert KEY.encode() not in path.read_bytes()
