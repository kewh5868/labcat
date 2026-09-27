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

            args = sys.argv[1:]
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
    for command in ("node", "npm", "cargo"):
        if os.name == "nt":
            (fake_bin / (command + ".cmd")).write_text(
                f'@"{sys.executable}" "{build_script}" %*\n', encoding="utf-8"
            )
        else:
            path = fake_bin / command
            path.write_text(
                f"#!{sys.executable}\n"
                f"exec(compile(open({str(build_script)!r}).read(), "
                f"{str(build_script)!r}, 'exec'))\n",
                encoding="utf-8",
            )
            path.chmod(0o755)

    def run(*, bundled=True, failure=None, override=None, env_updates=None):
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
                str(ROOT / "scripts" / "install_desktop.ps1"),
                "-SourceRoot",
                str(source),
                "-Destination",
                str(destination),
                "-NoShortcut",
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
    assert "Unset CARGO_BUILD_TARGET" in result.stderr
    assert installer.calls() == []
    assert not installer.destination.exists()


def test_missing_native_build_prerequisite_has_actionable_failure(installer):
    for path in installer.fake_bin.glob("cargo*"):
        path.unlink()
    result = installer(bundled=False)
    assert result.returncode != 0
    assert "Building the Windows desktop shell requires" in result.stderr
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
