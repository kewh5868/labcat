"""Boundaries between the embedded coordinator and server-owned research
tools."""

import json
import os
import sys
from contextlib import contextmanager

import pytest

from labcat import goose_mcp, goose_runtime
from labcat.models import ModelError


def profile(provider="openai"):
    return {
        "provider": provider,
        "model": "gpt-4o",
        "allow_paid_inference": provider != "ollama",
        "ollama_url": "http://127.0.0.1:11434",
        "aws_profile": "default",
        "aws_region": "us-west-2",
    }


class Tools:
    build_plan = {"source": "server", "ranking_profile_id": "profile-one"}

    def tool_definitions(self):
        return [
            {
                "name": "generate_ranked_report",
                "description": "Compile approved evidence.",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
            }
        ]

    def call(self, name, arguments):
        assert name == "generate_ranked_report" and arguments == {}
        return {"status": "completed"}


def test_child_environment_does_not_inherit_secrets_or_instructions(
    monkeypatch, tmp_path
):
    for name in (
        "OPENAI_BASE_URL",
        "HTTPS_PROXY",
        "GOOSE_SEARCH_PATHS",
        "AWS_SECRET_ACCESS_KEY",
    ):
        monkeypatch.setenv(name, "private-canary")
    provider, env = goose_runtime._environment(
        profile(), "selected-key", tmp_path, "http://127.0.0.1:2222", "t" * 43, None
    )
    assert provider == "openai"
    assert env["OPENAI_API_KEY"] == "selected-key"
    assert "private-canary" not in json.dumps(env)
    assert env["CONTEXT_FILE_NAMES"] == "[]"
    assert env["GOOSE_PATH_ROOT"] == str(tmp_path)
    assert env["GOOSE_TELEMETRY_OFF"] == "1"
    assert env["HTTPS_PROXY"] == "http://goose-egress:8780"
    assert env["NO_PROXY"] == "127.0.0.1,localhost"


@pytest.mark.parametrize(
    "change",
    [
        {"provider": "claude-code"},
        {"provider": "codex"},
        {"allow_paid_inference": False},
        {"model": "--with-builtin developer"},
    ],
)
def test_provider_configuration_cannot_grant_agent_tools(change, tmp_path):
    with pytest.raises(ModelError):
        goose_runtime._environment(
            {**profile(), **change},
            "key",
            tmp_path,
            "http://127.0.0.1:2222",
            "t" * 43,
            None,
        )


@pytest.mark.parametrize(
    "change",
    [
        {"model": "qwen-cloud"},
        {"ollama_url": "http://192.168.1.1:11434"},
        {"ollama_url": "https://example.com"},
    ],
)
def test_local_model_remains_local(change, tmp_path):
    with pytest.raises(ModelError):
        goose_runtime._environment(
            {**profile("ollama"), **change},
            None,
            tmp_path,
            "http://127.0.0.1:2222",
            "t" * 43,
            None,
        )


def test_only_metadata_is_returned_never_goose_report_text():
    raw = json.dumps(
        {
            "messages": [
                {"role": "assistant", "content": "Fabricated claim: band gap 999 eV"}
            ],
            "metadata": {
                "status": "completed",
                "input_tokens": 17,
                "output_tokens": 3,
                "total_tokens": 20,
            },
        }
    ).encode()
    usage = goose_runtime._usage(raw)
    assert usage["total_tokens"] == 20
    assert usage["cache_read_input_tokens"] is None
    assert "Fabricated" not in json.dumps(usage)


@pytest.mark.parametrize("value", [True, -1, 1.1, "100", 10**12])
def test_invalid_usage_is_not_presented_as_token_information(value):
    with pytest.raises(ModelError):
        goose_runtime._usage(
            json.dumps(
                {"metadata": {"status": "completed", "input_tokens": value}}
            ).encode()
        )


def test_missing_usage_zero_accumulator_is_unknown_not_free():
    result = goose_runtime._usage(
        b'{"metadata":{"status":"completed","input_tokens":0,'
        b'"output_tokens":0,"total_tokens":0}}'
    )
    assert all(value is None for value in result.values())


def test_duplicate_usage_keys_are_rejected():
    with pytest.raises(ModelError):
        goose_runtime._usage(
            b'{"metadata":{"status":"completed","input_tokens":1,"input_tokens":2}}'
        )


def test_mcp_exposes_no_resources_or_nonresearch_tools(monkeypatch):
    calls = []
    monkeypatch.setattr(
        goose_mcp,
        "_broker",
        lambda path, body: calls.append((path, body)) or {"status": "completed"},
    )
    result = goose_mcp.dispatch(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "resources/read",
            "params": {"uri": "file:///private/data"},
        }
    )
    assert result["error"]["code"] == -32601
    assert calls == []
    result = goose_mcp.dispatch(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "generate_ranked_report", "arguments": {}},
        }
    )
    assert result["result"]["isError"] is False
    assert calls == [("/call", {"name": "generate_ranked_report", "arguments": {}})]


def test_broker_rejects_nonloopback_targets_before_network(monkeypatch):
    monkeypatch.setenv("LABCAT_GOOSE_BROKER", "https://example.com")
    monkeypatch.setenv("LABCAT_GOOSE_TOKEN", "t" * 43)
    with pytest.raises(ValueError):
        goose_mcp._broker("/tools", {})


@pytest.mark.parametrize("prompt_size", [13000, 20000])
def test_run_uses_fixed_no_profile_command_and_cleans_temporary_tokens(
    monkeypatch, tmp_path, prompt_size
):
    from labcat import chatgpt_auth

    monkeypatch.setattr(chatgpt_auth, "_is_tmpfs", lambda _: True)
    monkeypatch.setenv("LABCAT_AUTH_TMPDIR", str(tmp_path.resolve()))
    captured = {}
    tokens = {
        "access_token": "sensitive-access",
        "refresh_token": "sensitive-refresh",
        "id_token": "sensitive-id",
        "account_id": "account",
        "expires_at": "2099-01-01T00:00:00Z",
    }

    @contextmanager
    def broker(_):
        yield (
            "http://127.0.0.1:2222",
            "t" * 43,
            [],
            goose_runtime._ReportRetentionSignal(),
        )

    def execute(command, env, folder, payload, **kwargs):
        captured.update(
            command=command, env=env, folder=folder, payload=json.loads(payload)
        )
        path = folder / "config/chatgpt_codex/tokens.json"
        assert json.loads(path.read_text()) == tokens
        if os.name == "posix":
            assert path.stat().st_mode & 0o777 == 0o600
            assert folder.stat().st_mode & 0o777 == 0o700
        return goose_runtime._ProcessResult(
            b'{"messages": [{"content":"invented report"}], '
            b'"metadata":{"status":"completed"}}'
        )

    monkeypatch.setattr(goose_runtime, "runtime_status", lambda: {"available": True})
    monkeypatch.setattr(goose_runtime, "_tool_broker", broker)
    monkeypatch.setattr(goose_runtime, "_execute", execute)
    prompt = "a" * (prompt_size - len("TAIL_INTENT")) + "TAIL_INTENT"
    result = goose_runtime.run_goose(
        profile("chatgpt"),
        None,
        prompt,
        tool_session=Tools(),
        chatgpt_tokens=tokens,
    )
    assert not captured["folder"].exists()
    assert "--no-profile" in captured["command"]
    assert "--no-session" in captured["command"]
    assert "--with-builtin" not in captured["command"]
    assert "sensitive-access" not in " ".join(captured["command"])
    assert captured["payload"]["build_plan"] == Tools.build_plan
    assert captured["payload"]["untrusted_new_prompt"] == prompt
    assert result.pop("refreshed_chatgpt_tokens") == tokens
    assert "invented" not in json.dumps(result)
    assert result["usage"]["input_tokens"] is None


@pytest.mark.parametrize("prompt", [None, "", "a" * 20001])
def test_runtime_rejects_invalid_prompt_before_startup(monkeypatch, prompt):
    monkeypatch.setattr(
        goose_runtime, "runtime_status", lambda: pytest.fail("Inspected runtime")
    )
    with pytest.raises(ModelError, match="20,000"):
        goose_runtime.run_goose(profile(), "test-key", prompt, tool_session=Tools())


def test_process_output_is_bounded_and_errors_do_not_echo_output(monkeypatch, tmp_path):
    monkeypatch.setattr(goose_runtime, "MAX_OUTPUT_BYTES", 1000)
    with pytest.raises(ModelError, match="bounded response size") as error:
        goose_runtime._execute(
            [
                sys.executable,
                "-c",
                "import sys;sys.stdout.write('private-canary'*10000)",
            ],
            {},
            tmp_path,
            b"",
        )
    assert "private-canary" not in str(error.value)
    assert error.value.failure_code == "output_limit"


def test_oauth_never_uses_an_ordinary_temporary_directory(monkeypatch, tmp_path):
    from labcat import chatgpt_auth

    monkeypatch.setattr(chatgpt_auth, "_is_tmpfs", lambda _: False)
    monkeypatch.setenv("LABCAT_AUTH_TMPDIR", str(tmp_path.resolve()))
    with pytest.raises(ModelError, match="memory-backed"):
        with goose_runtime._runtime_directory(True):
            pytest.fail("OAuth storage was incorrectly accepted.")
    assert list(tmp_path.iterdir()) == []


def test_refreshed_token_file_must_be_valid_and_same_account(tmp_path):
    path = tmp_path / "config/chatgpt_codex/tokens.json"
    path.parent.mkdir(parents=True)
    path.write_text('{"access_token":"sensitive", "account_id":"other"}')
    with pytest.raises(ModelError, match="recovered safely") as error:
        goose_runtime._refreshed_tokens(tmp_path, {"account_id": "expected"})
    assert "sensitive" not in str(error.value)
    path.unlink()
    with pytest.raises(ModelError, match="recovered safely"):
        goose_runtime._refreshed_tokens(tmp_path, {"account_id": "expected"})


def test_runtime_failure_retains_internal_refreshed_tokens(monkeypatch, tmp_path):
    tokens = {
        "access_token": "sensitive-access",
        "refresh_token": "sensitive-refresh",
        "id_token": None,
        "account_id": "same",
        "expires_at": "2099-01-01T00:00:00Z",
    }

    @contextmanager
    def directory(_):
        yield tmp_path

    @contextmanager
    def broker(_):
        yield (
            "http://127.0.0.1:2222",
            "t" * 43,
            [],
            goose_runtime._ReportRetentionSignal(),
        )

    def execute(*_, **kwargs):
        raise goose_runtime.GooseRuntimeError("Safe failure", failure_code="time_limit")

    monkeypatch.setattr(goose_runtime, "runtime_status", lambda: {"available": True})
    monkeypatch.setattr(goose_runtime, "_tool_broker", broker)
    monkeypatch.setattr(goose_runtime, "_runtime_directory", directory)
    monkeypatch.setattr(goose_runtime, "_execute", execute)
    with pytest.raises(goose_runtime.GooseRuntimeError) as failure:
        goose_runtime.run_goose(
            profile("chatgpt"),
            None,
            "prompt",
            tool_session=Tools(),
            chatgpt_tokens=tokens,
        )
    assert failure.value.refreshed_chatgpt_tokens == tokens
    assert str(failure.value) == "Safe failure"
    assert failure.value.failure_code == "time_limit"


def test_timeout_includes_child_that_does_not_read_stdin(monkeypatch, tmp_path):
    monkeypatch.setattr(goose_runtime, "MAX_RUNTIME_SECONDS", 0.1)
    with pytest.raises(ModelError, match="time limit") as failure:
        goose_runtime._execute(
            [sys.executable, "-c", "import time;time.sleep(10)"],
            {},
            tmp_path,
            b"x" * 64000,
        )
    assert failure.value.failure_code == "time_limit"
