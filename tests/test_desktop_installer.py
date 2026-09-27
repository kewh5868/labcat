"""Offline POSIX native installation scenarios; no OS tools or Docker
required."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(os.name == "nt", reason="POSIX installer")


@pytest.fixture
def installer(tmp_path):
    source = tmp_path / "checkout with spaces"
    (source / "scripts").mkdir(parents=True)
    shutil.copy(ROOT / "scripts/install_desktop.sh", source / "scripts")
    shutil.copy(ROOT / "labcat.sh", source)
    shutil.copy(ROOT / "compose.yaml", source)
    tools = tmp_path / "tools"
    tools.mkdir()
    log = tmp_path / "calls.jsonl"
    stub = (
        f"#!{sys.executable}\n"
        "import json, os, sys, subprocess\n"
        "from pathlib import Path\n"
        "name = Path(sys.argv[0]).name\n"
        "with open(os.environ['CALL_LOG'], 'a') as f:\n"
        "    f.write(json.dumps([name, *sys.argv[1:]]) + '\\n')\n"
        "if name == 'uname': print(os.environ.get('TEST_PLATFORM', 'Darwin'))\n"
        "if name == 'codesign': sys.exit(int(os.environ.get('SIGN_EXIT', '0')))\n"
        "if name == 'mv':\n"
        "    source = sys.argv[1]\n"
        "    if os.environ.get('FAIL_SWAP') and '.labcat-install.' in source:\n"
        "        if Path(source).name == 'Labcat.app': sys.exit(1)\n"
        "        if os.environ.get('FAIL_RESTORE') and "
        "Path(source).name == 'previous': sys.exit(1)\n"
        "    sys.exit(subprocess.run(['/bin/mv', *sys.argv[1:]]).returncode)\n"
        "if name == 'npm':\n"
        "    sys.exit(int(os.environ.get('NPM_EXIT', '0')))\n"
    )
    for name in (
        "uname",
        "codesign",
        "node",
        "npm",
        "cargo",
        "rustc",
        "xcode-select",
        "cc",
        "pkg-config",
        "mv",
    ):
        path = tools / name
        path.write_text(stub)
        path.chmod(0o755)
    env = {
        **os.environ,
        "PATH": str(tools) + os.pathsep + os.environ["PATH"],
        "LABCAT_DESKTOP_INSTALL_DIR": str(tmp_path / "user apps"),
        "CALL_LOG": str(log),
    }
    for key in ("CARGO_TARGET_DIR", "CARGO_BUILD_TARGET"):
        env.pop(key, None)

    def native(platform="Darwin", built=False):
        if platform == "Darwin":
            app = source / (
                "desktop/target/release/bundle/macos/Labcat.app"
                if built
                else "desktop-bin/Labcat.app"
            )
            binary = app / "Contents/MacOS/labcat-desktop"
            (app / "Contents/Resources/launcher").mkdir(parents=True)
            (app / "Contents/Resources/launcher/stale-secret").write_text("not copied")
        else:
            binary = source / (
                "desktop/target/release/labcat-desktop"
                if built
                else "desktop-bin/labcat-desktop"
            )
        binary.parent.mkdir(parents=True, exist_ok=True)
        binary.write_text("#!/bin/sh\nexit 0\n")
        binary.chmod(0o755)
        return binary

    def run(**overrides):
        result = subprocess.run(
            ["sh", str(source / "scripts/install_desktop.sh")],
            cwd=tmp_path,
            env={**env, **overrides},
            capture_output=True,
            text=True,
            timeout=20,
        )
        calls = (
            [json.loads(line) for line in log.read_text().splitlines()]
            if log.exists()
            else []
        )
        return result, calls

    run.native = native
    run.destination = Path(env["LABCAT_DESKTOP_INSTALL_DIR"])
    return run, source


@pytest.mark.parametrize("platform", ["Darwin", "Linux"])
def test_native_bundle_installs_fixed_resources_without_build_tools(
    installer, platform
):
    run, source = installer
    run.native(platform)
    (source / "compose.local.yaml").write_text("services: {}\n")
    (source / ".env").write_text("PRIVATE_TEST=not-for-installation\n")
    result, calls = run(TEST_PLATFORM=platform)
    assert result.returncode == 0, result.stderr
    if platform == "Darwin":
        app = run.destination / "Labcat.app"
        resources = app / "Contents/Resources/launcher"
        assert ["codesign", "--force", "--deep", "--sign", "-", str(app)] not in calls
        assert any(
            call[:4] == ["codesign", "--verify", "--deep", "--strict"] for call in calls
        )
    else:
        app = run.destination / "desktop"
        resources = app / "launcher"
        entry = (run.destination / "applications/labcat.desktop").read_text()
        assert f'Exec="{app}/labcat-desktop"' in entry
    assert (resources / "labcat.sh").read_bytes() == (source / "labcat.sh").read_bytes()
    assert (resources / "compose.yaml").read_bytes() == (
        source / "compose.yaml"
    ).read_bytes()
    assert (resources / "compose.local.yaml").read_bytes() == (
        source / "compose.local.yaml"
    ).read_bytes()
    assert (resources / ".labcat-project-directory").read_text() == str(source) + "\n"
    assert not (resources / "stale-secret").exists()
    assert not any(path.name == ".env" for path in app.rglob("*"))
    assert not any(call[0] in ("npm", "cargo") for call in calls)
    assert not list(run.destination.glob(".labcat-install.*"))


@pytest.mark.parametrize("platform", ["Darwin", "Linux"])
def test_source_build_uses_both_dependency_locks(installer, platform):
    run, source = installer
    run.native(platform, built=True)
    for name in ("package-lock.json", "Cargo.lock", "tauri.conf.json"):
        (source / "desktop" / name).write_text("{}\n")
    result, calls = run(TEST_PLATFORM=platform)
    assert result.returncode == 0, result.stderr
    assert [
        "npm",
        "ci",
        "--prefix",
        str(source / "desktop"),
        "--ignore-scripts",
    ] in calls
    build = next(call for call in calls if call[:3] == ["npm", "run", "build"])
    assert build[-2:] == ["--", "--locked"]
    assert ("--bundles" if platform == "Darwin" else "--no-bundle") in build


@pytest.mark.parametrize("failure", ["build", "signature"])
def test_failure_preserves_existing_application(installer, failure):
    run, source = installer
    if failure == "build":
        run.native(built=True)
        for name in ("package-lock.json", "Cargo.lock", "tauri.conf.json"):
            (source / "desktop" / name).write_text("{}\n")
    else:
        run.native()
    app = run.destination / "Labcat.app"
    app.mkdir(parents=True)
    (app / "Contents/Resources").mkdir(parents=True)
    (app / "Contents/Resources/.labcat-managed-install").write_text(
        "labcat-desktop-v1\n"
    )
    (app / "old-working-version").write_text("preserved")
    result, _ = run(**({"NPM_EXIT": "1"} if failure == "build" else {"SIGN_EXIT": "1"}))
    assert result.returncode != 0
    assert (app / "old-working-version").read_text() == "preserved"
    assert not list(run.destination.glob(".labcat-install.*"))


def test_unrelated_application_and_symlink_destination_are_not_replaced(
    installer, tmp_path
):
    run, _ = installer
    run.native()
    app = run.destination / "Labcat.app"
    app.mkdir(parents=True)
    (app / "unrelated").write_text("keep")
    result, _ = run()
    assert result.returncode != 0
    assert "not a recognized Labcat app" in result.stderr
    assert (app / "unrelated").read_text() == "keep"
    shutil.rmtree(app)
    target = tmp_path / "other app"
    target.mkdir()
    app.symlink_to(target, target_is_directory=True)
    result, _ = run()
    assert result.returncode != 0
    assert "symbolic link" in result.stderr
    assert target.is_dir()


@pytest.mark.parametrize("key", ["CARGO_BUILD_TARGET", "CARGO_TARGET_DIR"])
def test_source_build_rejects_target_override_instead_of_installing_stale_output(
    installer, key
):
    run, _ = installer
    run.native(built=True)
    result, calls = run(**{key: "custom"})
    assert result.returncode != 0
    assert "Unset CARGO_BUILD_TARGET and CARGO_TARGET_DIR" in result.stderr
    assert not any(call[0] == "npm" for call in calls)
    assert not (run.destination / "Labcat.app").exists()


def test_local_override_symlink_is_not_copied(installer, tmp_path):
    run, source = installer
    run.native()
    target = tmp_path / "override"
    target.write_text("services: {}\n")
    (source / "compose.local.yaml").symlink_to(target)
    result, _ = run()
    assert result.returncode != 0
    assert "regular file" in result.stderr
    assert not (run.destination / "Labcat.app").exists()


def test_source_without_prerequisites_explains_browser_alternative(installer):
    run, _ = installer
    # A bundle without native code cannot claim a desktop installation.
    result, _ = run()
    assert result.returncode != 0
    assert "--browser" in result.stderr
    assert not (run.destination / "Labcat.app").exists()


def test_failed_rollback_preserves_previous_app_for_manual_recovery(installer):
    run, _ = installer
    run.native()
    app = run.destination / "Labcat.app"
    app.mkdir(parents=True)
    (app / "Contents/Resources").mkdir(parents=True)
    (app / "Contents/Resources/.labcat-managed-install").write_text(
        "labcat-desktop-v1\n"
    )
    (app / "old-working-version").write_text("preserved")
    result, _ = run(FAIL_SWAP="1", FAIL_RESTORE="1")
    assert result.returncode != 0
    backups = list(run.destination.glob(".labcat-install.*/previous"))
    assert len(backups) == 1
    assert (backups[0] / "old-working-version").read_text() == "preserved"
    assert str(backups[0]) in result.stderr


def test_failed_swap_restores_previous_application(installer):
    run, _ = installer
    run.native()
    app = run.destination / "Labcat.app"
    app.mkdir(parents=True)
    (app / "Contents/Resources").mkdir(parents=True)
    (app / "Contents/Resources/.labcat-managed-install").write_text(
        "labcat-desktop-v1\n"
    )
    (app / "old-working-version").write_text("preserved")
    result, _ = run(FAIL_SWAP="1")
    assert result.returncode != 0
    assert (app / "old-working-version").read_text() == "preserved"
    assert not list(run.destination.glob(".labcat-install.*"))


@pytest.mark.parametrize("platform", ["Darwin", "Linux"])
def test_reinstallation_preserves_original_relative_path_base(
    installer, tmp_path, platform
):
    run, source = installer
    run.native(platform)
    original = tmp_path / "original deployment with spaces"
    original.mkdir()
    (source / ".labcat-project-directory").write_text(str(original) + "\n")
    (source / "compose.local.yaml").write_text("services: {}\n")
    result, _ = run(TEST_PLATFORM=platform)
    assert result.returncode == 0, result.stderr
    resources = run.destination / (
        "Labcat.app/Contents/Resources/launcher"
        if platform == "Darwin"
        else "desktop/launcher"
    )
    assert (resources / ".labcat-project-directory").read_text() == str(original) + "\n"


def test_invalid_existing_deployment_setting_does_not_install(installer, tmp_path):
    run, source = installer
    run.native()
    (source / ".labcat-project-directory").write_text(str(tmp_path) + "\nextra")
    result, _ = run()
    assert result.returncode != 0
    assert "deployment directory setting is invalid" in result.stderr
    assert not (run.destination / "Labcat.app").exists()
