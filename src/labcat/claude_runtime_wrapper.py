"""Constrain Goose's native Claude provider to Labcat's public MCP
tools.

The pinned, unmodified Claude executable owns authentication. This
launcher never reads its credentials and accepts only the two command
shapes emitted by Goose 1.50.0: model discovery and one bounded research
session.
"""

import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path

from labcat.credentials import unique_json_object
from labcat.goose_runtime import MAX_TOOL_CALLS, RESEARCH_TOOLS

CLAUDE_BINARY = "/usr/local/bin/claude"
FAILURE_MARKER = "claude-native-failure.json"
MAX_NATIVE_OUTPUT = 1_000_000
_BASE = ["--input-format", "stream-json", "--output-format", "stream-json", "--verbose"]
_RUN_FLAGS = {
    "--mcp-config",
    "--strict-mcp-config",
    "--include-partial-messages",
    "--system-prompt-file",
    "--model",
    "--dangerously-skip-permissions",
}
_VALUE_FLAGS = {"--mcp-config", "--system-prompt-file", "--model"}


class RuntimeBoundaryError(ValueError):
    """Never include a rejected path, argument, file or provider
    output."""


def _root_directory():
    from labcat.chatgpt_auth import _is_tmpfs

    root = Path(os.environ.get("LABCAT_CLAUDE_RUNTIME_DIR", ""))
    if not root.is_absolute() or root.is_symlink():
        raise RuntimeBoundaryError
    info = root.stat()
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_mode & 0o077
        or info.st_uid != os.getuid()
        or not _is_tmpfs(root)
    ):
        raise RuntimeBoundaryError
    return root.resolve()


def _private_file(value, root, limit):
    path = Path(value)
    if not path.is_absolute() or path.resolve() == root:
        raise RuntimeBoundaryError
    try:
        relative = path.relative_to(root)
    except ValueError:
        raise RuntimeBoundaryError from None
    if ".." in relative.parts or any(
        part.is_symlink() for part in [path, *path.parents] if part != root.parent
    ):
        raise RuntimeBoundaryError
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or info.st_mode & 0o077
            or not 0 < info.st_size <= limit
        ):
            raise RuntimeBoundaryError
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise RuntimeBoundaryError
    return data


def _validate_mcp(raw):
    value = json.loads(raw, object_pairs_hook=unique_json_object)
    expected = {
        "mcpServers": {
            "labcat": {
                "type": "stdio",
                "command": sys.executable,
                "args": ["-I", "-m", "labcat.goose_mcp"],
            }
        }
    }
    if value != expected:
        raise RuntimeBoundaryError


def command(arguments):
    """Build native arguments after validating Goose's closed input
    shape."""
    if arguments[: len(_BASE)] != _BASE or len(arguments) > 16:
        raise RuntimeBoundaryError
    root = _root_directory()
    rest = arguments[len(_BASE) :]
    selected = {}
    while rest:
        flag, *rest = rest
        if flag not in _RUN_FLAGS or flag in selected:
            raise RuntimeBoundaryError
        if flag in _VALUE_FLAGS:
            if not rest:
                raise RuntimeBoundaryError
            selected[flag], *rest = rest
        else:
            selected[flag] = True
    if selected and set(selected) != _RUN_FLAGS:
        raise RuntimeBoundaryError
    # --tools affects built-ins only. Only the fixed MCP server remains; its
    # five tools are independently schema-checked and counted by the parent.
    result = [
        CLAUDE_BINARY,
        "--print",
        *_BASE,
        "--tools",
        "",
        "--setting-sources",
        "",
        "--disable-slash-commands",
        "--no-session-persistence",
        "--permission-mode",
        "dontAsk",
        "--max-turns",
        str(MAX_TOOL_CALLS),
        "--strict-mcp-config",
    ]
    if selected:
        model = selected["--model"]
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,199}", model):
            raise RuntimeBoundaryError
        _validate_mcp(_private_file(selected["--mcp-config"], root, 16_000))
        _private_file(selected["--system-prompt-file"], root, 64_000).decode("utf-8")
        result.extend(
            [
                "--mcp-config",
                selected["--mcp-config"],
                "--system-prompt-file",
                selected["--system-prompt-file"],
                "--include-partial-messages",
                "--model",
                model,
                "--allowedTools",
                ",".join("mcp__labcat__" + name for name in sorted(RESEARCH_TOOLS)),
            ]
        )
    else:
        # Model discovery receives no server and cannot acquire tool access.
        result.extend(["--mcp-config", '{"mcpServers":{}}'])
    return result


def record_failure(root):
    """Retain only a fixed failure bit, never native content or
    credentials."""
    path = root / FAILURE_MARKER
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(b'{"failed":true}')


def relay_native(arguments, root, output):
    """Forward the native protocol and preserve its structured error
    signal.

    Goose 1.50 converts provider failures to assistant prose while
    returning exit zero. The private marker lets the parent fail safely
    without parsing or exposing that prose. The native process stays in
    Goose's process group.
    """
    process = subprocess.Popen(arguments, stdout=subprocess.PIPE)
    seen = 0
    failed = False
    try:
        while True:
            line = process.stdout.readline(MAX_NATIVE_OUTPUT - seen + 1)
            if not line:
                break
            seen += len(line)
            if seen > MAX_NATIVE_OUTPUT:
                raise RuntimeBoundaryError
            event = json.loads(line, object_pairs_hook=unique_json_object)
            if not isinstance(event, dict):
                raise RuntimeBoundaryError
            if event.get("type") == "error" or (
                event.get("type") == "result" and event.get("is_error") is True
            ):
                failed = True
                record_failure(root)
            output.write(line)
            output.flush()
        code = process.wait()
        if code != 0 or failed:
            record_failure(root)
        return code
    except (OSError, ValueError, TypeError, RecursionError):
        record_failure(root)
        raise
    finally:
        if process.poll() is None:
            process.kill()
        process.wait()
        process.stdout.close()


def main():
    try:
        arguments = command(sys.argv[1:])
        code = relay_native(arguments, _root_directory(), sys.stdout.buffer)
    except (OSError, ValueError, TypeError, RecursionError):
        try:
            record_failure(_root_directory())
        except (OSError, ValueError):
            pass
        print(
            "Claude Code could not start within the research boundary.", file=sys.stderr
        )
        raise SystemExit(2) from None
    raise SystemExit(code)


if __name__ == "__main__":
    main()
