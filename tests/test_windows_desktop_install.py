"""Exercise per-user Windows installation with a fake native shell and
build tools.

PowerShell is real; the shell/build artifacts are inert fixtures. Start-
menu and WebView2 integration still require native Windows validation.
"""

import json
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

POWERSHELL = shutil.which("powershell") or shutil.which("pwsh")
pytestmark = pytest.mark.skipif(
    POWERSHELL is None, reason="PowerShell is not installed on this host"
)
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def installer(tmp_path):
    source = tmp_path / "source with spaces"
    source.mkdir()
    for name in ("labcat.ps1", "labcat.cmd", "compose.yaml"):
        shutil.copyfile(ROOT / name, source / name)
    destination = tmp_path / "Programs" / "Labcat"
    calls = tmp_path / "build-calls.jsonl"
    fake_bin = tmp_path / "build-tools"
    fake_bin.mkdir()
    build_script = tmp_path / "fake_build.py"
    build_script.write_text(
        textwrap.dedent("""\
            import json
            import os
            import sys
            from pathlib import Path

            command, *args = sys.argv[1:]
            if args == ['--version']:
                versions = {'node': '24.9.0', 'npm': '11.6.0',
                            'cargo': '1.88.0', 'rustc': '1.88.0'}
                print(os.environ.get(command.upper() + '_VERSION', versions[command]))
                sys.exit(0)
            if command == 'rustc' and args == ['-vV']:
                print('host: ' + os.environ.get('LABCAT_TEST_RUST_HOST',
                                               'x86_64-pc-windows-msvc'))
                sys.exit(0)
            if command == 'vswhere':
                print(os.environ['LABCAT_TEST_VS'])
                sys.exit(0)
            with open(os.environ['LABCAT_TEST_BUILD_CALLS'], 'a') as log:
                log.write(json.dumps(args) + '\\n')
            if args[0] == os.environ.get('LABCAT_TEST_BUILD_FAILURE'):
                sys.exit(1)
            if args[0] == 'run':
                binary = (Path(os.environ['LABCAT_TEST_SOURCE']) / 'desktop'
                          / 'target' / 'release' / 'labcat-desktop.exe')
                binary.parent.mkdir(parents=True)
                binary.write_bytes(b'native-test-fixture')
            """),
        encoding="utf-8",
    )
    for command in ("node", "npm", "cargo", "rustc", "vswhere"):
        if os.name == "nt":
            (fake_bin / (command + ".cmd")).write_text(
                f'@"{sys.executable}" "{build_script}" {command} %*\n', encoding="utf-8"
            )
        else:
            path = fake_bin / command
            path.write_text(
                f"#!{sys.executable}\nimport sys\nsys.argv.insert(1, {command!r})\n"
                f"exec(compile(open({str(build_script)!r}).read(), "
                f"{str(build_script)!r}, 'exec'))\n",
                encoding="utf-8",
            )
            path.chmod(0o755)

    visual_studio = tmp_path / "Visual Studio fixture"
    windows_sdk = tmp_path / "Windows SDK fixture"
    for file in (
        visual_studio / "VC/Tools/MSVC/14.44/bin/Hostx64/x64/cl.exe",
        visual_studio / "VC/Tools/MSVC/14.44/bin/Hostx64/x64/link.exe",
        windows_sdk / "Include/10.0.26100.0/um/Windows.h",
        windows_sdk / "Include/10.0.26100.0/ucrt/stdio.h",
        windows_sdk / "Lib/10.0.26100.0/um/x64/kernel32.lib",
        windows_sdk / "Lib/10.0.26100.0/ucrt/x64/ucrt.lib",
    ):
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text("inert prerequisite fixture")
    harness = tmp_path / "run-installer.ps1"
    harness.write_text(
        """param(
    [string]$Installer, [string]$SourceRoot, [string]$Destination,
    [switch]$CheckOnly, [switch]$PrebuiltOnly, [switch]$BuildSource
)
function Get-ItemProperty {
    param([string]$LiteralPath, [string]$Name, [string]$ErrorAction)
    if ($Name -eq 'pv' -and $env:LABCAT_TEST_WEBVIEW -ne 'missing') {
        return [pscustomobject]@{ pv = $env:LABCAT_TEST_WEBVIEW }
    }
    if ($Name -eq 'KitsRoot10' -and $env:LABCAT_TEST_SDK -ne 'missing') {
        return [pscustomobject]@{ KitsRoot10 = $env:LABCAT_TEST_SDK }
    }
}
& $Installer -SourceRoot $SourceRoot -Destination $Destination -NoShortcut `
    -CheckOnly:$CheckOnly -PrebuiltOnly:$PrebuiltOnly -BuildSource:$BuildSource
""",
        encoding="utf-8",
    )

    def run(
        *,
        bundled=True,
        failure=None,
        override=None,
        env_updates=None,
        check_only=False,
        prebuilt_only=False,
        build_source=False,
    ):
        if bundled:
            binary = source / "desktop-bin" / "Labcat.exe"
            binary.parent.mkdir(exist_ok=True)
            binary.write_bytes(b"native-test-fixture")
        else:
            desktop = source / "desktop"
            desktop.mkdir(exist_ok=True)
            for name in (
                "package.json",
                "package-lock.json",
                "Cargo.toml",
                "Cargo.lock",
                "tauri.conf.json",
            ):
                (desktop / name).write_text("test fixture\n")
        if override:
            (source / "compose.local.yaml").write_text(override)
        env = os.environ.copy()
        env.update(
            {
                "OS": "Windows_NT",
                "PATH": str(fake_bin),
                "LABCAT_TEST_SOURCE": str(source),
                "LABCAT_TEST_BUILD_CALLS": str(calls),
                "LABCAT_TEST_VS": str(visual_studio),
                "LABCAT_TEST_SDK": str(windows_sdk),
                "LABCAT_TEST_WEBVIEW": "140.0.3485.54",
                "ProgramFiles(x86)": str(tmp_path / "Program Files fixture"),
            }
        )
        env.pop("CARGO_BUILD_TARGET", None)
        env.pop("CARGO_TARGET_DIR", None)
        if failure:
            env["LABCAT_TEST_BUILD_FAILURE"] = failure
        env.update(env_updates or {})
        return subprocess.run(
            [
                POWERSHELL,
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-File",
                str(harness),
                "-Installer",
                str(ROOT / "scripts" / "install_desktop.ps1"),
                "-SourceRoot",
                str(source),
                "-Destination",
                str(destination),
                *(["-CheckOnly"] if check_only else []),
                *(["-PrebuiltOnly"] if prebuilt_only else []),
                *(["-BuildSource"] if build_source else []),
            ],
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
            check=False,
        )

    run.source = source
    run.destination = destination
    run.fake_bin = fake_bin
    run.visual_studio = visual_studio
    run.windows_sdk = windows_sdk
    run.calls = lambda: (
        [json.loads(line) for line in calls.read_text().splitlines()]
        if calls.exists()
        else []
    )
    return run


def test_bundle_installs_fixed_resources_only_without_building(installer):
    (installer.source / ".env").write_text("private-test-fixture")
    (installer.source / "workspace.credentials.enc.json").write_text("private")
    result = installer()
    assert result.returncode == 0, result.stderr
    assert (installer.destination / "Labcat.exe").read_bytes() == b"native-test-fixture"
    assert set(
        path.relative_to(installer.destination).as_posix()
        for path in installer.destination.rglob("*")
        if path.is_file()
    ) == {
        "Labcat.exe",
        ".labcat-desktop-install",
        ".labcat-install-source",
        "launcher/labcat.ps1",
        "launcher/labcat.cmd",
        "launcher/compose.yaml",
    }
    assert installer.calls() == []


def test_source_install_builds_locked_native_shell_then_installs(installer):
    result = installer(bundled=False)
    assert result.returncode == 0, result.stderr
    calls = installer.calls()
    assert calls == [
        [
            "ci",
            "--prefix",
            str(installer.source / "desktop"),
            "--no-audit",
            "--no-fund",
        ],
        [
            "run",
            "build",
            "--prefix",
            str(installer.source / "desktop"),
            "--",
            "--no-bundle",
            "--",
            "--locked",
        ],
    ]
    assert (installer.destination / "Labcat.exe").is_file()


@pytest.mark.parametrize("failure", ["ci", "run"])
def test_build_failure_cannot_leave_partial_install(installer, failure):
    result = installer(bundled=False, failure=failure)
    assert result.returncode != 0
    assert "failed" in result.stderr
    assert not installer.destination.exists()


def test_local_compose_preserves_original_directory_without_private_files(installer):
    override = "services:\n  labcat:\n    volumes: ['./local-data:/data']\n"
    result = installer(override=override)
    assert result.returncode == 0, result.stderr
    launcher = installer.destination / "launcher"
    assert (launcher / "compose.local.yaml").read_text() == override
    assert (launcher / ".labcat-project-directory").read_text() == str(
        installer.source
    ) + "\n"


def test_reinstall_preserves_existing_original_directory(installer, tmp_path):
    original = tmp_path / "actual workspace source"
    original.mkdir()
    (installer.source / ".labcat-project-directory").write_text(str(original) + "\n")
    result = installer(override="services: {}\n")
    assert result.returncode == 0, result.stderr
    assert (
        installer.destination / "launcher" / ".labcat-project-directory"
    ).read_text() == str(original) + "\n"


def test_unowned_destination_is_never_replaced(installer):
    installer.destination.mkdir(parents=True)
    important = installer.destination / "keep.txt"
    important.write_text("keep")
    result = installer()
    assert result.returncode != 0
    assert "not managed by this installer" in result.stderr
    assert important.read_text() == "keep"
    assert not (installer.destination / "Labcat.exe").exists()


def test_owned_install_can_be_updated_without_staging_residue(installer):
    first = installer()
    assert first.returncode == 0, first.stderr
    second = installer()
    assert second.returncode == 0, second.stderr
    assert list(installer.destination.parent.iterdir()) == [installer.destination]


def test_cross_target_settings_are_rejected_before_build(installer):
    result = installer(
        bundled=False, env_updates={"CARGO_BUILD_TARGET": "wrong-target"}
    )
    assert result.returncode != 0
    assert "Unset CARGO_BUILD_TARGET" in result.stdout
    assert installer.calls() == []
    assert not installer.destination.exists()


def test_missing_native_build_prerequisite_has_actionable_failure(installer):
    for path in installer.fake_bin.glob("cargo*"):
        path.unlink()
    result = installer(bundled=False)
    assert result.returncode != 0
    assert "[missing] cargo not available" in result.stdout
    assert "-Browser" in result.stderr
    assert not installer.destination.exists()


def test_missing_windows_shell_does_not_start_an_unrelated_build(installer):
    result = installer(bundled=True, env_updates={"OS": "Other"})
    assert result.returncode != 0
    assert "Use this installer on Windows" in result.stderr
    assert installer.calls() == []


def test_failed_source_update_leaves_previous_install_intact(installer):
    initial = installer()
    assert initial.returncode == 0, initial.stderr
    installed = installer.destination / "Labcat.exe"
    original = installed.read_bytes()
    (installer.source / "desktop-bin" / "Labcat.exe").unlink()
    result = installer(bundled=False, failure="run")
    assert result.returncode != 0
    assert installed.read_bytes() == original
    assert list(installer.destination.parent.iterdir()) == [installer.destination]


def test_original_project_marker_is_preserved_without_override(installer, tmp_path):
    original = tmp_path / "workspace environment root"
    original.mkdir()
    (installer.source / ".labcat-project-directory").write_text(str(original) + "\n")
    result = installer()
    assert result.returncode == 0, result.stderr
    launcher = installer.destination / "launcher"
    assert (launcher / ".labcat-project-directory").read_text() == str(original) + "\n"
    assert not (launcher / "compose.local.yaml").exists()


def test_windows_check_reports_all_missing_prerequisites_before_build(installer):
    for file in installer.fake_bin.iterdir():
        file.unlink()
    result = installer(
        bundled=False,
        check_only=True,
        env_updates={
            "LABCAT_TEST_WEBVIEW": "missing",
            "LABCAT_TEST_SDK": "missing",
            "PRIVATE_CREDENTIAL_CANARY": "must-not-be-printed",
        },
    )
    assert result.returncode != 0
    for label in (
        "node not available",
        "npm not available",
        "cargo not available",
        "rustc not available",
        "Microsoft Edge WebView2 Runtime",
        "MSVC Rust host",
        "Visual Studio C++ Build Tools",
        "Windows 10/11 SDK",
    ):
        assert f"[missing] {label}" in result.stdout
    assert "must-not-be-printed" not in result.stdout + result.stderr
    assert installer.calls() == []
    assert not installer.destination.parent.exists()


def test_windows_check_lists_versions_and_does_not_build_or_install(installer):
    result = installer(bundled=False, check_only=True)
    assert result.returncode == 0, result.stderr
    for label in (
        "node 24.9.0",
        "cargo 1.88.0",
        "rustc 1.88.0",
        "Microsoft Edge WebView2 Runtime 140.0.3485.54",
        "Visual Studio C++ Build Tools",
        "Windows 10/11 SDK",
    ):
        assert f"[met] {label}" in result.stdout
    assert "Nothing was built or installed" in result.stdout
    assert installer.calls() == []
    assert not installer.destination.parent.exists()


def test_windows_version_and_toolchain_mismatches_are_aggregated(installer):
    result = installer(
        bundled=False,
        check_only=True,
        env_updates={
            "NODE_VERSION": "22.19.0",
            "RUSTC_VERSION": "1.85.0",
            "CARGO_VERSION": "1.87.0",
            "LABCAT_TEST_RUST_HOST": "x86_64-pc-windows-gnu",
        },
    )
    assert result.returncode != 0
    for label in ("node 22.19.0", "cargo 1.87.0", "rustc 1.85.0", "MSVC Rust host"):
        assert f"[missing] {label}" in result.stdout
    assert installer.calls() == []
    assert not installer.destination.exists()


@pytest.mark.parametrize("component", ["compiler", "sdk"])
def test_windows_checks_real_component_files_not_just_registration(
    installer, component
):
    if component == "compiler":
        next(installer.visual_studio.rglob("link.exe")).unlink()
        label = "Visual Studio C++ Build Tools"
    else:
        next(installer.windows_sdk.rglob("kernel32.lib")).unlink()
        label = "Windows 10/11 SDK"
    result = installer(bundled=False, check_only=True)
    assert result.returncode != 0
    assert f"[missing] {label}" in result.stdout
    assert installer.calls() == []


def test_windows_prebuilt_check_only_requires_webview_runtime(installer):
    for file in installer.fake_bin.iterdir():
        file.unlink()
    result = installer(check_only=True, env_updates={"LABCAT_TEST_SDK": "missing"})
    assert result.returncode == 0, result.stderr
    assert "prebuilt native app" in result.stdout
    assert installer.calls() == []
    assert not installer.destination.parent.exists()


@pytest.mark.parametrize("version", ["missing", "0.0.0.0", "not-a-version"])
def test_windows_prebuilt_requires_a_valid_webview_runtime(installer, version):
    result = installer(check_only=True, env_updates={"LABCAT_TEST_WEBVIEW": version})
    assert result.returncode != 0
    assert "[missing] Microsoft Edge WebView2 Runtime" in result.stdout
    assert "install the Microsoft WebView2 Evergreen Runtime" in result.stdout
    assert installer.calls() == []
    assert not installer.destination.exists()


def test_windows_prebuilt_only_never_falls_back_to_source(installer):
    result = installer(bundled=False, prebuilt_only=True)
    assert result.returncode != 0
    assert "No source build was started" in result.stderr
    assert installer.calls() == []
    assert not installer.destination.exists()


def test_windows_source_mode_checks_requirements_even_with_prebuilt(installer):
    for path in installer.fake_bin.glob("cargo*"):
        path.unlink()
    result = installer(build_source=True, check_only=True)
    assert result.returncode != 0
    assert "[missing] cargo not available" in result.stdout
    assert "prebuilt native app;" not in result.stdout
    assert installer.calls() == []
    assert not installer.destination.exists()


def test_windows_incompatible_installer_modes_rejected(installer):
    result = installer(prebuilt_only=True, build_source=True)
    assert result.returncode != 0
    assert "Choose only one" in result.stderr
    assert installer.calls() == []
    assert not installer.destination.exists()
