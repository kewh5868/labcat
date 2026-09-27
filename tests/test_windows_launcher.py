"""Exercise the PowerShell launcher against Docker responses, without a
daemon."""

import json
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

# Prefer the Windows PowerShell runtime used by labcat.cmd when available.
POWERSHELL = shutil.which("powershell") or shutil.which("pwsh")
pytestmark = pytest.mark.skipif(
    POWERSHELL is None, reason="PowerShell is not installed on this host"
)
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def launcher(tmp_path):
    install = tmp_path / "installation with spaces"
    install.mkdir()
    shutil.copyfile(ROOT / "labcat.ps1", install / "labcat.ps1")
    shutil.copyfile(ROOT / "labcat.cmd", install / "labcat.cmd")
    (install / "compose.yaml").write_text("services: {}\n", encoding="utf-8")
    commands = tmp_path / "docker-calls.jsonl"
    openings = tmp_path / "desktop-opens.jsonl"
    harness = tmp_path / "launcher-harness.ps1"
    harness.write_text(
        textwrap.dedent("""\
            param(
                [Parameter(Position = 0)] [string]$Action = 'start',
                [switch]$NoOpen,
                [switch]$Browser,
                [switch]$Desktop,
                [switch]$Choose,
                [Parameter(ValueFromRemainingArguments = $true)]
                [string[]]$CliArguments = @()
            )
            function global:Start-Process {
                param([string]$FilePath, [string[]]$ArgumentList)
                if ($env:LABCAT_TEST_OPEN_FAIL) { throw "launch failed fixture" }
                @{path = $FilePath; arguments = @($ArgumentList)} |
                    ConvertTo-Json -Compress |
                    Add-Content -Encoding UTF8 -LiteralPath $env:LABCAT_TEST_OPENS
            }
            $launcherParameters = @{
                Action = $Action
                NoOpen = $NoOpen
                Browser = $Browser
                Desktop = $Desktop
                Choose = $Choose
                CliArguments = $CliArguments
            }
            & $env:LABCAT_TEST_SCRIPT @launcherParameters
            exit $LASTEXITCODE
            """),
        encoding="utf-8",
    )
    fake_script = tmp_path / "fake_docker.py"
    fake_script.write_text(
        textwrap.dedent("""\
            import json
            import os
            import sys

            args = sys.argv[1:]
            with open(os.environ["LABCAT_TEST_CALLS"], "a", encoding="utf-8") as log:
                log.write(json.dumps(args) + "\\n")
            if args[:1] == ["info"]:
                if os.environ.get("LABCAT_TEST_DAEMON_FAIL"):
                    sys.exit(1)
                print("linux")
            elif args == ["compose", "version"]:
                if os.environ.get("LABCAT_TEST_COMPOSE_FAIL"):
                    sys.exit(1)
                print("Docker Compose version test")
            elif args[:2] == ["context", "inspect"]:
                if os.environ.get("LABCAT_TEST_CONTEXT_FAIL"):
                    sys.exit(1)
                print(os.environ.get("LABCAT_TEST_ENDPOINT", "unix:///docker.sock"))
            elif args[:1] == ["run"]:
                print("CLI status")
            elif args[:1] == ["compose"]:
                command_index = 1
                while args[command_index] in {
                    "--project-name", "--file", "--project-directory"
                }:
                    command_index += 2
                command = args[command_index]
                if command == "up":
                    callback = os.environ.get("LABCAT_OAUTH_CALLBACK_PORT", "1455")
                    callback_log = os.environ["LABCAT_TEST_CALLS"] + ".callbacks"
                    with open(callback_log, "a") as log:
                        log.write(callback + "\\n")
                    if (os.environ.get("LABCAT_TEST_CALLBACK_COLLISION")
                            and callback == "1455"):
                        print(os.environ.get(
                            "LABCAT_TEST_COLLISION_MESSAGE",
                            "Bind for 127.0.0.1:1455 failed: port is already allocated"
                        ), file=sys.stderr)
                        sys.exit(1)
                    if os.environ.get("LABCAT_TEST_START_FAIL"):
                        print(os.environ.get(
                            "LABCAT_TEST_START_ERROR", "image unavailable"
                        ), file=sys.stderr)
                        sys.exit(1)
                elif command == "port":
                    if args[-1] == "1456":
                        if "LABCAT_TEST_CALLBACK_BINDING" not in os.environ:
                            sys.exit(1)
                        print(os.environ["LABCAT_TEST_CALLBACK_BINDING"])
                        sys.exit(0)
                    print(os.environ.get("LABCAT_TEST_BINDING", "127.0.0.1:54321"))
                elif command == "ps":
                    if "--quiet" in args:
                        if not os.environ.get("LABCAT_TEST_STOPPED"):
                            print("managed-container-id")
                    else:
                        print("Labcat status")
                elif command not in {"stop", "logs", "exec"}:
                    sys.exit(2)
            else:
                sys.exit(2)
            """),
        encoding="utf-8",
    )
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    if os.name == "nt":
        (fake_bin / "docker.cmd").write_text(
            f'@"{sys.executable}" "{fake_script}" %*\n', encoding="utf-8"
        )
    else:
        executable = fake_bin / "docker"
        executable.write_text(
            f"#!{sys.executable}\n"
            f"exec(compile(open({str(fake_script)!r}).read(), "
            f"{str(fake_script)!r}, 'exec'))\n",
            encoding="utf-8",
        )
        executable.chmod(0o755)

    def run(
        *arguments,
        docker_environment=None,
        open_window=False,
        native=False,
        auto_mode=True,
        interactive_answer=None,
        **settings,
    ):
        desktop_executable = tmp_path / "AppData" / "Programs" / "Labcat" / "Labcat.exe"
        if native:
            desktop_executable.parent.mkdir(parents=True, exist_ok=True)
            desktop_executable.write_text("test placeholder", encoding="utf-8")
            (desktop_executable.parent / ".labcat-install-source").write_text(
                str(install) + "\n"
            )
            resources = desktop_executable.parent / "launcher"
            resources.mkdir(exist_ok=True)
            for name in ("labcat.ps1", "labcat.cmd", "compose.yaml"):
                shutil.copyfile(install / name, resources / name)
        else:
            desktop_executable.unlink(missing_ok=True)
        env = os.environ.copy()
        env["LOCALAPPDATA"] = str(tmp_path / "AppData")
        env["PATH"] = str(fake_bin) + os.pathsep + env.get("PATH", "")
        env["LABCAT_TEST_CALLS"] = str(commands)
        env["LABCAT_TEST_OPENS"] = str(openings)
        env["LABCAT_TEST_SCRIPT"] = str(install / "labcat.ps1")
        env.pop("DOCKER_CONTEXT", None)
        env.pop("DOCKER_HOST", None)
        env.pop("LABCAT_OAUTH_CALLBACK_PORT", None)
        env.update(docker_environment or {})
        env.update({f"LABCAT_TEST_{key}": value for key, value in settings.items()})
        command = [
            POWERSHELL,
            "-NoLogo",
            "-NoProfile",
            *(["-NonInteractive"] if interactive_answer is None else []),
            "-File",
            str(harness),
            *arguments,
            *(
                ["-Browser"]
                if open_window
                and auto_mode
                and not any(
                    arg in {"-Browser", "-Desktop", "-Choose"} for arg in arguments
                )
                else []
            ),
            *([] if open_window else ["-NoOpen"]),
        ]
        if interactive_answer is None:
            result = subprocess.run(
                command,
                cwd=tmp_path,
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        else:
            import pty

            master, slave = pty.openpty()
            try:
                process = subprocess.Popen(
                    command,
                    cwd=tmp_path,
                    env=env,
                    stdin=slave,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                os.close(slave)
                slave = None
                os.write(master, (interactive_answer + "\n").encode())
                stdout, stderr = process.communicate(timeout=30)
                result = subprocess.CompletedProcess(
                    command, process.returncode, stdout, stderr
                )
            finally:
                os.close(master)
                if slave is not None:
                    os.close(slave)
        calls = (
            [
                json.loads(line)
                for line in commands.read_text(encoding="utf-8").splitlines()
            ]
            if commands.exists()
            else []
        )
        return result, calls

    run.openings = lambda: (
        [
            json.loads(line)
            for line in openings.read_text(encoding="utf-8-sig").splitlines()
        ]
        if openings.exists()
        else []
    )
    run.callbacks = lambda: Path(str(commands) + ".callbacks").read_text().splitlines()
    run.install = install
    return run


def test_repeated_start_targets_one_project_and_discovers_actual_port(launcher):
    for _ in range(2):
        result, calls = launcher()
        assert result.returncode == 0, result.stderr
        assert "http://127.0.0.1:54321" in result.stdout
    starts = [call for call in calls if "up" in call]
    assert len(starts) == 2
    assert starts[0] == starts[1]
    assert starts[0][1:4] == ["--project-name", "labcat", "--file"]
    assert "installation with spaces" in starts[0][4]
    assert starts[0][-5:] == ["up", "--detach", "--wait", "--wait-timeout", "60"]
    assert all(call[0] != "run" for call in calls)
    assert not any("stop" in call or "rm" in call for call in calls)


@pytest.mark.parametrize("action", ["start", "stop", "status", "logs"])
@pytest.mark.parametrize("local_kind", ["absent", "file", "directory"])
def test_local_deployment_override_applies_only_when_file_exists(
    launcher, action, local_kind
):
    local = launcher.install / "compose.local.yaml"
    if local_kind == "file":
        local.write_text("services: {}\n")
    elif local_kind == "directory":
        local.mkdir()
    result, calls = launcher(action)
    assert result.returncode == 0, result.stderr
    managed = [call for call in calls if call[:2] == ["compose", "--project-name"]]
    assert managed
    expected = [str(launcher.install / "compose.yaml")]
    if local_kind == "file":
        expected.append(str(local))
    for call in managed:
        assert [call[i + 1] for i, arg in enumerate(call) if arg == "--file"] == (
            expected
        )


def test_local_deployment_override_survives_callback_retry(launcher):
    local = launcher.install / "compose.local.yaml"
    local.write_text("services: {}\n")
    result, calls = launcher(CALLBACK_COLLISION="1")
    assert result.returncode == 0, result.stderr
    starts = [call for call in calls if "up" in call]
    assert len(starts) == 2
    assert starts[0] == starts[1]
    assert starts[0][5:7] == ["--file", str(local)]


@pytest.mark.parametrize(
    "binding",
    [
        "0.0.0.0:54321",
        "127.0.0.1:0",
        "127.0.0.1:65536",
        "127.0.0.1:12;malicious-command",
        "127.0.0.1:54321\n127.0.0.1:54322",
        "https://unexpected.example/",
    ],
)
def test_start_never_opens_or_reports_unexpected_binding(launcher, binding):
    result, _ = launcher(BINDING=binding)
    assert result.returncode != 0
    assert "Labcat is running" not in result.stdout


@pytest.mark.parametrize(
    "failure", ["DAEMON_FAIL", "COMPOSE_FAIL", "CONTEXT_FAIL", "START_FAIL"]
)
def test_failed_start_returns_error_without_success_or_cleanup(launcher, failure):
    result, calls = launcher(**{failure: "1"})
    assert result.returncode != 0
    assert "Labcat is running" not in result.stdout
    assert "Labcat:" in result.stderr
    assert not any("stop" in call or "rm" in call for call in calls)
    if failure != "START_FAIL":
        assert not any("up" in call for call in calls)


def test_stop_only_targets_its_managed_compose_project(launcher):
    result, calls = launcher("stop")
    assert result.returncode == 0, result.stderr
    stop = calls[-1]
    assert stop[1:4] == ["--project-name", "labcat", "--file"]
    assert stop[-1] == "stop"
    assert not any("down" in call or "rm" in call for call in calls)


@pytest.mark.parametrize("stopped", [False, True])
def test_status_only_reports_a_url_for_a_running_container(launcher, stopped):
    result, calls = launcher("status", STOPPED="1" if stopped else "")
    assert result.returncode == 0, result.stderr
    assert ("http://127.0.0.1:54321" in result.stdout) is not stopped
    assert any("port" in call for call in calls) is not stopped
    assert not any("up" in call for call in calls)


def test_logs_are_bounded_and_do_not_start_a_container(launcher):
    result, calls = launcher("logs")
    assert result.returncode == 0, result.stderr
    assert calls[-1][-4:] == ["logs", "--tail", "100", "labcat"]
    assert not any("up" in call for call in calls)


@pytest.mark.parametrize(
    ("endpoint", "docker_environment"),
    [
        ("ssh://remote.example", {}),
        ("tcp://127.0.0.1:2375", {}),
        ("unix:///docker.sock", {"DOCKER_HOST": "ssh://remote.example"}),
        (
            "ssh://remote.example",
            {"DOCKER_HOST": "unix:///docker.sock", "DOCKER_CONTEXT": "remote"},
        ),
    ],
)
def test_remote_or_tcp_endpoint_is_rejected_before_start(
    launcher, endpoint, docker_environment
):
    result, calls = launcher(ENDPOINT=endpoint, docker_environment=docker_environment)
    assert result.returncode != 0
    assert "requires a local Docker context" in result.stderr
    assert not any("up" in call for call in calls)


@pytest.mark.parametrize(
    "endpoint", ["unix:///docker.sock", "npipe:////./pipe/docker_engine"]
)
def test_explicit_local_host_overrides_default_context(launcher, endpoint):
    result, calls = launcher(
        ENDPOINT="ssh://unused.example", docker_environment={"DOCKER_HOST": endpoint}
    )
    assert result.returncode == 0, result.stderr
    assert not any(call[0] == "context" for call in calls)


def test_explicit_local_context_takes_precedence_over_remote_host(launcher):
    result, calls = launcher(
        ENDPOINT="npipe:////./pipe/docker_engine",
        docker_environment={
            "DOCKER_CONTEXT": "desktop-linux",
            "DOCKER_HOST": "ssh://unused.example",
        },
    )
    assert result.returncode == 0, result.stderr
    assert any(call[0] == "context" for call in calls)


def test_explicit_desktop_opens_installed_executable(launcher):
    result, _ = launcher("-Desktop", open_window=True, native=True)
    assert result.returncode == 0, result.stderr
    opened = launcher.openings()
    assert len(opened) == 1
    assert Path(opened[0]["path"]).name == "Labcat.exe"
    assert opened[0]["arguments"] == ["--url", "http://127.0.0.1:54321/"]


@pytest.mark.parametrize("native", [False, True])
def test_browser_flag_opens_default_browser_even_with_native_app(launcher, native):
    result, _ = launcher("-Browser", open_window=True, native=native)
    assert result.returncode == 0, result.stderr
    opened = launcher.openings()
    assert len(opened) == 1
    assert opened[0]["path"] == "http://127.0.0.1:54321/"


def test_explicit_browser_does_not_require_native_app(launcher):
    result, _ = launcher(open_window=True)
    assert result.returncode == 0, result.stderr
    assert launcher.openings()[0]["path"] == "http://127.0.0.1:54321/"


def test_no_open_keeps_start_headless_with_native_app_present(launcher):
    result, _ = launcher(native=True)
    assert result.returncode == 0, result.stderr
    assert launcher.openings() == []


@pytest.mark.parametrize(
    ("arguments", "network", "expected"),
    [
        ([], "bridge", ["status"]),
        (
            ["status", "--style", "audit", "--format", "json"],
            "bridge",
            ["status", "--style", "audit", "--format", "json"],
        ),
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
def test_cli_passes_arguments_to_one_container_without_ui(
    launcher, arguments, network, expected
):
    result, calls = launcher("cli", *arguments, open_window=True, native=True)
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
    assert not any("up" in call or "port" in call for call in calls)
    assert launcher.openings() == []


def test_help_describes_public_and_offline_cli_without_contacting_docker(launcher):
    result, calls = launcher("help")
    assert result.returncode == 0, result.stderr
    assert "cli [--offline]" in result.stdout
    assert "running application account" in result.stdout
    assert calls == []
    assert launcher.openings() == []


def test_research_reuses_backend_account_without_mounting_credentials(launcher):
    prompt = "Compare Fe-Ni alloys; $(Write-Output 'not a command')"
    result, calls = launcher("cli", "research", prompt, "--format", "json")
    assert result.returncode == 0, result.stderr
    assert calls[-1][5:] == [
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
    assert launcher.openings() == []


def test_failed_research_start_cannot_execute_request(launcher):
    result, calls = launcher("cli", "research", "Compare alloys", START_FAIL="1")
    assert result.returncode != 0
    assert not any("exec" in call for call in calls)
    assert launcher.openings() == []


def test_start_rejects_unrecognized_positional_arguments(launcher):
    result, _ = launcher("start", "unexpected")
    assert result.returncode != 0
    assert "Extra arguments are supported only after cli" in result.stderr
    assert launcher.openings() == []


@pytest.mark.parametrize(
    "message",
    [
        "Bind for 127.0.0.1:1455 failed: port is already allocated",
        "listen tcp4 127.0.0.1:1455: bind: address already in use",
        "listen tcp 127.0.0.1:1455: bind: Only one usage of each socket "
        "address is normally permitted.",
    ],
)
def test_callback_collision_retries_once_without_touching_its_owner(launcher, message):
    result, calls = launcher(
        open_window=True, CALLBACK_COLLISION="1", COLLISION_MESSAGE=message
    )
    assert result.returncode == 0, result.stderr
    assert launcher.callbacks() == ["1455", "0"]
    assert "ChatGPT browser sign-in needs local port 1455" in result.stderr
    assert len(launcher.openings()) == 1
    assert not any("stop" in call or "rm" in call or "kill" in call for call in calls)


def test_reopening_a_dynamic_callback_reuses_its_setting(launcher):
    result, calls = launcher(CALLBACK_BINDING="127.0.0.1:54322")
    assert result.returncode == 0, result.stderr
    assert launcher.callbacks() == ["0"]
    assert len([call for call in calls if "up" in call]) == 1


def test_explicit_callback_port_overrides_dynamic_binding(launcher):
    result, _ = launcher(
        CALLBACK_BINDING="127.0.0.1:54322",
        docker_environment={"LABCAT_OAUTH_CALLBACK_PORT": "1455"},
    )
    assert result.returncode == 0, result.stderr
    assert launcher.callbacks() == ["1455"]


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
def test_unrelated_start_failure_never_retries_or_opens(launcher, error):
    result, _ = launcher(open_window=True, START_FAIL="1", START_ERROR=error)
    assert result.returncode != 0
    assert launcher.callbacks() == ["1455"]
    assert launcher.openings() == []


def test_retry_failure_is_terminal(launcher):
    result, _ = launcher(open_window=True, CALLBACK_COLLISION="1", START_FAIL="1")
    assert result.returncode != 0
    assert launcher.callbacks() == ["1455", "0"]
    assert "Labcat is running" not in result.stdout
    assert launcher.openings() == []


def test_headless_research_callback_fallback_preserves_stdout(launcher):
    result, calls = launcher(
        "cli", "research", "Compare alloys", CALLBACK_COLLISION="1"
    )
    assert result.returncode == 0, result.stderr
    assert launcher.callbacks() == ["1455", "0"]
    assert "1455" not in result.stdout
    assert any("exec" in call for call in calls)
    assert launcher.openings() == []


def test_unattended_first_start_requires_an_explicit_mode(launcher):
    result, calls = launcher(open_window=True, auto_mode=False)
    assert result.returncode != 0
    assert "Choose a launch mode" in result.stderr
    assert not any("up" in call for call in calls)
    assert launcher.openings() == []


def test_desktop_failure_does_not_silently_open_browser_or_save_choice(launcher):
    result, calls = launcher("-Desktop", open_window=True)
    assert result.returncode != 0
    assert "desktop installer is missing" in result.stderr
    assert not any("up" in call for call in calls)
    assert launcher.openings() == []
    assert not (launcher.install / ".labcat-launch-mode").exists()


@pytest.mark.parametrize("mode", ["desktop", "browser"])
def test_successful_choice_is_saved_and_reused(launcher, mode):
    result, _ = launcher("-" + mode.title(), open_window=True, native=True)
    assert result.returncode == 0, result.stderr
    assert (launcher.install / ".labcat-launch-mode").read_text() == mode + "\n"
    result, _ = launcher(open_window=True, native=True, auto_mode=False)
    assert result.returncode == 0, result.stderr
    assert len(launcher.openings()) == 2
    path = launcher.openings()[-1]["path"]
    assert (
        path.endswith("Labcat.exe") if mode == "desktop" else path.startswith("http://")
    )


def test_browser_switch_replaces_saved_desktop_choice(launcher):
    (launcher.install / ".labcat-launch-mode").write_text("desktop\n")
    result, _ = launcher("-Browser", open_window=True)
    assert result.returncode == 0, result.stderr
    assert launcher.openings()[0]["path"].startswith("http://")
    assert (launcher.install / ".labcat-launch-mode").read_text() == "browser\n"


def test_choose_does_not_reuse_saved_mode_without_interactive_input(launcher):
    (launcher.install / ".labcat-launch-mode").write_text("browser\n")
    result, calls = launcher("-Choose", open_window=True)
    assert result.returncode != 0
    assert "Choose a launch mode" in result.stderr
    assert not any("up" in call for call in calls)


@pytest.mark.parametrize(
    "mode", ["browser; Write-Output unsafe", "desktop\nbrowser", ""]
)
def test_invalid_saved_mode_does_not_execute_or_launch(launcher, mode):
    (launcher.install / ".labcat-launch-mode").write_text(mode)
    result, _ = launcher(open_window=True, auto_mode=False)
    assert result.returncode != 0
    assert "saved launch preference is invalid" in result.stderr
    assert launcher.openings() == []


def test_conflicting_mode_flags_are_rejected(launcher):
    result, calls = launcher("-Desktop", "-Browser", open_window=True)
    assert result.returncode != 0
    assert "Choose only one" in result.stderr
    assert calls == []


@pytest.mark.parametrize("action", ["start", "status", "stop", "logs", "cli"])
def test_headless_and_lifecycle_ignore_invalid_saved_mode(launcher, action):
    (launcher.install / ".labcat-launch-mode").write_text("invalid\n")
    result, _ = launcher(action)
    assert result.returncode == 0, result.stderr
    assert launcher.openings() == []


def test_copied_override_preserves_original_project_directory(launcher, tmp_path):
    original = tmp_path / "original source with spaces"
    original.mkdir()
    (launcher.install / ".labcat-project-directory").write_text(str(original) + "\n")
    (launcher.install / "compose.local.yaml").write_text("services: {}\n")
    result, calls = launcher()
    assert result.returncode == 0, result.stderr
    for call in calls:
        if call[:2] == ["compose", "--project-name"]:
            assert call[call.index("--project-directory") + 1] == str(original)


@pytest.mark.parametrize("path", ["relative", "C:\\missing\\location", "first\nsecond"])
def test_invalid_original_project_directory_stops_before_docker(launcher, path):
    (launcher.install / ".labcat-project-directory").write_text(path)
    result, calls = launcher()
    assert result.returncode != 0
    assert "original deployment folder" in result.stderr
    assert calls == []


@pytest.mark.skipif(os.name == "nt", reason="POSIX pseudo-terminal harness")
@pytest.mark.parametrize(
    ("answer", "expected"), [("", "desktop"), ("1", "desktop"), ("2", "browser")]
)
def test_first_interactive_choice_and_default_are_remembered(
    launcher, answer, expected
):
    result, _ = launcher(
        open_window=True, native=True, auto_mode=False, interactive_answer=answer
    )
    assert result.returncode == 0, result.stderr
    assert "Install and open the desktop application (default)" in result.stdout
    assert (launcher.install / ".labcat-launch-mode").read_text() == expected + "\n"
    assert len(launcher.openings()) == 1
    path = launcher.openings()[0]["path"]
    assert (
        path.endswith("Labcat.exe")
        if expected == "desktop"
        else path.startswith("http://")
    )


@pytest.mark.skipif(os.name == "nt", reason="POSIX pseudo-terminal harness")
def test_invalid_interactive_choice_does_not_install_or_start(launcher):
    result, calls = launcher(
        open_window=True, auto_mode=False, interactive_answer="wrong"
    )
    assert result.returncode != 0
    assert "No mode was selected" in result.stderr
    assert not any("up" in call for call in calls)
    assert launcher.openings() == []


def test_first_desktop_choice_calls_installer_then_uses_fixed_executable(launcher):
    installer = launcher.install / "scripts" / "install_desktop.ps1"
    installer.parent.mkdir()
    installer.write_text(
        "param([string]$SourceRoot, [string]$Destination)\n"
        "[IO.Directory]::CreateDirectory($Destination) | Out-Null\n"
        "[IO.File]::WriteAllText((Join-Path $Destination 'Labcat.exe'), 'fixture')\n"
    )
    result, calls = launcher("-Desktop", open_window=True)
    assert result.returncode == 0, result.stderr
    assert len(launcher.openings()) == 1
    assert launcher.openings()[0]["path"].endswith("Labcat.exe")
    assert launcher.openings()[0]["arguments"] == ["--url", "http://127.0.0.1:54321/"]
    assert any("up" in call for call in calls)
    assert (launcher.install / ".labcat-launch-mode").read_text() == "desktop\n"


def test_desktop_launch_error_does_not_fall_back_or_save_choice(launcher):
    result, calls = launcher("-Desktop", open_window=True, native=True, OPEN_FAIL="1")
    assert result.returncode != 0
    assert "desktop application could not be opened" in result.stderr
    assert any("up" in call for call in calls)
    assert launcher.openings() == []
    assert not (launcher.install / ".labcat-launch-mode").exists()


def test_installer_failure_does_not_start_backend_or_save_choice(launcher):
    installer = launcher.install / "scripts" / "install_desktop.ps1"
    installer.parent.mkdir()
    installer.write_text("throw 'installation failure fixture'\n")
    result, calls = launcher("-Desktop", open_window=True)
    assert result.returncode != 0
    assert "installation failure fixture" in result.stderr
    assert not any("up" in call for call in calls)
    assert launcher.openings() == []
    assert not (launcher.install / ".labcat-launch-mode").exists()
