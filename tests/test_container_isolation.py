"""Ensure deployment smoke checks reject filesystem and network
privilege leaks."""

import importlib.util
import json
from copy import deepcopy
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "smoke_container", Path(__file__).parents[1] / "scripts" / "smoke_container.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


@pytest.fixture
def deployment():
    channel_mount = {
        "Type": "volume",
        "Name": "test_agent-channel",
        "Destination": "/run/labcat-channel",
        "RW": True,
    }
    app = {
        "Image": "sha256:test-image",
        "Config": {"User": "labcat"},
        "HostConfig": {
            "ReadonlyRootfs": True,
            "Privileged": False,
            "CapDrop": ["ALL"],
            "CapAdd": [],
            "Devices": [],
            "SecurityOpt": ["no-new-privileges:true"],
            "Binds": [],
            "VolumesFrom": [],
            "PidMode": "",
            "IpcMode": "private",
            "NetworkMode": "test_default",
            "Tmpfs": {"/tmp": "size=64m,mode=1777"},
            "PortBindings": {
                "8000/tcp": [{"HostIp": "127.0.0.1", "HostPort": ""}],
                "1456/tcp": [{"HostIp": "127.0.0.1", "HostPort": ""}],
            },
            "PublishAllPorts": False,
        },
        "Mounts": [
            {
                "Type": "volume",
                "Name": "test_workspace-data",
                "Destination": "/var/lib/labcat",
                "RW": True,
            },
            channel_mount,
        ],
        "NetworkSettings": {
            "Ports": {
                "8000/tcp": [{"HostIp": "127.0.0.1", "HostPort": "51000"}],
                "1456/tcp": [{"HostIp": "127.0.0.1", "HostPort": "51001"}],
            },
            "Networks": {"test_default": {}, "test_agent-private": {}},
        },
    }
    worker = deepcopy(app)
    worker["HostConfig"]["PortBindings"] = {}
    worker["NetworkSettings"]["Ports"] = {"8000/tcp": None}
    worker["Mounts"] = [{**channel_mount, "RW": False}]
    worker["NetworkSettings"]["Networks"] = {"test_agent-private": {}}
    egress = deepcopy(app)
    egress["HostConfig"]["PortBindings"] = {}
    egress["NetworkSettings"]["Ports"] = {"8000/tcp": None}
    egress["Mounts"] = []
    channel = {
        "Name": "test_agent-channel",
        "Driver": "local",
        "Options": {
            "type": "tmpfs",
            "device": "tmpfs",
            "o": "size=1m,uid=10001,gid=10001,mode=0700",
        },
    }
    networks = [
        {"Name": "test_default", "Internal": False},
        {"Name": "test_agent-private", "Internal": True},
    ]
    return app, worker, channel, egress, networks


def test_expected_container_boundaries_pass(deployment):
    MODULE.validate_container_isolation(*deployment)


@pytest.mark.parametrize("port", ["8000/tcp", "1456/tcp"])
@pytest.mark.parametrize("location", ["HostConfig", "NetworkSettings"])
def test_main_ui_and_callback_ports_must_be_loopback_only(deployment, port, location):
    key = "PortBindings" if location == "HostConfig" else "Ports"
    deployment[0][location][key][port][0]["HostIp"] = "0.0.0.0"
    with pytest.raises(AssertionError):
        MODULE.validate_container_isolation(*deployment)


def test_main_cannot_publish_an_extra_port(deployment):
    deployment[0]["HostConfig"]["PortBindings"]["8765/tcp"] = [
        {"HostIp": "127.0.0.1", "HostPort": "8765"}
    ]
    with pytest.raises(AssertionError):
        MODULE.validate_container_isolation(*deployment)


def test_smoke_commands_force_a_dynamic_callback_port(monkeypatch):
    calls = []

    def run(args, **kwargs):
        calls.append(kwargs)
        return type("Result", (), {"returncode": 0, "stdout": "ok", "stderr": ""})()

    monkeypatch.setenv("LABCAT_OAUTH_CALLBACK_PORT", "1455")
    monkeypatch.setattr(MODULE.subprocess, "run", run)
    assert MODULE.command("compose", "up") == "ok"
    assert calls[0]["env"]["LABCAT_OAUTH_CALLBACK_PORT"] == "0"


@pytest.mark.parametrize("which", [0, 1, 3])
@pytest.mark.parametrize("destination", ["/home", "/downloads", "/var/run/docker.sock"])
def test_host_bind_is_rejected(deployment, which, destination):
    deployment[which]["Mounts"].append(
        {"Type": "bind", "Source": "/host/private", "Destination": destination}
    )
    with pytest.raises(AssertionError):
        MODULE.validate_container_isolation(*deployment)


def test_worker_cannot_mount_application_data(deployment):
    deployment[1]["Mounts"].append(deployment[0]["Mounts"][0])
    with pytest.raises(AssertionError):
        MODULE.validate_container_isolation(*deployment)


@pytest.mark.parametrize(
    "key,value",
    [
        ("Privileged", True),
        ("ReadonlyRootfs", False),
        ("CapAdd", ["SYS_ADMIN"]),
        ("NetworkMode", "host"),
        ("PidMode", "host"),
        ("IpcMode", "host"),
        ("SecurityOpt", ["seccomp:unconfined"]),
        ("PublishAllPorts", True),
        ("PortBindings", {"8765/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8765"}]}),
    ],
)
def test_worker_privilege_or_port_expansion_is_rejected(deployment, key, value):
    deployment[1]["HostConfig"][key] = value
    with pytest.raises(AssertionError):
        MODULE.validate_container_isolation(*deployment)


def test_worker_channel_must_be_read_only(deployment):
    deployment[1]["Mounts"][0]["RW"] = True
    with pytest.raises(AssertionError):
        MODULE.validate_container_isolation(*deployment)


def test_authentication_channel_must_be_memory_backed(deployment):
    deployment[2]["Options"] = {}
    with pytest.raises(AssertionError):
        MODULE.validate_container_isolation(*deployment)


def test_worker_cannot_join_an_outbound_network(deployment):
    deployment[1]["NetworkSettings"]["Networks"]["test_default"] = {}
    with pytest.raises(AssertionError):
        MODULE.validate_container_isolation(*deployment)


def test_worker_network_must_be_internal(deployment):
    deployment[4][1]["Internal"] = False
    with pytest.raises(AssertionError):
        MODULE.validate_container_isolation(*deployment)


def test_proxy_cannot_mount_authentication_channel(deployment):
    deployment[3]["Mounts"].append(deployment[0]["Mounts"][1])
    with pytest.raises(AssertionError):
        MODULE.validate_container_isolation(*deployment)


def test_proxy_port_must_not_be_published(deployment):
    deployment[3]["HostConfig"]["PortBindings"] = {
        "8780/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8780"}]
    }
    with pytest.raises(AssertionError):
        MODULE.validate_container_isolation(*deployment)


@pytest.fixture
def smoke_workspace(tmp_path):
    """The container's actual seed path, with every public adapter
    disabled."""
    from labcat.config import load_config
    from labcat.science import render_research, run_research
    from labcat.workspace import WorkspaceStore

    store = WorkspaceStore(tmp_path / "smoke.sqlite3")
    config = load_config()
    project = store.create_project("Disposable fixture project")
    chat = store.project_draft(project["id"])

    def seed(chat_id):
        prompt = "TEST ONLY: Compare oxide materials with sources unavailable"
        result = run_research(
            prompt, config, materials_project_mode="off", allow_nomad=False
        )
        assert result["result"]["candidates"] == []
        result["result"]["execution"] = {
            "mode": "test_core_no_sources",
            "provider": "none",
            "presentation": config.to_dict()["presentation"],
            "context_is_evidence": False,
        }
        result = render_research(result, config)
        scope, _ = store.research_inputs(chat_id)
        return store.append_research(chat_id, scope, prompt, result)

    detail = seed(chat["id"])
    store.set_pin(project["id"], "report", detail["reports"][0]["id"])
    return store, project["id"], chat["id"], seed


def test_docker_pin_sequence_runs_against_real_api_without_inference(smoke_workspace):
    from urllib.error import HTTPError

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from labcat.config import load_config
    from labcat.report_exports import create_exports_router
    from labcat.workspace_api import create_router

    store, project_id, chat_id, seed = smoke_workspace
    app = FastAPI()
    app.include_router(create_router(store, load_config()))
    app.include_router(create_exports_router(store))
    with TestClient(app) as client:

        def api(path, body=None, method=None):
            response = client.request(
                method or ("POST" if body is not None else "GET"), path, json=body
            )
            if response.status_code >= 400:
                raise HTTPError(path, response.status_code, "Fixture error", {}, None)
            return response.json() if response.content else None

        def export_bytes(report_id, format):
            response = client.get(
                f"/api/chats/{chat_id}/reports/{report_id}/export"
                f"?format={format}&views=both"
            )
            assert response.status_code == 200
            return response.content

        MODULE.check_report_pin_revisions(api, export_bytes, seed, project_id, chat_id)
        contents = api(f"/api/projects/{project_id}/contents")
        assert len(contents["reports"]) == 3
        assert {row["pin"]["mode"] for row in contents["reports"]} == {
            "snapshot",
            "latest",
        }
        assert len(store.get_global_chat(chat_id)["reports"]) == 2


@pytest.mark.parametrize("format", ["text", "json", "pdf", "docx"])
@pytest.mark.parametrize("views", ["pi", "audit", "both"])
def test_smoke_export_validator_accepts_saved_presentation_v2(
    smoke_workspace, format, views
):
    from labcat.report_exports import (
        prepare_presentation,
        presentation_response,
        render_download,
    )

    store, _, chat_id, _ = smoke_workspace
    report = store.get_global_chat(chat_id)["reports"][0]
    prepared = prepare_presentation(report)
    display = presentation_response(prepared, chat_id)
    body, media_type, filename = render_download(prepared, format, views)
    headers = {
        "Content-Type": media_type,
        "Content-Disposition": f'attachment; filename="{filename}"',
        "X-Content-Type-Options": "nosniff",
    }
    MODULE.validate_export(body, headers, format, views, report, display)


@pytest.mark.parametrize("views", ["pi", "audit", "both"])
@pytest.mark.parametrize("change", ["missing", "modified"])
def test_smoke_export_validator_rejects_changed_material_names(
    smoke_workspace, views, change
):
    from labcat.report_exports import (
        prepare_presentation,
        presentation_response,
        render_download,
    )

    store, _, chat_id, _ = smoke_workspace
    report = store.get_global_chat(chat_id)["reports"][0]
    prepared = prepare_presentation(report)
    display = presentation_response(prepared, chat_id)
    body, media_type, filename = render_download(prepared, "json", views)
    headers = {
        "Content-Type": media_type,
        "Content-Disposition": f'attachment; filename="{filename}"',
        "X-Content-Type-Options": "nosniff",
    }
    MODULE.validate_export(body, headers, "json", views, report, display)
    document = json.loads(body)
    if change == "missing":
        del document["presentation"]["material_names"]
    else:
        document["presentation"]["material_names"] = [
            {"id": "fixture-only", "name": "TEST ONLY: unexpected material name"}
        ]
    with pytest.raises(AssertionError):
        MODULE.validate_export(
            json.dumps(document).encode(), headers, "json", views, report, display
        )


def test_smoke_revision_comparison_keeps_science_but_ignores_pin_state():
    report = {
        "id": "fixture-report",
        "pi_summary": "Fixture content",
        "result": {"candidates": []},
        "snapshot_pin": None,
        "tracking_pin": None,
        "latest_report_id": "fixture-report",
    }
    pinned = {
        **report,
        "snapshot_pin": {"id": "fixture-pin"},
        "latest_report_id": "new-fixture",
    }
    assert MODULE.saved_report_history(
        {"reports": [report]}
    ) == MODULE.saved_report_history({"reports": [pinned]})
    assert MODULE.saved_report_history(
        {"reports": [report]}
    ) != MODULE.saved_report_history(
        {"reports": [{**pinned, "pi_summary": "Changed content"}]}
    )
