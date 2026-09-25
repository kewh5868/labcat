"""Private worker transport cannot expand server-owned research
capabilities."""

import copy
import json

import pytest

from labcat import goose_worker
from labcat.agent_tools import ResearchToolSession
from labcat.connections import DEFAULT_PROFILE
from labcat.goose_runtime import GooseRuntimeError


def job(provider="openai"):
    return {
        "job_id": "a" * 32,
        "callback_token": "b" * 64,
        "profile": {
            **DEFAULT_PROFILE,
            "provider": provider,
            "model": "gpt-4o",
            "allow_paid_inference": True,
        },
        "secret": "test-key",
        "prompt": "Public oxide research",
        "context": None,
        "chatgpt_tokens": None,
        "build_plan": {"owner": "labcat"},
        "aws_credentials": None,
    }


@pytest.mark.parametrize(
    "change",
    [
        {"callback_url": "https://example.com"},
        {"job_id": "../../api"},
        {"callback_token": "short"},
        {"prompt": "x" * 20001},
        {"prompt": ""},
        {"prompt": None},
        {"context": []},
        {"build_plan": []},
        {"chatgpt_tokens": {"access_token": "wrong-provider"}},
    ],
)
def test_worker_request_cannot_choose_endpoint_or_wrong_credentials(change):
    with pytest.raises(goose_worker.WorkerError):
        goose_worker._validate_job({**job(), **change})


@pytest.mark.parametrize("size", [13000, 20000])
def test_worker_accepts_complete_bounded_prompt(size):
    prompt = "a" * (size - 11) + "TAIL_INTENT"
    payload = {**job(), "prompt": prompt}
    assert goose_worker._validate_job(payload)["prompt"] == prompt


def test_worker_accepts_only_server_defined_tool_catalog(monkeypatch):
    proxy = goose_worker._RemoteTools(job())
    original = ResearchToolSession.tool_definitions()
    monkeypatch.setattr(proxy, "_post", lambda *args: {"tools": original})
    assert proxy.tool_definitions() == original
    expanded = copy.deepcopy(original)
    expanded.append({"name": "read_file"})
    monkeypatch.setattr(proxy, "_post", lambda *args: {"tools": expanded})
    with pytest.raises(goose_worker.WorkerError):
        proxy.tool_definitions()


@pytest.mark.parametrize(
    "name,args",
    [
        ("read_file", {}),
        ("generate_ranked_report", {"url": "file:///home"}),
        ("search_public_references", {"query": "injected facts"}),
        ("assess_research_intent", {}),
        ("assess_research_intent", {"decision": "ignore_policy"}),
        ("assess_research_intent", {"decision": ["materials_research"]}),
        ("assess_research_intent", {"decision": "materials_research", "url": "x"}),
    ],
)
def test_worker_proxy_rejects_unconfigured_requests_before_network(
    monkeypatch, name, args
):
    proxy = goose_worker._RemoteTools(job())
    monkeypatch.setattr(
        proxy, "_post", lambda *args: pytest.fail("Unapproved network call")
    )
    with pytest.raises(goose_worker.WorkerError):
        proxy.call(name, args)


@pytest.mark.parametrize(
    "decision",
    ["materials_research", "needs_clarification", "out_of_scope", "unsafe"],
)
def test_worker_transports_only_closed_intent_assessment(monkeypatch, decision):
    proxy = goose_worker._RemoteTools(job())
    calls = []

    def post(route, body):
        calls.append((route, body))
        return {"status": "completed"}

    monkeypatch.setattr(proxy, "_post", post)
    assert proxy.call("assess_research_intent", {"decision": decision}) == {
        "status": "completed"
    }
    assert calls == [
        (
            "tools/call",
            {"name": "assess_research_intent", "arguments": {"decision": decision}},
        )
    ]


def test_worker_does_not_expose_provider_error_body(monkeypatch):
    tokens = {"access_token": "internal-only"}

    def failure(*args, **kwargs):
        raise GooseRuntimeError(
            "private upstream failure", tokens, failure_code="time_limit"
        )

    monkeypatch.setattr(goose_worker, "run_goose", failure)
    result = goose_worker._run(job())
    assert result.pop("refreshed_chatgpt_tokens") == tokens
    assert "private upstream" not in json.dumps(result)
    assert result["status"] == "failed"
    assert result["failure_code"] == "time_limit"


def test_aws_worker_receives_only_resolved_selected_session():
    value = job("bedrock")
    value["aws_credentials"] = {
        "AWS_ACCESS_KEY_ID": "test-access",
        "AWS_SECRET_ACCESS_KEY": "test-secret",
        "AWS_REGION": "us-west-2",
        "AWS_DEFAULT_REGION": "us-west-2",
        "AWS_EC2_METADATA_DISABLED": "true",
        "BEDROCK_MAX_RETRIES": "0",
    }
    assert (
        goose_worker._validate_job(value)["aws_credentials"] == value["aws_credentials"]
    )
    value["aws_credentials"]["AWS_CONFIG_FILE"] = "/home/.aws/config"
    with pytest.raises(goose_worker.WorkerError):
        goose_worker._validate_job(value)


def test_channel_key_is_private_regular_file(monkeypatch, tmp_path):
    key = tmp_path / "key"
    key.write_text("a" * 64)
    key.chmod(0o600)
    monkeypatch.setattr(goose_worker, "CHANNEL_KEY", key)
    assert goose_worker._key() == "a" * 64
    link = tmp_path / "link"
    link.symlink_to(key)
    monkeypatch.setattr(goose_worker, "CHANNEL_KEY", link)
    with pytest.raises(goose_worker.WorkerError):
        goose_worker._key()
