"""The actual-binary smoke rejects extra capabilities and never mounts
credentials."""

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

spec = importlib.util.spec_from_file_location(
    "claude_smoke", Path(__file__).parents[1] / "scripts/smoke_claude_runtime.py"
)
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)
TOOLS = [
    "mcp__labcat__" + name
    for name in (
        "assess_research_intent",
        "search_public_references",
        "propose_candidate_leads",
        "evaluate_candidate_fit",
        "generate_ranked_report",
    )
]


def events(tools=None, error=True):
    return b"\n".join(
        json.dumps(value).encode()
        for value in [
            {
                "type": "system",
                "subtype": "init",
                "tools": TOOLS if tools is None else tools,
            },
            {"type": "result", "is_error": error},
        ]
    )


def test_inventory_requires_actual_native_init_and_failure():
    assert smoke.validate_native_events(events()) == sorted(TOOLS)


@pytest.mark.parametrize(
    "raw",
    [
        events(TOOLS + ["Bash"]),
        events(TOOLS + ["Read"]),
        events(TOOLS + ["WebFetch"]),
        events(TOOLS + ["mcp__other__search"]),
        events(TOOLS[:-1]),
        events(TOOLS + [TOOLS[0]]),
        events(error=False),
        b'{"type":"result","is_error":true}',
    ],
)
def test_extra_missing_duplicate_or_unobserved_tool_inventory_fails(raw):
    with pytest.raises(AssertionError):
        smoke.validate_native_events(raw)


def test_docker_probe_has_no_network_or_credential_mount_and_cleans_own_container(
    monkeypatch,
):
    calls = []

    def run(command, **options):
        calls.append((command, options))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(smoke.subprocess, "run", run)
    smoke.run_image_probe("fixture-image", "linux/arm64")
    command, options = calls[0]
    assert command[command.index("--network") + 1] == "none"
    assert "--read-only" in command
    assert not {"-v", "--mount", "--volume", "--env", "-e", "--env-file"} & set(command)
    assert command[command.index("--platform") + 1] == "linux/arm64"
    assert b"def inside_probe" in options["input"]
    assert calls[1][0] == [
        "docker",
        "rm",
        "--force",
        command[command.index("--name") + 1],
    ]


def test_offline_network_allows_only_loopback_and_down_kernel_tunnels():
    smoke.validate_network(
        [("lo", 0x9), ("tunl0", 0x80), ("gre0", 0x80)],
        "Iface Destination Gateway\n",
        "00000000 00 lo\n",
    )


@pytest.mark.parametrize(
    "interfaces,ipv4,ipv6",
    [
        ([("lo", 0x9), ("eth0", 0x1003)], "Iface\n", ""),
        ([("lo", 0x9)], "Iface\neth0 00000000\n", ""),
        ([("lo", 0x9)], "Iface\n", "00000000 eth0\n"),
        ([("lo", 0x8)], "Iface\n", ""),
    ],
)
def test_offline_probe_rejects_external_routes_or_active_interfaces(
    interfaces, ipv4, ipv6
):
    with pytest.raises(AssertionError):
        smoke.validate_network(interfaces, ipv4, ipv6)
