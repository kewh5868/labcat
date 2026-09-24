"""Provider protocol boundaries with synthetic credentials; no live
inference."""

import json
from io import BytesIO
from urllib.error import HTTPError
from urllib.parse import urlsplit

import pytest

from labcat import models
from labcat.connections import DEFAULT_PROFILE
from labcat.provider_catalog import CHAT_COMPLETION_ROUTES, MODEL_LIST_ENDPOINTS

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
