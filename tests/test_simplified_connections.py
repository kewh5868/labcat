"""The simplified provider surface safely reads earlier local
settings."""

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_goose_worker import job

from labcat.cli import main
from labcat.connections import DEFAULT_PROFILE, PROVIDERS, ConnectionManager
from labcat.connections_api import create_connections_router
from labcat.credentials import ConnectionError
from labcat.goose_runtime import _environment
from labcat.goose_worker import WorkerError, _validate_job
from labcat.models import ModelError, plan_with_model


def legacy_profile(provider="openai"):
    return {
        **DEFAULT_PROFILE,
        "provider": provider,
        "model": "fixture-model",
        "allow_paid_inference": True,
        "aws_profile": "private-retired-profile",
        "aws_region": "us-west-2",
    }


def saved_manager(tmp_path, document):
    path = tmp_path / "workspace.sqlite3"
    profile_path = path.with_suffix(".connections.json")
    raw = json.dumps(document)
    profile_path.write_text(raw)
    manager = ConnectionManager(path)
    assert profile_path.read_text() == raw
    return manager


@pytest.mark.parametrize("version", [1, 2])
def test_saved_supported_profile_migrates_without_inference_or_storage_change(
    tmp_path, version
):
    old = legacy_profile()
    document = {"version": version, "profile": old}
    if version == 2:
        document.update(
            accounts=[{"id": "a" * 32, "label": "Work", "profile": old}],
            active_account_id="a" * 32,
        )
    manager = saved_manager(tmp_path, document)
    status = manager.status()
    assert status["profile"] == {key: old[key] for key in DEFAULT_PROFILE}
    assert not status["warnings"]
    assert not manager.setup.status()["can_research"]
    if version == 2:
        assert status["active_account_id"] == "a" * 32
        assert status["accounts"][0]["profile"] == status["profile"]
    assert "aws" not in json.dumps(status).lower()


@pytest.mark.parametrize("active_retired", [False, True])
def test_retired_saved_accounts_are_omitted_while_supported_account_survives(
    tmp_path, active_retired
):
    current = {"id": "a" * 32, "label": "Work", "profile": legacy_profile()}
    retired = {
        "id": "b" * 32,
        "label": "Private retired AWS connection",
        "profile": legacy_profile("bedrock"),
    }
    selected = retired if active_retired else current
    manager = saved_manager(
        tmp_path,
        {
            "version": 2,
            "profile": selected["profile"],
            "accounts": [current, retired],
            "active_account_id": selected["id"],
        },
    )
    status = manager.status()
    assert [account["id"] for account in status["accounts"]] == [current["id"]]
    assert status["active_account_id"] == (None if active_retired else current["id"])
    assert status["profile"]["provider"] == ("none" if active_retired else "openai")
    assert status["warnings"]
    assert "aws" not in json.dumps(status).lower()
    assert "bedrock" not in json.dumps(status).lower()
    assert not manager.setup.status()["can_research"]
    manager.select_account(current["id"])
    persisted = json.loads(manager.profile_path.read_text())
    assert persisted["profile"]["provider"] == "openai"
    assert set(persisted["profile"]) == set(DEFAULT_PROFILE)
    assert len(persisted["accounts"]) == 1


def test_retired_direct_profile_requires_a_new_connection(tmp_path):
    manager = saved_manager(
        tmp_path, {"version": 1, "profile": legacy_profile("bedrock")}
    )
    assert manager.status()["profile"] == DEFAULT_PROFILE
    assert manager.status()["warnings"]
    assert manager.setup.status()["model"]["status"] == "not_connected"


def test_migration_still_rejects_mismatched_selected_account(tmp_path):
    manager = saved_manager(
        tmp_path,
        {
            "version": 2,
            "profile": legacy_profile(),
            "accounts": [
                {"id": "a" * 32, "label": "Work", "profile": legacy_profile("bedrock")}
            ],
            "active_account_id": "a" * 32,
        },
    )
    assert manager.status()["profile"] == DEFAULT_PROFILE
    assert manager.status()["accounts"] == []
    assert manager.status()["warnings"]


def test_retired_provider_routes_and_new_profile_submissions_are_unavailable(tmp_path):
    manager = ConnectionManager(tmp_path / "workspace.sqlite3")
    app = FastAPI()
    app.include_router(create_connections_router(manager))
    with TestClient(app) as client:
        assert client.get("/api/connections/aws-profiles").status_code == 404
        response = client.post("/api/connections/test", json={"target": "aws"})
        assert response.status_code == 422
        for profile in (legacy_profile(), {**DEFAULT_PROFILE, "provider": "bedrock"}):
            response = client.put(
                "/api/connections",
                json={"profile": profile, "secret_storage": "session"},
            )
            assert response.status_code == 422
    assert "bedrock" not in PROVIDERS
    assert not manager.profile_path.exists()


def test_retired_setup_step_migrates_without_granting_readiness(tmp_path):
    path = tmp_path / "workspace.sqlite3"
    path.with_suffix(".setup.json").write_text(
        json.dumps({"version": 1, "completed": False, "current_step": "compute"})
    )
    manager = ConnectionManager(path)
    state = manager.setup.status()
    assert state["current_step"] == "sources"
    assert state["optional"] == {"data_apis_required": False}
    assert not state["can_research"]
    with pytest.raises(ConnectionError):
        manager.setup.save_progress({"current_step": "compute"})


def test_retired_provider_cannot_execute_in_model_or_worker(tmp_path, monkeypatch):
    profile = {**DEFAULT_PROFILE, "provider": "bedrock", "model": "fixture-model"}
    monkeypatch.setattr(
        "labcat.models.request_json", lambda *a, **k: pytest.fail("Network reached")
    )
    with pytest.raises(ModelError, match="not supported"):
        plan_with_model(profile, None, "Find oxides")
    with pytest.raises(ModelError, match="not supported"):
        _environment(profile, None, tmp_path, "http://127.0.0.1:1", "token", None)
    with pytest.raises(ConnectionError, match="supported model provider"):
        _validate_job({**job(), "profile": profile})
    with pytest.raises(WorkerError, match="shape"):
        _validate_job({**job(), "aws_credentials": {"AWS_ACCESS_KEY_ID": "fixture"}})


def test_cli_help_has_no_retired_command(capsys):
    with pytest.raises(SystemExit) as stopped:
        main(["--help"])
    assert stopped.value.code == 0
    assert "aws" not in capsys.readouterr().out.lower()
    with pytest.raises(SystemExit) as stopped:
        main(["aws-check"])
    assert stopped.value.code == 2
