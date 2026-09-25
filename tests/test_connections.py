"""Connection and credential tests use synthetic secrets and no live
accounts."""

import json
import os

import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.testclient import TestClient

from labcat.connections import DEFAULT_PROFILE, ConnectionManager
from labcat.connections_api import create_connections_router
from labcat.credentials import ConnectionError
from labcat.onboarding import SetupRequired

SECRET = "synthetic-test-secret-do-not-use"
PHRASE = "synthetic vault passphrase only"


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    monkeypatch.delenv("LABCAT_VAULT_KEY", raising=False)
    monkeypatch.delenv("LABCAT_VAULT_KEY_FILE", raising=False)


@pytest.fixture
def manager(tmp_path):
    return ConnectionManager(tmp_path / "workspace.sqlite3")


def configured(manager, provider="openai", storage="session", **extra):
    return manager.configure(
        {
            "profile": {**DEFAULT_PROFILE, "provider": provider, "model": "test-model"},
            "secret_storage": storage,
            "secrets": {"openai": SECRET},
            **extra,
        }
    )


def restart(manager):
    return ConnectionManager(
        manager.profile_path.with_suffix("").with_suffix(".sqlite3")
    )


def test_initial_settings_need_no_credentials_but_planning_requires_login(
    manager, monkeypatch
):
    monkeypatch.setattr(
        "labcat.models.request_json", lambda *a, **k: pytest.fail("network")
    )
    status = manager.status()
    assert status["configured"] is False
    assert status["profile"] == DEFAULT_PROFILE
    assert set(status["credentials"].values()) == {"missing"}
    with pytest.raises(SetupRequired):
        manager.plan("Claim a magic material property")
    assert manager.test("model")["inference_tested"] is False


def test_session_keys_never_persist_but_profile_survives(manager):
    status = configured(manager)
    assert status["credentials"]["openai"] == "session"
    assert SECRET not in json.dumps(status)
    assert manager.get_secret("openai") == SECRET
    for path in manager.profile_path.parent.iterdir():
        assert SECRET.encode() not in path.read_bytes()
    reopened = restart(manager)
    assert reopened.status()["profile"]["provider"] == "openai"
    assert reopened.get_secret("openai") is None
    if os.name == "posix":
        assert manager.profile_path.stat().st_mode & 0o777 == 0o600


def test_passphrase_vault_restart_lock_unlock_and_ciphertext_only(manager):
    manager.vault_action({"action": "create", "passphrase": PHRASE})
    configured(manager, storage="encrypted")
    assert manager.status()["credentials"]["openai"] == "encrypted"
    for path in manager.profile_path.parent.iterdir():
        assert SECRET.encode() not in path.read_bytes()
        assert PHRASE.encode() not in path.read_bytes()
    assert len(list(manager.profile_path.parent.iterdir())) == 2
    reopened = restart(manager)
    assert reopened.status()["vault"]["locked"] is True
    assert reopened.get_secret("openai") is None
    with pytest.raises(ConnectionError, match="unlocked"):
        reopened.vault_action(
            {"action": "unlock", "passphrase": "wrong long passphrase"}
        )
    assert reopened.get_secret("openai") is None
    reopened.vault_action({"action": "unlock", "passphrase": PHRASE})
    assert reopened.get_secret("openai") == SECRET
    reopened.vault_action({"action": "lock"})
    assert reopened.get_secret("openai") is None


def test_encrypted_save_requires_a_ready_vault(manager):
    with pytest.raises(ConnectionError, match="vault"):
        configured(manager, storage="encrypted")
    assert not manager.profile_path.exists()
    assert manager.get_secret("openai") is None


def test_external_key_restores_saved_credentials_and_wrong_key_stays_locked(
    manager, monkeypatch
):
    monkeypatch.setenv("LABCAT_VAULT_KEY", Fernet.generate_key().decode())
    external = restart(manager)
    configured(external, storage="encrypted")
    assert restart(external).get_secret("openai") == SECRET
    monkeypatch.setenv("LABCAT_VAULT_KEY", Fernet.generate_key().decode())
    bad = restart(external)
    assert bad.get_secret("openai") is None
    assert bad.status()["vault"]["locked"] is True
    assert bad.status()["warnings"]


def test_external_key_file_never_copied_into_application_storage(
    manager, monkeypatch, tmp_path
):
    key_file = tmp_path / "deployment-secret"
    key = Fernet.generate_key()
    key_file.write_bytes(key)
    monkeypatch.setenv("LABCAT_VAULT_KEY_FILE", str(key_file))
    external = restart(manager)
    configured(external, storage="encrypted")
    assert external.status()["vault"]["key_source"] == "file"
    assert key not in external.vault.path.read_bytes()
    assert key not in external.profile_path.read_bytes()


def test_tampered_vault_fails_closed_without_destroying_it(manager):
    manager.vault_action({"action": "create", "passphrase": PHRASE})
    configured(manager, storage="encrypted")
    document = json.loads(manager.vault.path.read_text())
    document["token"] = document["token"][:-20] + "A" * 20
    manager.vault.path.write_text(json.dumps(document))
    reopened = restart(manager)
    with pytest.raises(ConnectionError):
        reopened.vault_action({"action": "unlock", "passphrase": PHRASE})
    assert reopened.get_secret("openai") is None
    assert json.loads(manager.vault.path.read_text()) == document


def test_lock_also_forgets_session_credentials_and_reset_requires_confirmation(manager):
    manager.vault_action({"action": "create", "passphrase": PHRASE})
    configured(manager)
    manager.vault_action({"action": "lock"})
    assert manager.get_secret("openai") is None
    with pytest.raises(ConnectionError):
        manager.vault_action({"action": "reset"})
    manager.vault_action({"action": "reset", "confirm": True})
    assert manager.status()["profile"]["provider"] == "openai"
    assert not manager.vault.path.exists()


def test_forget_saved_secret_is_explicit_and_survives_restart(manager):
    manager.vault_action({"action": "create", "passphrase": PHRASE})
    configured(manager, storage="encrypted")
    manager.configure(
        {
            "profile": dict(DEFAULT_PROFILE),
            "secret_storage": "session",
            "forget_secrets": ["openai"],
        }
    )
    reopened = restart(manager)
    reopened.vault_action({"action": "unlock", "passphrase": PHRASE})
    assert reopened.get_secret("openai") is None


def test_local_override_is_session_only_and_saved_defaults_are_explicit(manager):
    configured(manager)
    assert manager.local_defaults(False)["using_local_defaults"] is True
    assert manager.status()["profile"]["provider"] == "none"
    assert restart(manager).status()["profile"]["provider"] == "openai"
    manager.local_defaults(True)
    assert restart(manager).status()["profile"]["provider"] == "none"
    assert manager.get_secret("openai") == SECRET


def test_corrupt_profile_recovers_to_local_without_silently_overwriting(manager):
    manager.profile_path.write_text("{broken")
    recovered = restart(manager)
    assert recovered.status()["profile"]["provider"] == "none"
    assert recovered.status()["warnings"]
    assert manager.profile_path.read_text() == "{broken"


@pytest.mark.parametrize(
    "change",
    [
        {"provider": "shell"},
        {"allow_paid_inference": "yes"},
        {"ollama_url": "http://169.254.169.254:11434"},
        {"ollama_url": "https://example.org"},
        {"model": "model\nsecret"},
        {"aws_profile": "../../private"},
        {"aws_region": "https://evil"},
        {"provider": "ollama", "model": "model:cloud"},
        {"private_sources": True},
    ],
)
def test_invalid_profile_is_rejected_before_secret_persistence(manager, change):
    with pytest.raises(ConnectionError):
        manager.configure(
            {
                "profile": {**DEFAULT_PROFILE, **change},
                "secret_storage": "session",
                "secrets": {"openai": SECRET},
            }
        )
    assert manager.get_secret("openai") is None
    assert not manager.profile_path.exists()


def test_symbolic_storage_file_is_rejected_without_overwriting_target(
    manager, tmp_path
):
    target = tmp_path / "untouched"
    target.write_text("original")
    try:
        manager.profile_path.symlink_to(target)
    except OSError:
        pytest.skip("Host does not permit unprivileged symlinks")
    with pytest.raises(ConnectionError):
        manager.local_defaults(True)
    assert target.read_text() == "original"


def test_materials_project_check_uses_fixed_public_endpoint_and_no_inference(
    manager, monkeypatch
):
    manager.configure(
        {
            "profile": dict(DEFAULT_PROFILE),
            "secret_storage": "session",
            "secrets": {"materials_project": SECRET},
        }
    )
    calls = []

    def probe(secret):
        calls.append(secret)
        return {"records_checked": 1, "id_format": "legacy"}

    monkeypatch.setattr("labcat.science.sources.probe_connection", probe)
    monkeypatch.setattr(
        "labcat.connections.request_json",
        lambda *args, **kwargs: pytest.fail("Used a different provider transport"),
    )
    result = manager.test("materials_project")
    assert result["status"] == "ok"
    assert result["billable"] is False
    assert result["inference_tested"] is False
    assert SECRET not in json.dumps(result)
    assert calls == [SECRET]
    assert SECRET not in manager.profile_path.read_text()


def test_materials_project_probe_reports_safe_http_failure_and_keeps_session_key(
    manager, monkeypatch
):
    from labcat.science.sources import SourceError

    manager.configure(
        {
            "profile": dict(DEFAULT_PROFILE),
            "secret_storage": "session",
            "secrets": {"materials_project": SECRET},
        }
    )

    def rejected(secret):
        raise SourceError(
            "Materials Project returned HTTP 403; no response text or "
            "credentials retained."
        )

    monkeypatch.setattr("labcat.science.sources.probe_connection", rejected)
    result = manager.test("materials_project")
    assert result["status"] == "error"
    assert "HTTP 403" in result["message"]
    assert SECRET not in json.dumps(result)
    assert SECRET not in manager.profile_path.read_text()
    assert manager.get_secret("materials_project") == SECRET


def test_model_check_is_metadata_only_even_when_paid_consent_is_false(
    manager, monkeypatch
):
    configured(manager)
    calls = []

    def http(url, **kwargs):
        calls.append((url, kwargs))
        return {"data": [{"id": "test-model"}]}

    monkeypatch.setattr("labcat.connections.request_json", http)
    result = manager.test("model")
    assert result["status"] == "ok"
    assert result["inference_tested"] is False
    assert calls[0][0] == "https://api.openai.com/v1/models"
    assert "body" not in calls[0][1]
    with pytest.raises(SetupRequired, match="Allow"):
        manager.plan("Find oxide candidates")


def test_anthropic_verification_uses_the_same_catalog_page_as_model_selection(
    manager, monkeypatch
):
    selected = "fixture-model-outside-default-page"
    manager.configure(
        {
            "profile": {
                **DEFAULT_PROFILE,
                "provider": "anthropic",
                "model": selected,
                "allow_paid_inference": True,
            },
            "secret_storage": "session",
            "secrets": {"anthropic": SECRET},
        }
    )
    calls = []

    def catalog(url, **kwargs):
        calls.append((url, kwargs))
        # Simulate an authorized model outside the provider's default page.
        return {
            "data": [{"id": "fixture-default-model"}]
            + ([{"id": selected}] if url.endswith("?limit=100") else [])
        }

    monkeypatch.setattr("labcat.connections.request_json", catalog)
    assert selected in {model["id"] for model in manager.list_models()["models"]}
    assert manager.setup.verify()["can_research"]
    assert [url for url, _ in calls] == [
        "https://api.anthropic.com/v1/models?limit=100",
        "https://api.anthropic.com/v1/models?limit=100",
    ]
    assert all("body" not in kwargs for _, kwargs in calls)


def test_aws_check_returns_no_identity_and_does_not_prove_bedrock_access(
    manager, monkeypatch
):
    monkeypatch.setattr(
        "labcat.connections.check_connection",
        lambda *a: {"Arn": "SECRET_PRINCIPAL"},
    )
    result = manager.test("aws")
    assert result["status"] == "ok"
    assert "not been tested" in result["message"]
    assert "SECRET_PRINCIPAL" not in json.dumps(result)


def test_bedrock_mantle_readiness_rejects_unsupported_route_before_network(
    manager, monkeypatch
):
    configured(
        manager,
        profile={
            **DEFAULT_PROFILE,
            "provider": "bedrock",
            "model": "openai.gpt-5.5-high",
        },
    )
    monkeypatch.setattr(
        "labcat.connections.check_connection",
        lambda *a: pytest.fail("Unsupported route reached AWS"),
    )
    result = manager.test("model")
    assert result["status"] == "error"
    assert "Mantle bearer-token" in result["message"]
    assert result["inference_tested"] is False


def test_connection_routes_never_reflect_secret_input_in_validation_errors(manager):
    app = FastAPI()
    app.include_router(create_connections_router(manager))
    client = TestClient(app)
    for body in (
        {"profile": {"secret": SECRET}},
        {
            "profile": DEFAULT_PROFILE,
            "secret_storage": "session",
            "secrets": {"unknown": SECRET},
        },
        {
            "profile": DEFAULT_PROFILE,
            "secret_storage": "session",
            "secrets": {"openai": "SECRET\nHEADER"},
        },
    ):
        response = client.put("/api/connections", json=body)
        assert response.status_code == 422
        assert SECRET not in response.text
        assert "SECRET\\nHEADER" not in response.text
    response = client.put("/api/connections", content=b"x" * 24001)
    assert response.status_code == 413
    assert (
        client.post("/api/connections/vault", json={"action": "reset"}).status_code
        == 422
    )
    assert client.get("/api/connections").json()["profile"] == DEFAULT_PROFILE


def test_reset_clears_session_api_and_oauth_credentials_without_prior_lock(manager):
    manager.vault_action({"action": "create", "passphrase": PHRASE})
    configured(manager, storage="encrypted")
    oauth_slot = "oauth_" + "1" * 32
    manager.vault.update(
        {"kimi": "session-api-fixture", oauth_slot: "c2Vzc2lvbi1vYXV0aC1maXh0dXJl"},
        [],
        "session",
    )
    assert manager.vault.get(oauth_slot) is not None
    manager.vault_action({"action": "reset", "confirm": True})
    assert manager.vault.get(oauth_slot) is None
    assert manager.get_secret("kimi") is None
    assert manager.get_secret("openai") is None
    assert not manager.vault.session
    assert not manager.vault.path.exists()
    assert manager.status()["profile"]["provider"] == "openai"
    assert restart(manager).get_secret(oauth_slot) is None
