"""Host lifecycle regressions using a fake Docker CLI; no daemon
required."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(os.name == "nt", reason="POSIX launcher")


@pytest.fixture
def launcher(tmp_path):
    install = tmp_path / "install with spaces"
    install.mkdir()
    shutil.copy(ROOT / "labcat.sh", install)
    shutil.copy(ROOT / "compose.yaml", install)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "calls.jsonl"
    docker = bin_dir / "docker"
    docker.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        "args = sys.argv[1:]\n"
        "with open(os.environ['CALL_LOG'], 'a') as f:\n"
        "    f.write(json.dumps(args) + '\\n')\n"
        "if args[:2] == ['context', 'inspect']:\n"
        "    print(os.environ.get('TEST_ENDPOINT', 'unix:///local/docker.sock'))\n"
        "elif 'up' in args:\n"
        "    callback = os.environ.get('LABCAT_OAUTH_CALLBACK_PORT', '1455')\n"
        "    with open(os.environ['CALL_LOG'] + '.callbacks', 'a') as f:\n"
        "        f.write(callback + '\\n')\n"
        "    if os.environ.get('TEST_CALLBACK_COLLISION') and callback == '1455':\n"
        "        print(os.environ.get('TEST_COLLISION_MESSAGE', "
        "'Bind for 127.0.0.1:1455 failed: port is already allocated'), "
        "file=sys.stderr)\n"
        "        sys.exit(1)\n"
        "    if os.environ.get('TEST_UP_ERROR'):\n"
        "        print(os.environ['TEST_UP_ERROR'], file=sys.stderr)\n"
        "    sys.exit(int(os.environ.get('TEST_UP_EXIT', '0')))\n"
        "elif 'port' in args:\n"
        "    if args[-1] == '1456':\n"
        "        if 'TEST_CALLBACK_BINDING' not in os.environ: sys.exit(1)\n"
        "        print(os.environ['TEST_CALLBACK_BINDING'])\n"
        "        sys.exit(0)\n"
        "    print(os.environ.get('TEST_BINDING', '127.0.0.1:49155'))\n"
        "elif 'ps' in args and '--quiet' in args:\n"
        "    print(os.environ.get('TEST_RUNNING', 'container-id'))\n"
        "elif args == ['info']:\n"
        "    sys.exit(int(os.environ.get('TEST_INFO_EXIT', '0')))\n"
    )
    docker.chmod(0o755)
    # Exercise host opening without actually opening a window in test runs.
    (bin_dir / "uname").write_text("#!/bin/sh\necho Darwin\n")
    (bin_dir / "uname").chmod(0o755)
    (bin_dir / "open").write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        "with open(os.environ['OPEN_LOG'], 'a') as f:\n"
        "    f.write(json.dumps(sys.argv[1:]) + '\\n')\n"
    )
    (bin_dir / "open").chmod(0o755)
    env = {
        **os.environ,
        "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"],
        "CALL_LOG": str(log),
        "OPEN_LOG": str(tmp_path / "open.jsonl"),
    }
    for key in ("DOCKER_CONTEXT", "DOCKER_HOST", "LABCAT_OAUTH_CALLBACK_PORT"):
        env.pop(key, None)

    def run(*args, **overrides):
        result = subprocess.run(
            ["sh", str(install / "labcat.sh"), *args],
            cwd=tmp_path,
            env={**env, **overrides},
            capture_output=True,
            text=True,
            timeout=10,
        )
        calls = (
            [json.loads(line) for line in log.read_text().splitlines()]
            if log.exists()
            else []
        )
        return result, calls

    run.callbacks = lambda: Path(str(log) + ".callbacks").read_text().splitlines()
    return run, install, Path(env["OPEN_LOG"])


def test_start_from_other_directory_and_repeat_reuses_project(launcher):
    run, install, opened = launcher
    for _ in range(2):
        result, calls = run("start", "--no-open")
        assert result.returncode == 0, result.stderr
        assert "http://127.0.0.1:49155/" in result.stdout
        assert [
            "compose",
            "--project-name",
            "labcat",
            "--file",
            str(install / "compose.yaml"),
            "up",
            "--detach",
            "--wait",
            "--wait-timeout",
            "60",
        ] in calls
        assert all("run" not in call and "rm" not in call for call in calls)
    assert not opened.exists()


@pytest.mark.parametrize("action", ["start", "stop", "status", "logs"])
@pytest.mark.parametrize("local_kind", ["absent", "file", "directory"])
def test_local_deployment_override_applies_only_when_file_exists(
    launcher, action, local_kind
):
    run, install, _ = launcher
    local = install / "compose.local.yaml"
    if local_kind == "file":
        local.write_text("services: {}\n")
    elif local_kind == "directory":
        local.mkdir()
    result, calls = run(action, "--no-open")
    assert result.returncode == 0, result.stderr
    managed = [call for call in calls if call[:2] == ["compose", "--project-name"]]
    assert managed
    expected = [str(install / "compose.yaml")]
    if local_kind == "file":
        expected.append(str(local))
    for call in managed:
        assert [call[i + 1] for i, arg in enumerate(call) if arg == "--file"] == (
            expected
        )


def test_local_deployment_override_survives_callback_retry(launcher):
    run, install, _ = launcher
    local = install / "compose.local.yaml"
    local.write_text("services: {}\n")
    result, calls = run("start", "--no-open", TEST_CALLBACK_COLLISION="1")
    assert result.returncode == 0, result.stderr
    starts = [call for call in calls if "up" in call]
    assert len(starts) == 2
    assert starts[0] == starts[1]
    assert starts[0][5:7] == ["--file", str(local)]


def test_default_opens_only_discovered_local_url(launcher):
    run, _, opened = launcher
    result, _ = run(TEST_BINDING="127.0.0.1:53210")
    assert result.returncode == 0, result.stderr
    calls = [json.loads(line) for line in opened.read_text().splitlines()]
    assert calls[-1] == ["http://127.0.0.1:53210/"]


def test_native_window_preferred_when_bundled(launcher):
    run, install, opened = launcher
    app = install / "desktop-bin" / "Labcat.app"
    app.mkdir(parents=True)
    result, _ = run()
    assert result.returncode == 0, result.stderr
    args = json.loads(opened.read_text().splitlines()[-1])
    assert args == ["-n", "-a", str(app), "--args", "--url", "http://127.0.0.1:49155/"]


def test_browser_mode_skips_bundled_native_app(launcher):
    run, install, opened = launcher
    (install / "desktop-bin" / "Labcat.app").mkdir(parents=True)
    result, _ = run("--browser")
    assert result.returncode == 0, result.stderr
    assert json.loads(opened.read_text().splitlines()[-1]) == [
        "http://127.0.0.1:49155/"
    ]


@pytest.mark.parametrize(
    "arguments, network, expected",
    [
        ([], "bridge", ["status"]),
        (["status", "--format", "json"], "bridge", ["status", "--format", "json"]),
        (["--offline"], "none", ["status"]),
        (
            ["--offline", "status", "--format", "json"],
            "none",
            ["status", "--format", "json"],
        ),
        (
            ["--offline", "research", "Compare Fe-Ni alloys"],
            "none",
            ["research", "Compare Fe-Ni alloys"],
        ),
    ],
)
def test_cli_mode_forwards_arguments_without_starting_web_service(
    launcher, arguments, network, expected
):
    run, _, opened = launcher
    result, calls = run("cli", *arguments)
    assert result.returncode == 0, result.stderr
    assert calls[-1] == [
        "run",
        "--rm",
        "--pull",
        "never",
        "--network",
        network,
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--init",
        "--tmpfs",
        "/tmp:size=64m,mode=1777",
        "--tmpfs",
        "/var/lib/labcat:size=64m,uid=10001,gid=10001,mode=0700",
        "labcat:0.1.0.dev0",
        *expected,
    ]
    assert all("up" not in call and "port" not in call for call in calls)
    assert not opened.exists()


def test_help_describes_public_and_offline_cli_without_contacting_docker(launcher):
    run, _, opened = launcher
    result, calls = run("--help")
    assert result.returncode == 0, result.stderr
    assert "cli [--offline]" in result.stdout
    assert "running application account" in result.stdout
    assert calls == []
    assert not opened.exists()


def test_research_reuses_live_server_account_without_host_credentials(launcher):
    run, install, opened = launcher
    prompt = 'Compare Fe-Ni alloys; $(touch impossible) "quoted"'
    result, calls = run("cli", "research", prompt, "--format", "json")
    assert result.returncode == 0, result.stderr
    assert calls[-1] == [
        "compose",
        "--project-name",
        "labcat",
        "--file",
        str(install / "compose.yaml"),
        "exec",
        "--no-TTY",
        "labcat",
        "labcat",
        "research",
        "--server",
        prompt,
        "--format",
        "json",
    ]
    assert any("up" in call for call in calls)
    assert not any("run" in call or "--volume" in call for call in calls)
    assert all(call[-1] == "1456" for call in calls if "port" in call)
    assert not opened.exists()


def test_failed_headless_research_start_does_not_execute_or_open(launcher):
    run, _, opened = launcher
    result, calls = run("cli", "research", "Compare alloys", TEST_UP_EXIT="1")
    assert result.returncode != 0
    assert not any("exec" in call for call in calls)
    assert not opened.exists()


@pytest.mark.parametrize(
    "binding",
    [
        "0.0.0.0:5000",
        "127.0.0.1:0",
        "127.0.0.1:65536",
        "127.0.0.1:5000\n127.0.0.1:5001",
        "127.0.0.1:5000/evil",
        "",
    ],
)
def test_bad_binding_cannot_open_browser(launcher, binding):
    run, _, opened = launcher
    result, _ = run(TEST_BINDING=binding)
    assert result.returncode != 0
    assert not opened.exists()


@pytest.mark.parametrize(
    "failure",
    [
        {"TEST_UP_EXIT": "1"},
        {"TEST_INFO_EXIT": "1"},
        {"TEST_ENDPOINT": "ssh://remote"},
        {"DOCKER_HOST": "tcp://remote:2375"},
    ],
)
def test_failed_start_does_not_claim_ready_or_open(launcher, failure):
    run, _, opened = launcher
    result, _ = run(**failure)
    assert result.returncode != 0
    assert "Labcat UI:" not in result.stdout
    assert not opened.exists()


def test_stop_targets_only_managed_project(launcher):
    run, install, opened = launcher
    result, calls = run("stop")
    assert result.returncode == 0
    assert calls[-1] == [
        "compose",
        "--project-name",
        "labcat",
        "--file",
        str(install / "compose.yaml"),
        "stop",
    ]
    assert not opened.exists()


def test_stopped_status_does_not_lookup_stale_port(launcher):
    run, _, _ = launcher
    result, calls = run("status", TEST_RUNNING="")
    assert result.returncode == 0
    assert "Labcat is stopped." in result.stdout
    assert all("port" not in call for call in calls)


@pytest.mark.parametrize(
    "message",
    [
        "Bind for 127.0.0.1:1455 failed: port is already allocated",
        "listen tcp4 127.0.0.1:1455: bind: address already in use",
        "listen tcp 127.0.0.1:1455: bind: Only one usage of each socket "
        "address is normally permitted.",
    ],
)
def test_callback_collision_retries_once_without_stopping_its_owner(launcher, message):
    run, _, opened = launcher
    result, calls = run(TEST_CALLBACK_COLLISION="1", TEST_COLLISION_MESSAGE=message)
    assert result.returncode == 0, result.stderr
    assert run.callbacks() == ["1455", "0"]
    assert "ChatGPT browser sign-in needs local port 1455" in result.stderr
    assert "http://127.0.0.1:49155/" in result.stdout
    assert len(opened.read_text().splitlines()) == 1
    assert not any("stop" in call or "rm" in call or "kill" in call for call in calls)


def test_callback_fallback_is_reused_when_reopening_without_recreation(launcher):
    run, _, _ = launcher
    result, calls = run("--no-open", TEST_CALLBACK_BINDING="127.0.0.1:54322")
    assert result.returncode == 0, result.stderr
    assert run.callbacks() == ["0"]
    assert len([call for call in calls if "up" in call]) == 1


def test_explicit_callback_setting_overrides_a_previous_dynamic_binding(launcher):
    run, _, _ = launcher
    result, _ = run(
        "--no-open",
        TEST_CALLBACK_BINDING="127.0.0.1:54322",
        LABCAT_OAUTH_CALLBACK_PORT="1455",
    )
    assert result.returncode == 0, result.stderr
    assert run.callbacks() == ["1455"]


@pytest.mark.parametrize(
    "error",
    [
        "image unavailable",
        "container is unhealthy",
        "Bind for 127.0.0.1:8000 failed: port is already allocated",
        "Bind for 127.0.0.1:14550 failed: port is already allocated",
        "listen tcp4 127.0.0.1:1455: bind: permission denied",
    ],
)
def test_unrelated_start_failure_does_not_retry_or_open(launcher, error):
    run, _, opened = launcher
    result, _ = run(TEST_UP_EXIT="1", TEST_UP_ERROR=error)
    assert result.returncode != 0
    assert run.callbacks() == ["1455"]
    assert not opened.exists()


def test_callback_fallback_failure_stops_after_one_retry(launcher):
    run, _, opened = launcher
    result, _ = run(TEST_CALLBACK_COLLISION="1", TEST_UP_EXIT="1")
    assert result.returncode != 0
    assert run.callbacks() == ["1455", "0"]
    assert "Labcat UI:" not in result.stdout
    assert not opened.exists()


def test_headless_research_uses_callback_fallback_without_polluting_stdout(launcher):
    run, _, opened = launcher
    result, calls = run(
        "cli", "research", "Compare alloys", TEST_CALLBACK_COLLISION="1"
    )
    assert result.returncode == 0, result.stderr
    assert run.callbacks() == ["1455", "0"]
    assert "1455" not in result.stdout
    assert any("exec" in call for call in calls)
    assert not opened.exists()
