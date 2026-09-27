"""Check native Claude's tool boundary without credentials or network
access.

The host launches a disposable, network-disabled container with no
mounts. Only native initialization and the expected unauthenticated
failure execute; no provider sign-in, paid inference or scientific
retrieval is possible.
"""

import argparse
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path


def validate_native_events(raw):
    """Accept only the fixed five-tool inventory and a structured
    error."""
    expected = {
        "mcp__labcat__assess_research_intent",
        "mcp__labcat__search_public_references",
        "mcp__labcat__propose_candidate_leads",
        "mcp__labcat__evaluate_candidate_fit",
        "mcp__labcat__generate_ranked_report",
    }
    if len(raw) > 1_000_000:
        raise AssertionError("Native initialization exceeded its output limit.")
    events = [json.loads(line) for line in raw.splitlines() if line.strip()]
    initialization = [
        row
        for row in events
        if isinstance(row, dict)
        and row.get("type") == "system"
        and row.get("subtype") == "init"
    ]
    assert len(initialization) == 1, "Native tool initialization was not observed."
    tools = initialization[0].get("tools")
    assert (
        isinstance(tools, list)
        and len(tools) == len(expected)
        and set(tools) == expected
    ), "Native tool inventory exceeded the five research capabilities."
    assert any(
        isinstance(row, dict)
        and row.get("type") == "result"
        and row.get("is_error") is True
        for row in events
    ), "The unauthenticated native failure was not observed."
    return sorted(tools)


def validate_network(interfaces, ipv4_routes, ipv6_routes):
    """Allow kernel-created down tunnel devices, never an external
    route."""
    assert any(name == "lo" and flags & 1 for name, flags in interfaces)
    assert all(
        name == "lo" or not flags & 1 for name, flags in interfaces
    ), "Offline probe has an active non-loopback interface."
    assert all(
        not line.split() or line.split()[0] == "lo"
        for line in ipv4_routes.splitlines()[1:]
    ), "Offline probe has an IPv4 route."
    assert all(
        not line.split() or line.split()[-1] == "lo"
        for line in ipv6_routes.splitlines()
    ), "Offline probe has an IPv6 route."


def run_image_probe(image, platform=None):
    """Mount no host state; always remove only this probe's own
    container."""
    name = "labcat-native-boundary-" + uuid.uuid4().hex[:12]
    command = [
        "docker",
        "run",
        "--rm",
        "-i",
        "--name",
        name,
        "--network",
        "none",
        "--read-only",
        "--tmpfs",
        "/tmp:rw,nosuid,nodev,noexec,size=128m,mode=1777",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
    ]
    if platform:
        command.extend(["--platform", platform])
    command.extend(["--entrypoint", "python", image, "-", "--inside"])
    try:
        subprocess.run(
            command, input=Path(__file__).read_bytes(), check=True, timeout=90
        )
    finally:
        subprocess.run(
            ["docker", "rm", "--force", name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=15,
        )


def inside_probe():
    """Run only in a Linux container without external network access."""
    import socket
    import tempfile
    from contextlib import contextmanager

    from labcat import claude_auth, goose_worker_client, science
    from labcat import claude_runtime_wrapper as wrapper
    from labcat import goose_runtime as runtime
    from labcat.agent_tools import ResearchToolSession
    from labcat.config import load_config
    from labcat.connections import DEFAULT_PROFILE, ConnectionManager
    from labcat.models import ModelError
    from labcat.research import research

    validate_network(
        [
            (name, int((Path("/sys/class/net") / name / "flags").read_text(), 16))
            for _index, name in socket.if_nameindex()
        ],
        Path("/proc/net/route").read_text(),
        Path("/proc/net/ipv6_route").read_text(),
    )

    class Tools:
        build_plan = {}
        tool_definitions = staticmethod(ResearchToolSession.tool_definitions)

        def call(self, name, arguments):
            raise AssertionError("Offline initialization cannot execute research.")

    with tempfile.TemporaryDirectory(prefix="labcat-native-offline-") as temporary:
        root = Path(temporary)
        root.chmod(0o700)
        account = root / "native"
        account.mkdir(mode=0o700)
        native_env = {
            "HOME": str(account),
            "CLAUDE_CONFIG_DIR": str(account / "config"),
        }
        profile = {
            **DEFAULT_PROFILE,
            "provider": "claude_code",
            "model": "sonnet",
            "allow_paid_inference": True,
        }
        with runtime._tool_broker(Tools()) as (broker, token, trace, _retained):
            _provider, env = runtime._environment(
                profile, None, root, broker, token, None, native_env
            )
            mcp = root / "probe-mcp.json"
            runtime._private_json(
                mcp,
                {
                    "mcpServers": {
                        "labcat": {
                            "type": "stdio",
                            "command": sys.executable,
                            "args": ["-I", "-m", "labcat.goose_mcp"],
                        }
                    }
                },
            )
            prompt = root / "probe-system.txt"
            prompt.write_text(runtime.SYSTEM)
            prompt.chmod(0o600)
            command = [
                "/usr/local/bin/labcat-claude-runtime",
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
            payload = {
                "type": "user",
                "session_id": "offline",
                "message": {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Find oxide dielectric candidates"}
                    ],
                },
            }
            completed = subprocess.run(
                command,
                input=(json.dumps(payload) + "\n").encode(),
                env=env,
                cwd=root,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=30,
                check=False,
            )
            tools = validate_native_events(completed.stdout)
            assert (root / wrapper.FAILURE_MARKER).read_bytes() == b'{"failed":true}'
            assert (
                not trace
            ), "Unauthenticated initialization executed scientific tools."

        # Pretend only that a saved account was verified earlier; its native
        # storage is empty. All model execution below uses the actual binaries.
        @contextmanager
        def empty_session(_account, expected_session_id=None):
            assert expected_session_id == "b" * 32
            yield native_env

        claude_auth.session_environment = empty_session
        goose_worker_client._worker_request = lambda *_a, **_k: {
            "available": True,
            "signed_in": True,
            "session_id": "b" * 32,
            "message": "Offline test verification fixture.",
        }
        goose_worker_client.run_remote_goose = runtime.run_goose

        def forbidden_retrieval(*_args, **_kwargs):
            raise AssertionError(
                "An unauthenticated model started scientific retrieval."
            )

        science.run_research = forbidden_retrieval
        os.environ["LABCAT_AGENT_ENGINE"] = "goose"
        manager = ConnectionManager(root / "workspace.sqlite3")
        try:
            manager.save_account(
                {
                    "label": "Offline test account",
                    "profile": profile,
                    "secret_storage": "session",
                }
            )
            assert manager.setup.verify()["can_research"]
            try:
                research(
                    "Find oxide dielectric candidates",
                    load_config(),
                    connections=manager,
                )
            except ModelError:
                pass
            else:
                raise AssertionError(
                    "Unauthenticated native execution was reported as completed."
                )
            assert not manager.setup.status()[
                "can_research"
            ], "Native failure did not invalidate the verified connection."
        finally:
            manager.agent.close()
        print(
            json.dumps(
                {
                    "status": "passed",
                    "network": "none",
                    "native_tools": tools,
                    "unauthenticated_research": "failed",
                    "readiness_invalidated": True,
                }
            ),
            flush=True,
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default="labcat:0.1.0.dev0")
    parser.add_argument("--platform", choices=("linux/amd64", "linux/arm64"))
    parser.add_argument("--inside", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.inside:
        inside_probe()
    else:
        run_image_probe(args.image, args.platform)


if __name__ == "__main__":
    main()
