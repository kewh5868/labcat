"""Installation bundles contain verified image bytes and only approved
host files."""

import hashlib
import importlib.util
import os
import stat
import zipfile
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "build_install_bundle.py"
SPEC = importlib.util.spec_from_file_location("build_install_bundle", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
bundle_builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bundle_builder)


@pytest.fixture
def bundle_inputs(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    (root / "pyproject.toml").write_text(
        '[project]\nversion = "0.1.0.dev0"\n', encoding="utf-8"
    )
    for name in bundle_builder.HOST_FILES:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"Public install content: {name}\n", encoding="utf-8")
    archive = root / "dist" / "labcat-0.1.0.dev0-linux-arm64.tar"
    archive.parent.mkdir()
    archive.write_bytes(b"FAKE TAR BYTES FOR PACKAGING TEST ONLY\x00\xff")
    expected = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_suffix(".tar.sha256").write_text(
        f"{expected}  {archive.name}\n", encoding="utf-8", newline="\n"
    )
    return root, archive


def test_bundle_has_exact_allowlist_checksum_and_executable_launchers(bundle_inputs):
    root, archive = bundle_inputs
    output_dir = root / "bundles"
    output, checksum = bundle_builder.build_install_bundle(
        archive, output_dir, project_root=root
    )
    assert output == output_dir / f"{archive.stem}.zip"
    expected_names = {
        f"{archive.stem}/{name}"
        for name in (*bundle_builder.HOST_FILES, archive.name, archive.name + ".sha256")
    }
    with zipfile.ZipFile(output) as bundle:
        assert set(bundle.namelist()) == expected_names
        assert bundle.read(f"{archive.stem}/{archive.name}") == archive.read_bytes()
        assert bundle.read(f"{archive.stem}/{archive.name}.sha256") == (
            archive.with_suffix(".tar.sha256").read_bytes()
        )
        assert (
            bundle.read(f"{archive.stem}/docs/deployment.md")
            == (root / "docs/deployment.md").read_bytes()
        )
        for name in bundle_builder.HOST_FILES:
            entry = bundle.getinfo(f"{archive.stem}/{name}")
            permissions = stat.S_IMODE(entry.external_attr >> 16)
            expected_mode = 0o755 if name in bundle_builder.EXECUTABLE_FILES else 0o644
            assert permissions == expected_mode
    assert checksum.read_text(encoding="utf-8") == (
        f"{hashlib.sha256(output.read_bytes()).hexdigest()}  {output.name}\n"
    )


@pytest.mark.parametrize(
    "mutation,error",
    [
        ("missing", "Required regular file"),
        ("corrupt", "does not match"),
        ("missing_checksum", "Required regular file"),
        ("wrong_filename", "name the selected archive"),
        ("multiple_checksums", "exactly one"),
        ("wrong_version", "does not match pyproject"),
    ],
)
def test_invalid_archive_inputs_fail_without_partial_bundle(
    bundle_inputs, mutation, error
):
    root, archive = bundle_inputs
    checksum = archive.with_suffix(".tar.sha256")
    if mutation == "missing":
        archive.unlink()
    elif mutation == "corrupt":
        archive.write_bytes(b"CHANGED FAKE ARCHIVE")
    elif mutation == "missing_checksum":
        checksum.unlink()
    elif mutation == "wrong_filename":
        checksum.write_text("a" * 64 + "  other.tar\n", encoding="utf-8")
    elif mutation == "multiple_checksums":
        checksum.write_text(checksum.read_text() * 2, encoding="utf-8")
    elif mutation == "wrong_version":
        (root / "pyproject.toml").write_text(
            '[project]\nversion = "9.0.0"\n', encoding="utf-8"
        )
    with pytest.raises(bundle_builder.BundleError, match=error):
        bundle_builder.build_install_bundle(archive, project_root=root)
    assert not list(archive.parent.glob("*.zip"))
    assert not list(archive.parent.glob("*.tmp"))


def test_bundle_does_not_collect_private_or_unlisted_files(bundle_inputs):
    root, archive = bundle_inputs
    secret = b"PRIVATE_VALUE_MUST_NOT_BE_BUNDLED"
    for name in (
        ".env",
        "LOCAL_BRIEF.md",
        ".aws/credentials",
        "config/site.local.toml",
        "docs/private-notes.md",
        "dist/other-image.tar",
    ):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(secret)
    output, _ = bundle_builder.build_install_bundle(archive, project_root=root)
    with zipfile.ZipFile(output) as bundle:
        for name in bundle.namelist():
            assert secret not in bundle.read(name)


def test_missing_required_launcher_is_not_silently_omitted(bundle_inputs):
    root, archive = bundle_inputs
    (root / "labcat.cmd").unlink()
    with pytest.raises(bundle_builder.BundleError, match="labcat.cmd"):
        bundle_builder.build_install_bundle(archive, project_root=root)


def make_desktop_app(root, host):
    desktop_app = root / "native" / bundle_builder.DESKTOP_NAMES[host]
    desktop_app.parent.mkdir(exist_ok=True)
    if host == "macos":
        binary = desktop_app / "Contents" / "MacOS" / "labcat-desktop"
        binary.parent.mkdir(parents=True)
        (desktop_app / "Contents" / "Resources").mkdir()
        (desktop_app / "Contents" / "Info.plist").write_text(
            "Fake app metadata for packaging tests only.", encoding="utf-8"
        )
    else:
        binary = desktop_app
    binary.write_bytes(b"FAKE NATIVE EXECUTABLE FOR PACKAGING TEST ONLY")
    binary.chmod(0o755)
    return desktop_app, binary


def test_macos_bundle_preserves_explicit_app_tree_and_executable(bundle_inputs):
    root, archive = bundle_inputs
    desktop_app, binary = make_desktop_app(root, "macos")
    # Adjacent build files are not part of the explicitly selected app tree.
    (desktop_app.parent / "private-build-notes.txt").write_text(
        "PRIVATE_BUILD_NOTES", encoding="utf-8"
    )
    output, checksum = bundle_builder.build_install_bundle(
        archive, project_root=root, desktop_app=desktop_app, host="macos"
    )
    prefix = "labcat-0.1.0.dev0-macos-arm64"
    assert output.name == f"{prefix}.zip"
    native_prefix = f"{prefix}/desktop-bin/Labcat.app"
    with zipfile.ZipFile(output) as bundle:
        expected_native = {
            f"{native_prefix}/",
            f"{native_prefix}/Contents/",
            f"{native_prefix}/Contents/MacOS/",
            f"{native_prefix}/Contents/Resources/",
            f"{native_prefix}/Contents/MacOS/labcat-desktop",
            f"{native_prefix}/Contents/Info.plist",
        }
        assert set(bundle.namelist()) == expected_native | {
            f"{prefix}/{name}"
            for name in (
                *bundle_builder.HOST_FILES,
                archive.name,
                archive.name + ".sha256",
            )
        }
        binary_name = f"{native_prefix}/Contents/MacOS/labcat-desktop"
        assert bundle.read(binary_name) == binary.read_bytes()
        assert stat.S_IMODE(bundle.getinfo(binary_name).external_attr >> 16) == 0o755
        assert bundle.getinfo(f"{native_prefix}/Contents/Resources/").is_dir()
        assert bundle.read(f"{prefix}/{archive.name}") == archive.read_bytes()
        assert bundle.read(f"{prefix}/{archive.name}.sha256") == (
            archive.with_suffix(".tar.sha256").read_bytes()
        )
        assert all("PRIVATE_BUILD_NOTES" not in name for name in bundle.namelist())
    assert checksum.read_text() == (
        f"{hashlib.sha256(output.read_bytes()).hexdigest()}  {output.name}\n"
    )


@pytest.mark.parametrize("host", ["windows", "linux"])
def test_native_file_bundle_preserves_name_bytes_and_permissions(bundle_inputs, host):
    root, archive = bundle_inputs
    desktop_app, binary = make_desktop_app(root, host)
    binary.chmod(0o700)
    for parent in (root, desktop_app.parent):
        private_launcher_dir = parent / "launcher"
        private_launcher_dir.mkdir()
        (private_launcher_dir / "private.env").write_text(
            "PRIVATE_LAUNCHER_DIRECTORY_CONTENT", encoding="utf-8"
        )
    output, _ = bundle_builder.build_install_bundle(
        archive, project_root=root, desktop_app=desktop_app, host=host
    )
    prefix = f"labcat-0.1.0.dev0-{host}-arm64"
    assert output.name == f"{prefix}.zip"
    with zipfile.ZipFile(output) as bundle:
        name = f"{prefix}/desktop-bin/{desktop_app.name}"
        assert bundle.read(name) == binary.read_bytes()
        expected_mode = 0o755 if os.name == "nt" else 0o700
        assert stat.S_IMODE(bundle.getinfo(name).external_attr >> 16) == expected_mode
        expected_resources = {"labcat.sh", "labcat.ps1", "compose.yaml"}
        assert set(bundle.namelist()) == {
            f"{prefix}/{host_file}"
            for host_file in (
                *bundle_builder.HOST_FILES,
                archive.name,
                archive.name + ".sha256",
            )
        } | {name} | {
            f"{prefix}/desktop-bin/launcher/{resource}"
            for resource in expected_resources
        }
        for resource in expected_resources:
            entry = bundle.getinfo(f"{prefix}/desktop-bin/launcher/{resource}")
            assert bundle.read(entry) == (root / resource).read_bytes()
            expected_mode = 0o755 if resource == "labcat.sh" else 0o644
            assert stat.S_IMODE(entry.external_attr >> 16) == expected_mode


@pytest.mark.parametrize(
    "mutation,error",
    [
        ("missing_host", "supplied together"),
        ("missing_app", "supplied together"),
        ("invalid_host", "macos, windows, or linux"),
        ("wrong_name", "Expected desktop input named"),
        ("file_instead_of_app", "must be an .app directory"),
        ("missing_input", "must be an .app directory"),
        ("output_inside_app", "outside the selected desktop app"),
        ("unsafe_child", "unsafe archive filename"),
    ],
)
def test_native_argument_errors_leave_no_partial_bundle(bundle_inputs, mutation, error):
    root, archive = bundle_inputs
    desktop_app, _ = make_desktop_app(root, "macos")
    host = "macos"
    output_dir = root / "bundles"
    if mutation == "missing_host":
        host = None
    elif mutation == "missing_app":
        desktop_app = None
    elif mutation == "invalid_host":
        host = "unsupported"
    elif mutation == "wrong_name":
        desktop_app = desktop_app.with_name("Unexpected.app")
    elif mutation == "file_instead_of_app":
        desktop_app = root / "Labcat.app"
        desktop_app.write_bytes(b"NOT AN APP DIRECTORY")
    elif mutation == "missing_input":
        desktop_app = root / "missing" / "Labcat.app"
    elif mutation == "output_inside_app":
        output_dir = desktop_app / "bundles"
    elif mutation == "unsafe_child":
        # DEL is creatable on both Windows and Unix, but unsafe in an archive.
        (desktop_app / "unsafe\x7f.txt").write_text("unsafe", encoding="utf-8")
    with pytest.raises(bundle_builder.BundleError, match=error):
        bundle_builder.build_install_bundle(
            archive,
            output_dir,
            project_root=root,
            desktop_app=desktop_app,
            host=host,
        )
    assert not output_dir.exists()


@pytest.mark.parametrize("location", ["app", "parent", "child", "directory_child"])
def test_native_bundle_rejects_symlinks(bundle_inputs, location):
    root, archive = bundle_inputs
    desktop_app, binary = make_desktop_app(root, "macos")
    if location == "app":
        reference = root / desktop_app.name
        reference.symlink_to(desktop_app, target_is_directory=True)
        desktop_app = reference
    elif location == "parent":
        reference = root / "native-link"
        reference.symlink_to(desktop_app.parent, target_is_directory=True)
        desktop_app = reference / desktop_app.name
    elif location == "child":
        binary.unlink()
        binary.symlink_to(root / "README.md")
    else:
        (desktop_app / "external-data").symlink_to(
            root / "docs", target_is_directory=True
        )
    with pytest.raises(bundle_builder.BundleError, match="symlink"):
        bundle_builder.build_install_bundle(
            archive, project_root=root, desktop_app=desktop_app, host="macos"
        )
    assert not list(archive.parent.glob("*.zip"))
    assert not list(archive.parent.glob("*.tmp"))


def test_native_bundle_rejects_parent_traversal(bundle_inputs):
    root, archive = bundle_inputs
    desktop_app, _ = make_desktop_app(root, "macos")
    traversing = desktop_app / ".." / desktop_app.name
    with pytest.raises(bundle_builder.BundleError, match="parent traversal"):
        bundle_builder.build_install_bundle(
            archive, project_root=root, desktop_app=traversing, host="macos"
        )


def test_native_bundle_still_verifies_image_checksum(bundle_inputs):
    root, archive = bundle_inputs
    desktop_app, _ = make_desktop_app(root, "macos")
    archive.write_bytes(b"CORRUPTED IMAGE")
    with pytest.raises(bundle_builder.BundleError, match="does not match"):
        bundle_builder.build_install_bundle(
            archive, project_root=root, desktop_app=desktop_app, host="macos"
        )
    assert not list(archive.parent.glob("*.zip"))


def test_installed_private_deployment_is_not_published(bundle_inputs):
    root, archive = bundle_inputs
    desktop_app, _ = make_desktop_app(root, "macos")
    override = desktop_app / "Contents/Resources/launcher/compose.local.yaml"
    override.parent.mkdir()
    override.write_text("PRIVATE_DEPLOYMENT_ONLY", encoding="utf-8")
    with pytest.raises(bundle_builder.BundleError, match="private deployment"):
        bundle_builder.build_install_bundle(
            archive, project_root=root, desktop_app=desktop_app, host="macos"
        )
    assert not list(archive.parent.glob("*.zip"))


def test_cli_rejects_unsupported_native_host(bundle_inputs, capsys):
    _, archive = bundle_inputs
    with pytest.raises(SystemExit) as failure:
        bundle_builder.main([str(archive), "--host", "unsupported"])
    assert failure.value.code == 2
    assert "invalid choice" in capsys.readouterr().err


def test_windows_checksum_line_endings_are_accepted_and_normalized(bundle_inputs):
    root, archive = bundle_inputs
    checksum = archive.with_suffix(".tar.sha256")
    line = checksum.read_text(encoding="utf-8").strip()
    checksum.write_bytes((line + "\r\n").encode("utf-8"))
    output, _ = bundle_builder.build_install_bundle(archive, project_root=root)
    with zipfile.ZipFile(output) as bundle:
        assert bundle.read(f"{archive.stem}/{archive.name}.sha256") == (
            line + "\n"
        ).encode("utf-8")
