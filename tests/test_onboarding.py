"""Required sign-in is enforced independently of UI and saved setup
progress."""

import json

import pytest
from fastapi.testclient import TestClient

from labcat.config import load_config
from labcat.connections import DEFAULT_PROFILE, ConnectionManager
from labcat.credentials import ConnectionError
from labcat.models import ModelError
from labcat.onboarding import SetupRequired
from labcat.research import research
from labcat.web import create_app


def test_first_setup_and_progress_have_no_authority(tmp_path):
    path = tmp_path / "workspace.sqlite3"
    manager = ConnectionManager(path)
    state = manager.setup.status()
    assert state["required"] and not state["completed"]
    assert not state["can_research"]
    assert state["model"]["status"] == "not_connected"
    manager.setup.save_progress({"current_step": "sources"})
    reopened = ConnectionManager(path)
    assert reopened.setup.status()["current_step"] == "sources"
    with pytest.raises(SetupRequired):
        reopened.setup.complete()
    with pytest.raises(ConnectionError):
        reopened.setup.save_progress({"current_step": "review", "completed": True})


@pytest.mark.parametrize("provider", ["none", "ollama"])
def test_no_model_and_unauthenticated_local_provider_cannot_research(
    tmp_path, provider
):
    manager = ConnectionManager(tmp_path / "w.sqlite3")
    manager.configure(
        {
            "profile": {**DEFAULT_PROFILE, "provider": provider, "model": "local"},
            "secret_storage": "session",
        }
    )
    with pytest.raises(SetupRequired, match="Connect"):
        research("Find useful materials", load_config(), connections=manager)


def test_missing_manager_cannot_research_or_contact_sources(monkeypatch):
    monkeypatch.setattr(
        "labcat.science.run_research",
        lambda *a, **k: pytest.fail("Source retrieval ran without an account"),
    )
    with pytest.raises(SetupRequired, match="--connections"):
        research("Find useful materials", load_config())


def test_metadata_verification_is_not_persisted_authorization(
    tmp_path, authenticated_model_factory
):
    path = tmp_path / "w.sqlite3"
    manager = authenticated_model_factory(path)
    assert manager.setup.status()["model"]["status"] == "verification_required"
    complete = manager.setup.complete()
    assert complete["completed"] and complete["can_research"]
    assert complete["model"]["checked_at"]
    document = json.loads(manager.setup.path.read_text())
    assert document == {"version": 1, "completed": True, "current_step": "review"}
    reopened = ConnectionManager(path)
    assert reopened.setup.status()["completed"]
    assert not reopened.setup.status()["can_research"]
    assert "fixture-never-a-live-credential" not in manager.setup.path.read_text()


def test_locked_vault_rechecks_after_unlock(tmp_path, authenticated_model_factory):
    manager = authenticated_model_factory(tmp_path / "w.sqlite3")
    manager.vault_action({"action": "create", "passphrase": "fixture passphrase only"})
    manager.configure(
        {
            "profile": manager.status()["profile"],
            "secret_storage": "encrypted",
            "secrets": {"openai": "fixture-encrypted-credential"},
        }
    )
    assert manager.setup.complete()["can_research"]
    manager.vault_action({"action": "lock"})
    assert manager.setup.status()["model"]["status"] == "credentials_locked"
    with pytest.raises(SetupRequired, match="Unlock"):
        manager.setup.require_ready()
    manager.vault_action({"action": "unlock", "passphrase": "fixture passphrase only"})
    assert manager.setup.require_ready()["can_research"]


@pytest.mark.parametrize(
    ("change", "status"),
    [
        ({"model": ""}, "model_required"),
        ({"allow_paid_inference": False}, "consent_required"),
    ],
)
def test_incomplete_model_profile_does_not_verify(
    tmp_path, authenticated_model_factory, change, status
):
    manager = authenticated_model_factory(tmp_path / "w.sqlite3")
    assert manager.setup.verify()["can_research"]
    manager.configure(
        {
            "profile": {**manager.status()["profile"], **change},
            "secret_storage": "session",
        }
    )
    assert manager.setup.verify()["model"]["status"] == status
    with pytest.raises(SetupRequired):
        manager.setup.complete()


def test_changed_key_and_expired_verification_are_rechecked(
    tmp_path, monkeypatch, authenticated_model_factory
):
    manager = authenticated_model_factory(tmp_path / "w.sqlite3")
    assert manager.setup.verify()["can_research"]
    manager.setup._verified["expires"] = 0
    assert manager.setup.status()["model"]["status"] == "verification_required"
    assert manager.setup.require_ready()["can_research"]
    manager.vault.update({"openai": "fixture-replacement-invalid-key"}, [], "session")
    monkeypatch.setattr(
        "labcat.connections.request_json",
        lambda *args, **kwargs: {"data": []},
    )
    with pytest.raises(SetupRequired, match="not in the returned listing"):
        manager.setup.require_ready()
    assert not manager.setup.status()["can_research"]


def test_provider_metadata_error_does_not_authorize_or_leak_credentials(
    tmp_path, monkeypatch, authenticated_model_factory
):
    manager = authenticated_model_factory(tmp_path / "w.sqlite3")

    def failed(*args, **kwargs):
        raise ModelError("Provider metadata request failed.")

    monkeypatch.setattr("labcat.connections.request_json", failed)
    assert manager.setup.verify()["model"]["status"] == "error"
    with pytest.raises(SetupRequired):
        manager.setup.complete()


def test_bedrock_requires_account_authentication_and_selected_model_catalog(
    tmp_path, monkeypatch
):
    manager = ConnectionManager(tmp_path / "w.sqlite3")
    manager.configure(
        {
            "profile": {
                **DEFAULT_PROFILE,
                "provider": "bedrock",
                "model": "fixture-bedrock-model",
                "allow_paid_inference": True,
            },
            "secret_storage": "session",
        }
    )
    checks = []
    monkeypatch.setattr(
        "labcat.connections.check_connection", lambda *args: checks.append("sts")
    )
    monkeypatch.setattr("labcat.aws.model_options", lambda *args: [])
    assert not manager.setup.verify()["can_research"]
    monkeypatch.setattr(
        "labcat.aws.model_options",
        lambda *args: [{"id": "fixture-bedrock-model", "label": "Fixture"}],
    )
    assert manager.setup.verify()["can_research"]
    assert checks == ["sts", "sts"]


def test_existing_chatgpt_account_requires_provider_verified_metadata(
    tmp_path, monkeypatch
):
    from test_agent_connections import Broker, auth_fixture

    from labcat.agent_connections import _pack

    monkeypatch.setenv("LABCAT_AGENT_ENGINE", "goose")
    manager = ConnectionManager(tmp_path / "w.sqlite3")
    identifier = manager.save_account(
        {
            "label": "Fixture ChatGPT",
            "profile": {
                **DEFAULT_PROFILE,
                "provider": "chatgpt",
                "model": "test-model",
                "allow_paid_inference": True,
            },
            "secret_storage": "session",
        }
    )["active_account_id"]
    manager.vault.update({"oauth_" + identifier: _pack(auth_fixture())}, [], "session")
    manager.agent._auth = Broker()
    assert manager.setup.verify()["can_research"]
    manager.agent.forget_login(identifier)
    assert not manager.setup.status()["can_research"]
    with pytest.raises(SetupRequired):
        manager.setup.require_ready()


@pytest.mark.parametrize("engine", ["direct", "goose"])
def test_failed_inference_never_falls_back_to_retrieval(
    tmp_path, monkeypatch, authenticated_model_factory, engine
):
    monkeypatch.setenv("LABCAT_AGENT_ENGINE", engine)
    manager = authenticated_model_factory(tmp_path / "w.sqlite3")

    def failed(*args, **kwargs):
        raise ModelError("Test provider failure")

    monkeypatch.setattr(manager, "plan", failed)
    monkeypatch.setattr(manager.agent, "run", failed)
    monkeypatch.setattr(
        "labcat.science.run_research",
        lambda *a, **k: pytest.fail("Failed model fell back to source retrieval"),
    )
    with pytest.raises(ModelError, match="No report was saved"):
        research(
            "Find public oxide material evidence", load_config(), connections=manager
        )
    assert not manager.setup.status()["can_research"]


def test_api_blocks_research_but_keeps_projects_and_settings_available(tmp_path):
    with TestClient(
        create_app(workspace_path=tmp_path / "w.sqlite3"), base_url="http://localhost"
    ) as client:
        chat = client.post("/api/chats", json={"title": "Keep draft"}).json()
        denied = client.post(
            f"/api/chats/{chat['id']}/messages", json={"content": "Find materials"}
        )
        assert denied.status_code == 409
        assert denied.json()["detail"]["code"] == "model_setup_required"
        assert client.get(f"/api/chats/{chat['id']}").json()["messages"] == []
        for route in ("/api/projects", "/api/settings", "/api/public-sources"):
            assert client.get(route).status_code == 200
        assert (
            client.post(
                "/api/public-sources/search",
                json={"query": "materials", "sources": ["arxiv"]},
            ).status_code
            == 409
        )
        assert (
            client.post("/api/connections/setup/complete", json={}).status_code == 403
        )
        token = client.get("/api/session").json()["csrf_token"]
        assert (
            client.post(
                "/api/connections/setup/complete",
                json={},
                headers={"X-CSRF-Token": token},
            ).status_code
            == 422
        )
        assert client.get("/api/connections/setup").json()["can_research"] is False


def test_stateless_research_uses_current_connection_and_creates_no_chats(
    tmp_path, authenticated_app_models
):
    app = create_app(workspace_path=tmp_path / "w.sqlite3")
    with TestClient(app, base_url="http://localhost") as client:
        assert (
            client.post("/api/research", json={"prompt": "Find materials"}).status_code
            == 403
        )
        token = client.get("/api/session").json()["csrf_token"]
        response = client.post(
            "/api/research",
            json={"prompt": "Find polymers"},
            headers={"X-CSRF-Token": token},
        )
        assert response.status_code == 200, response.text
        assert response.json()["result"]["execution"]["provider"] == "openai"
        assert client.get("/api/chats").json()["chats"] == []
