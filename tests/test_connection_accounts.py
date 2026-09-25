"""Named connections retain keys privately and select the intended
provider/model."""

import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from labcat import aws
from labcat.connections import DEFAULT_PROFILE, ConnectionManager
from labcat.credentials import ConnectionError
from labcat.web import create_app


def account(
    manager,
    label="Work",
    key="test-key-account-one",
    model="test-model",
    storage="session",
):
    return manager.save_account(
        {
            "label": label,
            "profile": {
                **DEFAULT_PROFILE,
                "provider": "openai",
                "model": model,
                "allow_paid_inference": True,
            },
            "secret_storage": storage,
            "api_key": key,
        }
    )


def test_named_accounts_switch_correct_keys_and_models_without_plaintext(
    tmp_path, monkeypatch
):
    manager = ConnectionManager(tmp_path / "workspace.sqlite3")
    one = account(manager)["active_account_id"]
    two = account(manager, "Personal", "test-key-account-two", "other-model")[
        "active_account_id"
    ]
    seen = []
    monkeypatch.setattr(
        "labcat.connections.request_json",
        lambda *args, **kwargs: {"data": [{"id": "test-model"}, {"id": "other-model"}]},
    )
    monkeypatch.setattr(
        "labcat.connections.plan_with_model",
        lambda profile, secret, prompt, context=None: seen.append(
            (profile["model"], secret)
        ),
    )
    manager.select_account(one)
    manager.plan("Find oxides")
    manager.select_account(two)
    manager.plan("Find oxides")
    assert seen == [
        ("test-model", "test-key-account-one"),
        ("other-model", "test-key-account-two"),
    ]
    status = manager.status()
    assert len(status["accounts"]) == 2 and status["credentials"]["openai"] == "session"
    for text in [
        json.dumps(status),
        *(path.read_text() for path in tmp_path.iterdir()),
    ]:
        assert "test-key-account-" not in text
    restarted = ConnectionManager(tmp_path / "workspace.sqlite3")
    assert restarted.status()["active_account_id"] == two
    assert restarted.status()["profile"]["model"] == "other-model"
    assert {a["credential_state"] for a in restarted.status()["accounts"]} == {
        "missing"
    }


def test_named_encrypted_accounts_survive_locked_restart(tmp_path, monkeypatch):
    manager = ConnectionManager(tmp_path / "workspace.sqlite3")
    phrase = "test-only-long-passphrase"
    manager.vault_action({"action": "create", "passphrase": phrase})
    identifier = account(manager, storage="encrypted")["active_account_id"]
    restarted = ConnectionManager(tmp_path / "workspace.sqlite3")
    assert restarted.status()["accounts"][0]["credential_state"] == "locked"
    assert restarted.status()["credentials"]["openai"] == "locked"
    restarted.vault_action({"action": "unlock", "passphrase": phrase})
    assert restarted.status()["accounts"][0]["credential_state"] == "encrypted"
    assert restarted.vault.get("account_" + identifier) == "test-key-account-one"
    for path in tmp_path.iterdir():
        assert phrase.encode() not in path.read_bytes()
        assert b"test-key-account-one" not in path.read_bytes()
    restarted.local_defaults(True)
    again = ConnectionManager(tmp_path / "workspace.sqlite3")
    assert again.status()["profile"]["provider"] == "none"
    assert len(again.status()["accounts"]) == 1


def test_legacy_profile_load_and_selected_account_edits(tmp_path):
    path = tmp_path / "workspace.sqlite3"
    manager = ConnectionManager(path)
    manager.profile_path.write_text(
        json.dumps({"version": 1, "profile": DEFAULT_PROFILE})
    )
    manager = ConnectionManager(path)
    identifier = account(manager)["active_account_id"]
    status = manager.configure(
        {
            "profile": {**manager.status()["profile"], "model": "next-model"},
            "secret_storage": "session",
            "secrets": {"openai": "replacement-test-key"},
        }
    )
    assert status["active_account_id"] == identifier
    assert status["accounts"][0]["profile"]["model"] == "next-model"
    assert manager.vault.get("account_" + identifier) == "replacement-test-key"
    assert manager.vault.get("openai") is None
    manager.configure({"profile": DEFAULT_PROFILE, "secret_storage": "session"})
    assert manager.status()["active_account_id"] is None
    assert manager.status()["accounts"][0]["profile"]["model"] == "next-model"


def test_model_catalog_uses_selected_key_without_inference(tmp_path, monkeypatch):
    manager = ConnectionManager(tmp_path / "workspace.sqlite3")
    account(manager, model="")
    captured = []

    def listing(url, **kwargs):
        captured.append((url, kwargs))
        return {
            "data": [
                {"id": "valid-model", "secret_metadata": "discard"},
                {"id": "https://evil.example/?key=secret"},
                {"id": None},
            ]
        }

    monkeypatch.setattr("labcat.connections.request_json", listing)
    monkeypatch.setattr(
        "labcat.connections.plan_with_model",
        lambda *a, **k: pytest.fail("Inference attempted"),
    )
    result = manager.list_models()
    assert result["models"] == [{"id": "valid-model", "label": "valid-model"}]
    assert result["inference_tested"] is False
    assert captured[0][0] == "https://api.openai.com/v1/models"
    assert captured[0][1]["headers"]["Authorization"] == "Bearer test-key-account-one"
    assert "discard" not in json.dumps(result)


@pytest.mark.parametrize(
    "change",
    [
        {"label": "\ninvalid"},
        {"secret_storage": []},
        {"api_key": "bad whitespace key"},
        {"unexpected": "secret"},
    ],
)
def test_invalid_account_never_writes_secrets(tmp_path, change):
    manager = ConnectionManager(tmp_path / "workspace.sqlite3")
    body = {
        "label": "Work",
        "profile": {**DEFAULT_PROFILE, "provider": "openai"},
        "secret_storage": "session",
        "api_key": "test-key-account-one",
        **change,
    }
    with pytest.raises(ConnectionError):
        manager.save_account(body)
    assert not manager.profile_path.exists()
    assert not manager.vault.session


def test_account_provider_cannot_change_and_raw_slots_rejected(tmp_path):
    manager = ConnectionManager(tmp_path / "workspace.sqlite3")
    identifier = account(manager)["active_account_id"]
    with pytest.raises(ConnectionError):
        manager.save_account(
            {
                "label": "Changed",
                "profile": {**DEFAULT_PROFILE, "provider": "anthropic"},
                "secret_storage": "session",
            },
            identifier,
        )
    with pytest.raises(ConnectionError):
        manager.configure(
            {
                "profile": manager.status()["profile"],
                "secret_storage": "session",
                "secrets": {"account_" + identifier: "injected-test-key"},
            }
        )
    assert manager.vault.get("account_" + identifier) == "test-key-account-one"


def test_account_api_requires_csrf_and_does_not_echo_secret(tmp_path):
    with TestClient(
        create_app(workspace_path=tmp_path / "workspace.sqlite3"),
        base_url="http://127.0.0.1",
    ) as client:
        payload = {
            "label": "Test",
            "profile": {**DEFAULT_PROFILE, "provider": "openai"},
            "secret_storage": "session",
            "api_key": "test-key-api-only",
        }
        assert client.post("/api/connections/accounts", json=payload).status_code == 403
        token = client.get("/api/session").json()["csrf_token"]
        response = client.post(
            "/api/connections/accounts", json=payload, headers={"x-csrf-token": token}
        )
        assert response.status_code == 200 and "test-key-api-only" not in response.text
        about = client.get("/api/about").json()
        assert about["developer"] == "Keith White" and about["github_url"] is None


def test_aws_profile_options_only_reads_profile_names(monkeypatch):
    import boto3

    session = SimpleNamespace(
        available_profiles=["work", "../../invalid"],
        get_available_regions=lambda service: ["us-west-2"],
    )
    monkeypatch.setattr(boto3, "Session", lambda: session)
    result = aws.profile_options()
    assert result["profiles"] == ["work"] and result["regions"] == ["us-west-2"]
    assert "Do not mount host folders" in result["setup"]["message"]


def test_status_profiles_are_detached_from_live_consent_and_account_state(tmp_path):
    manager = ConnectionManager(tmp_path / "workspace.sqlite3")
    identifier = account(manager)["active_account_id"]
    returned = manager.status()
    returned["accounts"][0]["profile"]["allow_paid_inference"] = False
    returned["accounts"][0]["profile"]["model"] = "mutated-model"
    manager.select_account(identifier)
    assert manager.status()["profile"]["model"] == "test-model"
    assert manager.status()["profile"]["allow_paid_inference"] is True


def test_new_account_without_key_never_copies_another_accounts_credential(tmp_path):
    manager = ConnectionManager(tmp_path / "workspace.sqlite3")
    first = account(manager)["active_account_id"]
    second = account(manager, label="Another account", key="")["active_account_id"]
    assert first != second
    assert manager.status()["credentials"]["openai"] == "missing"
    assert manager.vault.get("account_" + second) is None
    assert manager.vault.get("account_" + first) == "test-key-account-one"
    manager.save_account(
        {
            "label": "First renamed",
            "profile": manager.status()["accounts"][0]["profile"],
            "secret_storage": "session",
            "api_key": "",
        },
        first,
    )
    assert manager.vault.get("account_" + first) == "test-key-account-one"


@pytest.mark.parametrize("storage", ["session", "encrypted"])
def test_failed_profile_commit_rolls_back_keys_and_forces_local_after_restart(
    tmp_path, monkeypatch, storage
):
    manager = ConnectionManager(tmp_path / "workspace.sqlite3")
    phrase = "test-only-rollback-passphrase"
    if storage == "encrypted":
        manager.vault.create(phrase)
    identifier = account(manager, storage=storage)["active_account_id"]
    old_profile = manager.profile_path.read_bytes()

    def fail(*args):
        raise ConnectionError("Synthetic storage failure")

    monkeypatch.setattr(manager, "_write_state", fail)
    with pytest.raises(ConnectionError, match="Synthetic storage failure"):
        manager.save_account(
            {
                "label": "Changed account",
                "profile": manager.status()["profile"],
                "secret_storage": storage,
                "api_key": "replacement-private-test-key",
            },
            identifier,
        )
    assert manager.vault.get("account_" + identifier) == "test-key-account-one"
    assert manager.profile_path.read_bytes() == old_profile
    assert manager.status()["profile"]["provider"] == "none"
    assert manager.status()["active_account_id"] is None
    assert manager.pending_path.exists()
    assert "replacement-private-test-key" not in manager.pending_path.read_text()
    reopened = ConnectionManager(tmp_path / "workspace.sqlite3")
    assert reopened.status()["profile"]["provider"] == "none"
    assert reopened.status()["active_account_id"] is None
    if storage == "encrypted":
        reopened.vault.unlock(phrase)
        assert reopened.vault.get("account_" + identifier) == "test-key-account-one"
    reopened.select_account(identifier)
    assert not reopened.pending_path.exists()
    assert reopened.status()["active_account_id"] == identifier


def test_failed_first_named_save_retains_no_session_key_or_account(
    tmp_path, monkeypatch
):
    manager = ConnectionManager(tmp_path / "workspace.sqlite3")
    monkeypatch.setattr(
        manager,
        "_write_state",
        lambda *args: (_ for _ in ()).throw(ConnectionError("Write failed")),
    )
    with pytest.raises(ConnectionError):
        account(manager)
    assert not manager.vault.session
    assert manager.status()["accounts"] == []
    assert manager.status()["active_account_id"] is None
    assert manager.status()["profile"]["provider"] == "none"


def test_mismatched_saved_account_and_profile_fail_closed_without_overwrite(tmp_path):
    manager = ConnectionManager(tmp_path / "workspace.sqlite3")
    account(manager)
    saved = json.loads(manager.profile_path.read_text())
    saved["profile"]["allow_paid_inference"] = False
    manager.profile_path.write_text(json.dumps(saved))
    raw = manager.profile_path.read_bytes()
    reopened = ConnectionManager(tmp_path / "workspace.sqlite3")
    assert reopened.status()["profile"]["provider"] == "none"
    assert reopened.status()["accounts"] == []
    assert reopened.status()["warnings"]
    assert manager.profile_path.read_bytes() == raw


def test_malformed_vault_salt_is_a_safe_error_on_unlock(tmp_path):
    manager = ConnectionManager(tmp_path / "workspace.sqlite3")
    manager.vault.create("test-only-long-vault-passphrase")
    saved = json.loads(manager.vault.path.read_text())
    saved["salt"] = None
    manager.vault.path.write_text(json.dumps(saved))
    reopened = ConnectionManager(tmp_path / "workspace.sqlite3")
    with pytest.raises(ConnectionError):
        reopened.vault_action(
            {"action": "unlock", "passphrase": "private-test-passphrase"}
        )
    assert reopened.status()["vault"]["locked"] is True
    assert "private-test-passphrase" not in json.dumps(reopened.status())
    assert json.loads(manager.vault.path.read_text()) == saved


def test_aws_model_catalog_filters_bad_labels_and_drops_unrelated_fields(monkeypatch):
    import boto3

    closed = []
    values = [
        {
            "modelId": "provider.good-v1",
            "modelName": "Readable name",
            "account": "do-not-return",
        },
        {"modelId": "provider.bad-label-v1", "modelName": {"private": "do-not-return"}},
        {"modelId": "provider.non-finite-v1", "modelName": float("nan")},
        {"modelId": "provider.control-v1", "modelName": "name\nsecret"},
        {"modelId": "provider.large-v1", "modelName": "x" * 201},
        {"modelId": "bad identifier", "modelName": "Discard"},
    ]
    client = SimpleNamespace(
        list_foundation_models=lambda **kw: {"modelSummaries": values},
        list_inference_profiles=lambda **kw: {"inferenceProfileSummaries": []},
        close=lambda: closed.append(True),
    )

    def session(**kwargs):
        assert kwargs == {"profile_name": "work", "region_name": "us-west-2"}
        return SimpleNamespace(client=lambda *a, **kw: client)

    monkeypatch.setattr(boto3, "Session", session)
    models = aws.model_options("work", "us-west-2")
    assert len(models) == 5 and closed == [True]
    assert models[0]["label"] == "Readable name"
    assert all(row["label"] == row["id"] for row in models[1:])
    assert "do-not-return" not in json.dumps(models, allow_nan=False)


@pytest.mark.parametrize(
    "profile,region",
    [(None, "us-west-2"), ("work", float("nan")), ("../../secret", "us-west-2")],
)
def test_aws_invalid_identifiers_never_reach_sdk(monkeypatch, profile, region):
    import boto3

    monkeypatch.setattr(boto3, "Session", lambda *a, **k: pytest.fail("SDK reached"))
    with pytest.raises(aws.AWSConnectionError):
        aws.model_options(profile, region)
