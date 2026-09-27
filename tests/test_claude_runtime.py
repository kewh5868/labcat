"""Native Claude may coordinate public tools without acquiring its
coding tools."""

import io
import json
import os
import sys
from contextlib import contextmanager
from email.message import Message
from types import SimpleNamespace

import pytest

from labcat import claude_runtime_wrapper as wrapper
from labcat import goose_runtime, goose_worker, goose_worker_client
from labcat.credentials import ConnectionError
from labcat.models import ModelError

ACCOUNT = "a" * 32
SESSION = "b" * 32


def profile(provider="claude_code"):
    return {
        "provider": provider,
        "model": "sonnet",
        "ollama_url": "http://127.0.0.1:11434",
        "allow_paid_inference": True,
    }


@pytest.fixture
def invocation(monkeypatch, tmp_path):
    from labcat import chatgpt_auth

    if os.name != "posix" or not all(
        hasattr(os, name) for name in ("getuid", "O_NOFOLLOW", "O_NONBLOCK")
    ):
        pytest.skip("Native Linux worker file boundaries require POSIX APIs.")
    monkeypatch.setattr(chatgpt_auth, "_is_tmpfs", lambda _: True)
    root = tmp_path.resolve()
    root.chmod(0o700)
    monkeypatch.setenv("LABCAT_CLAUDE_RUNTIME_DIR", str(root))
    prompt = root / "system.txt"
    prompt.write_text("Use the public Labcat tools.")
    prompt.chmod(0o600)
    mcp = root / "mcp.json"
    mcp.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "labcat": {
                        "type": "stdio",
                        "command": sys.executable,
                        "args": ["-I", "-m", "labcat.goose_mcp"],
                    }
                }
            }
        )
    )
    mcp.chmod(0o600)
    return [
        *wrapper._BASE,
        "--mcp-config",
        str(mcp),
        "--strict-mcp-config",
        "--include-partial-messages",
        "--system-prompt-file",
        str(prompt),
        "--model",
        "sonnet",
        "--dangerously-skip-permissions",
    ]


def test_launcher_removes_native_capabilities_and_bounds_internal_turns(invocation):
    command = wrapper.command(invocation)
    assert command[0] == "/usr/local/bin/claude"
    assert command[command.index("--tools") + 1] == ""
    assert command[command.index("--setting-sources") + 1] == ""
    assert command[command.index("--permission-mode") + 1] == "dontAsk"
    assert "--dangerously-skip-permissions" not in command
    assert command[command.index("--max-turns") + 1] == "8"
    assert "--no-session-persistence" in command
    assert "--disable-slash-commands" in command
    assert "--strict-mcp-config" in command
    assert set(command[command.index("--allowedTools") + 1].split(",")) == {
        "mcp__labcat__" + name for name in goose_runtime.RESEARCH_TOOLS
    }


def test_model_probe_has_no_mcp_tools(monkeypatch, tmp_path):
    monkeypatch.setattr(wrapper, "_root_directory", lambda: tmp_path)
    command = wrapper.command(wrapper._BASE)
    assert command[command.index("--mcp-config") + 1] == '{"mcpServers":{}}'
    assert "--allowedTools" not in command


@pytest.mark.parametrize(
    "extra",
    [
        ["--resume", "session"],
        ["--tools", "Bash"],
        ["--plugin-dir", "/tmp"],
        ["--model", "haiku"],
        ["--dangerously-skip-permissions"],
    ],
)
def test_launcher_rejects_expanded_or_duplicate_arguments(monkeypatch, tmp_path, extra):
    monkeypatch.setattr(wrapper, "_root_directory", lambda: tmp_path)
    arguments = [
        *wrapper._BASE,
        "--mcp-config",
        "unused.json",
        "--strict-mcp-config",
        "--include-partial-messages",
        "--system-prompt-file",
        "unused.txt",
        "--model",
        "sonnet",
        "--dangerously-skip-permissions",
    ]
    with pytest.raises(wrapper.RuntimeBoundaryError):
        wrapper.command(arguments + extra)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value["mcpServers"].update(
            extra={"type": "http", "url": "https://example.com"}
        ),
        lambda value: value["mcpServers"]["labcat"].update(command="/bin/sh"),
        lambda value: value["mcpServers"]["labcat"].update(
            args=["-c", "print('private')"]
        ),
        lambda value: value["mcpServers"]["labcat"].update(env={"PYTHONPATH": "/tmp"}),
    ],
)
def test_launcher_rejects_any_extra_mcp_capability(mutation):
    value = {
        "mcpServers": {
            "labcat": {
                "type": "stdio",
                "command": sys.executable,
                "args": ["-I", "-m", "labcat.goose_mcp"],
            }
        }
    }
    mutation(value)
    with pytest.raises(wrapper.RuntimeBoundaryError):
        wrapper._validate_mcp(json.dumps(value))


@pytest.mark.parametrize(
    "unsafe", ["symlink", "public", "outside", "duplicate", "large"]
)
def test_launcher_rejects_unsafe_runtime_files(invocation, tmp_path, unsafe):
    from pathlib import Path

    index = invocation.index("--mcp-config") + 1
    path = Path(invocation[index])
    if unsafe == "symlink":
        link = tmp_path / "link"
        link.symlink_to(path)
        invocation[index] = str(link)
    elif unsafe == "public":
        path.chmod(0o644)
    elif unsafe == "outside":
        invocation[index] = str(tmp_path.parent / "unrelated.json")
    elif unsafe == "duplicate":
        path.write_text('{"mcpServers":{},"mcpServers":{}}')
    else:
        path.write_text("x" * 16001)
    with pytest.raises((wrapper.RuntimeBoundaryError, ValueError)):
        wrapper.command(invocation)


def test_launcher_requires_verified_memory_backing(invocation, monkeypatch):
    from labcat import chatgpt_auth

    monkeypatch.setattr(chatgpt_auth, "_is_tmpfs", lambda _: False)
    with pytest.raises(wrapper.RuntimeBoundaryError):
        wrapper.command(invocation)


def test_claude_environment_contains_only_selected_native_session(
    monkeypatch, tmp_path
):
    for key in (
        "CLAUDE_CODE_OAUTH_TOKEN",
        "ANTHROPIC_API_KEY",
        "CLAUDE_CODE_COMMAND",
        "ANTHROPIC_BASE_URL",
        "CLAUDE_CONFIG_DIR",
    ):
        monkeypatch.setenv(key, "private-parent-canary")
    provider, env = goose_runtime._environment(
        profile(),
        None,
        tmp_path,
        "http://127.0.0.1:2222",
        "t" * 43,
        None,
        {"HOME": "/tmp/account-home", "CLAUDE_CONFIG_DIR": "/tmp/account-config"},
    )
    assert provider == "claude-code"
    assert env["HOME"] == "/tmp/account-home"
    assert env["CLAUDE_CODE_COMMAND"] == "/usr/local/bin/labcat-claude-runtime"
    assert "private-parent-canary" not in json.dumps(env)
    assert "ANTHROPIC_API_KEY" not in env
    assert "CLAUDE_CODE_OAUTH_TOKEN" not in env


@pytest.mark.parametrize(
    "secret,tokens,env",
    [
        ("api-secret", None, {"HOME": "/tmp/h", "CLAUDE_CONFIG_DIR": "/tmp/c"}),
        (
            None,
            {"access_token": "token"},
            {"HOME": "/tmp/h", "CLAUDE_CONFIG_DIR": "/tmp/c"},
        ),
        (
            None,
            None,
            {
                "HOME": "/tmp/h",
                "CLAUDE_CONFIG_DIR": "/tmp/c",
                "ANTHROPIC_API_KEY": "injected",
            },
        ),
    ],
)
def test_native_environment_rejects_key_or_token_bridge(secret, tokens, env, tmp_path):
    with pytest.raises(ModelError):
        goose_runtime._environment(
            profile(), secret, tmp_path, "http://127.0.0.1:2222", "t" * 43, tokens, env
        )


def test_run_pins_verified_native_session_through_worker_execution(
    monkeypatch, tmp_path
):
    from labcat import claude_auth

    events = []

    @contextmanager
    def native(account_id, expected_session_id=None):
        assert (account_id, expected_session_id) == (ACCOUNT, SESSION)
        events.append("pinned")
        try:
            yield {
                "HOME": "/tmp/native-home",
                "CLAUDE_CONFIG_DIR": "/tmp/native-config",
            }
        finally:
            events.append("released")

    @contextmanager
    def directory(needs_oauth):
        assert needs_oauth is True
        yield tmp_path

    @contextmanager
    def broker(_):
        yield (
            "http://127.0.0.1:2222",
            "t" * 43,
            [],
            goose_runtime._ReportRetentionSignal(),
        )

    def execute(command, env, folder, payload, **kwargs):
        assert events == ["pinned"]
        assert env["HOME"] == "/tmp/native-home"
        assert command[command.index("--provider") + 1] == "claude-code"
        events.append("run")
        return goose_runtime._ProcessResult(
            b'{"metadata":{"status":"completed","input_tokens":3,"output_tokens":2}}'
        )

    monkeypatch.setattr(claude_auth, "session_environment", native)
    monkeypatch.setattr(goose_runtime, "runtime_status", lambda: {"available": True})
    monkeypatch.setattr(goose_runtime, "_runtime_directory", directory)
    monkeypatch.setattr(goose_runtime, "_tool_broker", broker)
    monkeypatch.setattr(goose_runtime, "_execute", execute)
    result = goose_runtime.run_goose(
        profile(),
        None,
        "Find public oxides",
        tool_session=SimpleNamespace(build_plan={}),
        claude_account_id=ACCOUNT,
        claude_session_id=SESSION,
    )
    assert events == ["pinned", "run", "released"]
    assert "refreshed_chatgpt_tokens" not in result
    assert result["usage"]["input_tokens"] == 3


def job():
    return {
        "job_id": "c" * 32,
        "callback_token": "d" * 64,
        "profile": profile(),
        "secret": None,
        "prompt": "Public oxide research",
        "context": None,
        "chatgpt_tokens": None,
        "build_plan": {},
        "claude_account_id": ACCOUNT,
        "claude_session_id": SESSION,
    }


@pytest.mark.parametrize(
    "change",
    [
        {"claude_account_id": "../../x"},
        {"claude_session_id": None},
        {"secret": "token"},
        {"chatgpt_tokens": {"access_token": "token"}},
        {"profile": profile("openai")},
    ],
)
def test_worker_rejects_wrong_provider_or_native_identity(change):
    with pytest.raises(goose_worker.WorkerError):
        goose_worker._validate_job({**job(), **change})


def test_worker_native_job_has_no_credentials_and_forwards_bound_session(monkeypatch):
    value = goose_worker._validate_job(job())

    def run(*args, **kwargs):
        assert kwargs["claude_account_id"] == ACCOUNT
        assert kwargs["claude_session_id"] == SESSION
        assert args[1] is None and kwargs["chatgpt_tokens"] is None
        return {"status": "completed"}

    monkeypatch.setattr(goose_worker, "run_goose", run)
    assert goose_worker._run(value)["status"] == "completed"


@pytest.fixture
def native_rpc(monkeypatch):
    from labcat import claude_auth, goose_browser_auth

    calls = []
    value = {
        "available": True,
        "signed_in": True,
        "message": "Connected",
        "session_id": SESSION,
    }
    monkeypatch.setattr(
        claude_auth,
        "status",
        lambda identity: calls.append(("status", identity)) or value,
    )
    monkeypatch.setattr(
        claude_auth,
        "logout",
        lambda identity: calls.append(("logout", identity)) or value,
    )
    monkeypatch.setattr(
        goose_browser_auth, "GooseBrowserAuthBroker", lambda: SimpleNamespace()
    )
    captured = {}

    def server(address, handler):
        captured["handler"] = handler
        return SimpleNamespace()

    monkeypatch.setattr(goose_worker, "ThreadingHTTPServer", server)
    monkeypatch.setattr(goose_worker, "_key", lambda: "a" * 64)
    goose_worker.make_server()

    def post(path, body, *, authenticated=True, origin=False):
        handler = captured["handler"].__new__(captured["handler"])
        handler.path = path
        raw = json.dumps(body).encode()
        handler.headers = Message()
        handler.headers["Content-Length"] = str(len(raw))
        if authenticated:
            handler.headers["Authorization"] = "Bearer " + "a" * 64
        if origin:
            handler.headers["Origin"] = "https://unrelated.example"
        handler.rfile, handler.wfile = io.BytesIO(raw), io.BytesIO()
        handler.send_response = lambda status: setattr(
            handler, "response_status", status
        )
        handler.send_header = lambda *_: None
        handler.end_headers = lambda: None
        handler.do_POST()
        return handler.response_status, json.loads(handler.wfile.getvalue())

    return post, calls


@pytest.mark.parametrize("operation", ["status", "logout"])
def test_native_auth_rpc_is_account_scoped_and_private(native_rpc, operation):
    post, calls = native_rpc
    code, value = post("/claude/" + operation, {"account_id": ACCOUNT})
    assert code == 200 and value["session_id"] == SESSION
    assert calls == [(operation, ACCOUNT)]


@pytest.mark.parametrize(
    "body,auth,origin",
    [
        ({"account_id": "../../x"}, True, False),
        ({"account_id": ACCOUNT, "token": "private"}, True, False),
        ({"account_id": ACCOUNT}, False, False),
        ({"account_id": ACCOUNT}, True, True),
    ],
)
def test_native_auth_rpc_rejects_expansion_before_invoking_cli(
    native_rpc, body, auth, origin
):
    post, calls = native_rpc
    code, _ = post("/claude/status", body, authenticated=auth, origin=origin)
    assert code in {400, 403}
    assert calls == []


def test_parent_transports_native_identity_without_reading_credentials(monkeypatch):
    monkeypatch.setenv("LABCAT_GOOSE_REMOTE", "1")
    monkeypatch.setattr(goose_worker_client, "_channel_key", lambda: "e" * 64)
    captured = []

    @contextmanager
    def callbacks(*_):
        yield []

    def request(path, body):
        assert path == "/run"
        captured.append(goose_worker._validate_job(body))
        return {
            "status": "completed",
            "result": {
                "runtime": "goose",
                "version": goose_runtime.GOOSE_VERSION,
                "status": "completed",
                "usage": {"input_tokens": 2, "output_tokens": 1, "total_tokens": 3},
                "usage_scope": "this_run",
                "account_quota": None,
            },
        }

    monkeypatch.setattr(goose_worker_client, "_callbacks", callbacks)
    monkeypatch.setattr(goose_worker_client, "_worker_request", request)
    value = goose_worker_client.run_remote_goose(
        profile(),
        None,
        "Find public oxides",
        tool_session=SimpleNamespace(build_plan={}),
        claude_account_id=ACCOUNT,
        claude_session_id=SESSION,
    )
    assert value["status"] == "completed"
    assert captured[0]["claude_account_id"] == ACCOUNT
    assert captured[0]["claude_session_id"] == SESSION
    assert captured[0]["secret"] is None
    assert captured[0]["chatgpt_tokens"] is None


@pytest.mark.parametrize(
    "provider,account,session,secret,tokens",
    [
        ("claude_code", ACCOUNT, None, None, None),
        ("claude_code", "../escape", SESSION, None, None),
        ("claude_code", ACCOUNT, SESSION, "private", None),
        ("claude_code", ACCOUNT, SESSION, None, {"token": "private"}),
        ("openai", ACCOUNT, SESSION, "key", None),
    ],
)
def test_parent_rejects_invalid_native_identity_before_channel_access(
    monkeypatch, provider, account, session, secret, tokens
):
    monkeypatch.setenv("LABCAT_GOOSE_REMOTE", "1")
    monkeypatch.setattr(
        goose_worker_client, "_channel_key", lambda: pytest.fail("Read private channel")
    )
    with pytest.raises(ModelError):
        goose_worker_client.run_remote_goose(
            profile(provider),
            secret,
            "Find public oxides",
            tool_session=SimpleNamespace(build_plan={}),
            claude_account_id=account,
            claude_session_id=session,
            chatgpt_tokens=tokens,
        )


@pytest.mark.parametrize(
    "error",
    [
        OSError("private path"),
        ConnectionError("private account state"),
    ],
)
def test_native_session_capture_failures_are_safe_model_errors(monkeypatch, error):
    from labcat import claude_auth

    @contextmanager
    def unavailable(*args, **kwargs):
        raise error
        yield

    monkeypatch.setattr(claude_auth, "session_environment", unavailable)
    with pytest.raises(ModelError, match="Check the connection") as caught:
        with goose_runtime._claude_session(ACCOUNT, SESSION):
            pytest.fail("Used unavailable session")
    assert "private" not in str(caught.value)


@pytest.mark.parametrize(
    "event,code,failed",
    [
        (
            {"type": "result", "is_error": True, "result": "private provider error"},
            0,
            True,
        ),
        ({"type": "error", "message": "private provider error"}, 0, True),
        ({"type": "result", "is_error": False}, 1, True),
        ({"type": "assistant", "content": '{"type":"error"}'}, 0, False),
        ({"type": "result", "is_error": False}, 0, False),
    ],
)
def test_native_relay_preserves_only_structured_failure_bit(
    tmp_path, event, code, failed
):
    raw = (json.dumps(event) + "\n").encode()
    output = io.BytesIO()
    command = [
        sys.executable,
        "-c",
        "import sys;sys.stdout.buffer.write("
        + repr(raw)
        + ");sys.exit("
        + str(code)
        + ")",
    ]
    assert wrapper.relay_native(command, tmp_path, output) == code
    assert output.getvalue() == raw
    marker = tmp_path / wrapper.FAILURE_MARKER
    assert marker.exists() is failed
    if failed:
        assert marker.read_bytes() == b'{"failed":true}'
        assert "private" not in marker.read_text()


@pytest.mark.parametrize(
    "raw",
    [
        b"not-json\n",
        b'{"type":"result","is_error":false,"is_error":true}\n',
        b"x" * 1001,
    ],
)
def test_native_relay_bounds_and_rejects_invalid_protocol(tmp_path, monkeypatch, raw):
    monkeypatch.setattr(wrapper, "MAX_NATIVE_OUTPUT", 1000)
    command = [
        sys.executable,
        "-c",
        "import sys;sys.stdout.buffer.write(" + repr(raw) + ")",
    ]
    with pytest.raises(ValueError):
        wrapper.relay_native(command, tmp_path, io.BytesIO())
    assert (tmp_path / wrapper.FAILURE_MARKER).read_bytes() == b'{"failed":true}'


def test_native_exit_zero_failure_invalidates_verified_connection(
    monkeypatch, tmp_path
):
    from labcat import claude_auth, science
    from labcat.config import load_config
    from labcat.connections import ConnectionManager
    from labcat.research import research

    monkeypatch.setenv("LABCAT_AGENT_ENGINE", "goose")
    monkeypatch.delenv("LABCAT_VAULT_KEY", raising=False)
    monkeypatch.delenv("LABCAT_VAULT_KEY_FILE", raising=False)
    monkeypatch.setattr(
        goose_worker_client,
        "_worker_request",
        lambda *_a, **_k: {
            "available": True,
            "signed_in": True,
            "session_id": SESSION,
            "message": "Fixture sign-in",
        },
    )
    monkeypatch.setattr(
        goose_worker_client, "run_remote_goose", goose_runtime.run_goose
    )
    manager = ConnectionManager(tmp_path / "workspace.sqlite3")
    manager.save_account(
        {
            "label": "Fixture Claude account",
            "profile": profile(),
            "secret_storage": "session",
        }
    )
    assert manager.setup.verify()["can_research"]

    @contextmanager
    def native(*_args, **_kwargs):
        yield {"HOME": str(tmp_path), "CLAUDE_CONFIG_DIR": str(tmp_path / "config")}

    @contextmanager
    def directory(*_args):
        yield tmp_path

    @contextmanager
    def broker(*_args):
        yield (
            "http://127.0.0.1:2222",
            "t" * 43,
            [],
            goose_runtime._ReportRetentionSignal(),
        )

    def execute(_command, _env, folder, _payload, **_kwargs):
        wrapper.record_failure(folder)
        # Pinned Goose masks native error as completed with unknown usage.
        return goose_runtime._ProcessResult(
            b'{"metadata":{"status":"completed","input_tokens":0,"output_tokens":0}}'
        )

    monkeypatch.setattr(claude_auth, "session_environment", native)
    monkeypatch.setattr(goose_runtime, "runtime_status", lambda: {"available": True})
    monkeypatch.setattr(goose_runtime, "_runtime_directory", directory)
    monkeypatch.setattr(goose_runtime, "_tool_broker", broker)
    monkeypatch.setattr(goose_runtime, "_execute", execute)
    monkeypatch.setattr(
        science,
        "run_research",
        lambda *_a, **_k: pytest.fail("Unexpected scientific retrieval"),
    )
    try:
        with pytest.raises(ModelError, match="No report was saved"):
            research(
                "Find oxide dielectric candidates", load_config(), connections=manager
            )
        assert not manager.setup.status()["can_research"]
        assert manager.agent.usage()["last_run"] is None
    finally:
        manager.agent.close()
