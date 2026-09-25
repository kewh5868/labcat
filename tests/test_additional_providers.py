"""Provider integration contracts use synthetic secrets; no live
inference."""

import json
from io import BytesIO
from urllib.error import HTTPError
from urllib.parse import urlsplit

import pytest

from labcat import connections, goose_egress, goose_runtime, models
from labcat.connections import DEFAULT_PROFILE, ConnectionManager
from labcat.credentials import ConnectionError
from labcat.provider_catalog import (
    CHAT_COMPLETION_ROUTES,
    MODEL_LIST_ENDPOINTS,
)

PROVIDERS = ("gemini", "deepseek", "xai", "openrouter")
SECRET = "synthetic-selected-provider-key"


def profile(provider, **updates):
    return {
        **DEFAULT_PROFILE,
        "provider": provider,
        "model": "vendor/test-model",
        "allow_paid_inference": True,
        **updates,
    }


def save(manager, provider, **updates):
    return manager.save_account(
        {
            "label": provider,
            "profile": profile(provider, **updates),
            "secret_storage": "session",
            "api_key": SECRET,
        }
    )


@pytest.mark.parametrize("provider", PROVIDERS)
def test_provider_account_catalog_readiness_and_worker_use_selected_key(
    provider, tmp_path, monkeypatch
):
    manager = ConnectionManager(tmp_path / "workspace.sqlite3")
    status = save(manager, provider)
    account_id = status["active_account_id"]
    calls = []

    def request(url, **kwargs):
        calls.append((url, kwargs))
        assert url == MODEL_LIST_ENDPOINTS[provider]
        assert kwargs == {"headers": {"Authorization": "Bearer " + SECRET}}
        return {"data": [{"id": "vendor/test-model"}]}

    monkeypatch.setattr(connections, "request_json", request)
    catalog = manager.list_models()
    assert catalog["provider"] == provider
    assert catalog["models"] == [
        {"id": "vendor/test-model", "label": "vendor/test-model"}
    ]
    assert catalog["inference_tested"] is False
    state = manager.setup.verify()
    assert state["can_research"] and state["model"]["account_id"] == account_id
    assert len(calls) == 2  # Both metadata GETs; verification performs no inference.

    def remote(selected_profile, secret, prompt, **kwargs):
        assert selected_profile == profile(provider)
        assert secret == SECRET and prompt == "Find stable materials"
        assert kwargs["chatgpt_tokens"] is None
        return {"status": "completed", "usage": None}

    monkeypatch.setattr("labcat.goose_worker_client.run_remote_goose", remote)
    monkeypatch.setattr(manager.agent, "_record_usage", lambda *a: None)
    result = manager.agent.run("Find stable materials", None, object())
    assert result["provider"] == provider
    assert result["account_id"] == account_id
    for path in tmp_path.iterdir():
        assert SECRET.encode() not in path.read_bytes()
    assert SECRET not in json.dumps(manager.status())
    assert SECRET not in json.dumps(state)
    reopened = ConnectionManager(tmp_path / "workspace.sqlite3")
    assert reopened.status()["profile"]["provider"] == provider
    assert not reopened.setup.status()["can_research"]


@pytest.mark.parametrize("provider", PROVIDERS)
def test_direct_provider_key_remains_supported_and_optional_vault_roundtrips(
    provider, tmp_path, monkeypatch
):
    monkeypatch.delenv("LABCAT_VAULT_KEY", raising=False)
    monkeypatch.delenv("LABCAT_VAULT_KEY_FILE", raising=False)
    manager = ConnectionManager(tmp_path / "workspace.sqlite3")
    manager.vault_action({"action": "create", "passphrase": "synthetic vault phrase"})
    manager.configure(
        {
            "profile": profile(provider),
            "secret_storage": "encrypted",
            "secrets": {provider: SECRET},
        }
    )
    assert manager.get_secret(provider) == SECRET
    for path in tmp_path.iterdir():
        assert SECRET.encode() not in path.read_bytes()
    reopened = ConnectionManager(tmp_path / "workspace.sqlite3")
    assert reopened.status()["credentials"][provider] == "locked"
    assert reopened.setup.status()["model"]["status"] == "credentials_locked"
    reopened.vault_action({"action": "unlock", "passphrase": "synthetic vault phrase"})
    assert reopened.get_secret(provider) == SECRET
    assert reopened.setup.status()["model"]["status"] == "verification_required"


@pytest.mark.parametrize("provider", PROVIDERS)
def test_provider_catalog_failure_does_not_mark_account_connected(
    provider, tmp_path, monkeypatch
):
    manager = ConnectionManager(tmp_path / "workspace.sqlite3")
    save(manager, provider)

    def denied(*args, **kwargs):
        raise models.ModelError("Provider rejected the request.")

    monkeypatch.setattr(connections, "request_json", denied)
    with pytest.raises(ConnectionError, match="rejected"):
        manager.list_models()
    assert not manager.setup.verify()["can_research"]


@pytest.mark.parametrize("provider", PROVIDERS)
def test_new_provider_cannot_use_another_providers_key(provider, tmp_path, monkeypatch):
    manager = ConnectionManager(tmp_path / "workspace.sqlite3")
    manager.configure(
        {
            "profile": profile(provider),
            "secret_storage": "session",
            "secrets": {"openai": SECRET},
        }
    )
    monkeypatch.setattr(
        connections, "request_json", lambda *a, **k: pytest.fail("No provider call")
    )
    assert not manager.setup.verify()["can_research"]
    with pytest.raises(ConnectionError, match="credential"):
        manager.list_models()


@pytest.mark.parametrize("provider", PROVIDERS)
def test_fixed_compatible_planning_protocol_returns_only_closed_intent(
    provider, monkeypatch
):
    calls = []

    def request(url, **kwargs):
        calls.append(url)
        host, path = CHAT_COMPLETION_ROUTES[provider]
        assert url == host + path
        assert kwargs["headers"] == {"Authorization": "Bearer " + SECRET}
        body = kwargs["body"]
        assert body["model"] == "vendor/test-model"
        assert body["response_format"] == {"type": "json_object"}
        assert body["stream"] is False
        assert "tools" not in body
        return {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": json.dumps(models.Plan().to_dict())},
                }
            ]
        }

    monkeypatch.setattr(models, "request_json", request)
    assert (
        models.plan_with_model(profile(provider), SECRET, "Find materials")
        == models.Plan()
    )
    assert len(calls) == 1


@pytest.mark.parametrize("provider", PROVIDERS)
@pytest.mark.parametrize("change", [{"allow_paid_inference": False}, {"model": ""}])
def test_consent_and_model_required_before_any_inference(provider, change, monkeypatch):
    monkeypatch.setattr(models, "request_json", lambda *a, **k: pytest.fail("network"))
    with pytest.raises(models.ModelError):
        models.plan_with_model(profile(provider, **change), SECRET, "Find materials")


@pytest.mark.parametrize("provider", PROVIDERS)
@pytest.mark.parametrize(
    "response",
    [
        {"choices": [{"finish_reason": "length", "message": {"content": "{}"}}]},
        {"choices": [{"finish_reason": "stop", "message": {"tool_calls": [{}]}}]},
        {"choices": [{"finish_reason": "stop", "message": {"refusal": "no"}}]},
        {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": '{"material":"invented"}'},
                }
            ]
        },
    ],
)
def test_new_provider_responses_cannot_bypass_planning_schema(
    provider, response, monkeypatch
):
    monkeypatch.setattr(models, "request_json", lambda *a, **k: response)
    with pytest.raises(models.ModelError):
        models.plan_with_model(profile(provider), SECRET, "Find materials")


@pytest.mark.parametrize("provider", PROVIDERS)
def test_goose_isolated_configuration_uses_exact_compatible_path(
    provider, tmp_path, monkeypatch
):
    monkeypatch.setenv("OPENAI_HOST", "https://evil.example")
    monkeypatch.setenv("OPENAI_BASE_PATH", "private")
    monkeypatch.setenv("GEMINI_API_KEY", "other-provider-secret")
    runtime_provider, env = goose_runtime._environment(
        profile(provider), SECRET, tmp_path, "http://127.0.0.1:2222", "t" * 43, None
    )
    host, path = CHAT_COMPLETION_ROUTES[provider]
    assert runtime_provider == "openai"
    assert env["OPENAI_HOST"] == host
    assert env["OPENAI_BASE_PATH"] == path.lstrip("/")
    assert env["OPENAI_API_KEY"] == SECRET
    assert "other-provider-secret" not in json.dumps(env)
    assert "evil.example" not in json.dumps(env)
    assert env["HTTPS_PROXY"] == "http://goose-egress:8780"
    assert not list(tmp_path.iterdir())  # Keys remain in child env, not config files.
    domain = urlsplit(host).hostname
    assert goose_egress._destination("CONNECT", domain + ":443") == (domain, 443, None)
    with pytest.raises(goose_egress.ProxyError):
        goose_egress._destination("CONNECT", domain + ".evil.example:443")


@pytest.mark.parametrize("provider", PROVIDERS)
def test_new_provider_http_endpoints_are_allowlisted_and_error_bodies_redacted(
    provider, monkeypatch
):
    urls = [MODEL_LIST_ENDPOINTS[provider], "".join(CHAT_COMPLETION_ROUTES[provider])]
    opened = []

    class Opener:
        def open(self, request, **kwargs):
            opened.append(request.full_url)
            raise HTTPError(request.full_url, 401, SECRET, {}, BytesIO(SECRET.encode()))

    monkeypatch.setattr(models, "build_opener", lambda *a: Opener())
    for url in urls:
        with pytest.raises(models.ModelError, match="Provider rejected") as error:
            models.request_json(url, headers={"Authorization": "Bearer " + SECRET})
        assert SECRET not in str(error.value)
        with pytest.raises(models.ModelError, match="not approved"):
            models.request_json(url.replace("https://", "https://evil.example/"))
        with pytest.raises(models.ModelError, match="not approved"):
            models.request_json(urlsplit(url)._replace(path="/private").geturl())
    assert opened == urls
