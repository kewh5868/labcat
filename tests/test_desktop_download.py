"""Offline checks for pinned native downloads and clean release
artifacts."""

import hashlib
import io
import os
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def native_download(tmp_path):
    if os.name == "nt":
        pytest.skip("POSIX host downloader")
    root = tmp_path / "checkout"
    scripts = root / "scripts"
    scripts.mkdir(parents=True)
    shutil.copyfile(
        ROOT / "scripts/download_desktop.sh", scripts / "download_desktop.sh"
    )
    archive = tmp_path / "fixture.tar.gz"
    with tarfile.open(archive, "w:gz") as bundle:
        info = tarfile.TarInfo("labcat-desktop")
        data = b"native fixture, never executed\n"
        info.size = len(data)
        info.mode = 0o755
        bundle.addfile(info, io.BytesIO(data))
    tools = tmp_path / "tools"
    tools.mkdir()
    uname = tools / "uname"
    uname.write_text(
        '#!/bin/sh\ncase "$1" in -s) echo Linux;; -m) echo x86_64;; esac\n'
    )
    uname.chmod(0o755)
    curl = tools / "curl"
    curl.write_text(
        '#!/bin/sh\nprintf "%s\\n" "$@" > "$CURL_CALL"\n'
        'while [ "$#" -gt 0 ]; do\n'
        'if [ "$1" = --output ]; then shift; cp "$FIXTURE_ARCHIVE" "$1"; exit 0; fi\n'
        "shift\ndone\nexit 1\n"
    )
    curl.chmod(0o755)
    env = dict(os.environ)
    env.update(
        PATH=f"{tools}{os.pathsep}{env['PATH']}",
        FIXTURE_ARCHIVE=str(archive),
        CURL_CALL=str(tmp_path / "curl-call"),
    )

    def run(*, checksum=None, entry=None):
        digest = checksum or hashlib.sha256(archive.read_bytes()).hexdigest()
        manifest = entry or (
            "x86_64-unknown-linux-gnu\tnative-v0.1.0-1\t"
            f"Labcat-x86_64-unknown-linux-gnu.tar.gz\t{digest}\n"
        )
        (scripts / "desktop-release.tsv").write_text(manifest)
        return subprocess.run(
            ["sh", str(scripts / "download_desktop.sh")],
            env=env,
            text=True,
            capture_output=True,
            timeout=15,
        )

    return root, archive, env, run


def test_download_verifies_pinned_bytes_without_build_tools(native_download):
    root, _, env, run = native_download
    result = run()
    assert result.returncode == 0, result.stderr
    assert (
        (root / "desktop-bin/labcat-desktop").read_bytes().startswith(b"native fixture")
    )
    assert os.access(root / "desktop-bin/labcat-desktop", os.X_OK)
    arguments = Path(env["CURL_CALL"]).read_text()
    assert "--proto-redir\n=https\n" in arguments
    assert "--max-filesize\n134217728\n" in arguments
    assert not list((root / "desktop-bin").glob(".download.*"))
    assert "No Node, Rust or compiler" in result.stdout


def test_checksum_failure_never_extracts_or_installs(native_download):
    root, _, _, run = native_download
    result = run(checksum="0" * 64)
    assert result.returncode != 0
    assert "checksum mismatch" in result.stderr
    assert not (root / "desktop-bin/labcat-desktop").exists()
    assert not list((root / "desktop-bin").glob(".download.*"))


@pytest.mark.parametrize("kind", ["traversal", "symlink", "outside", "missing"])
def test_even_pinned_archive_must_have_safe_native_layout(native_download, kind):
    root, archive, _, run = native_download
    name = {
        "traversal": "labcat-desktop/../../escaped",
        "symlink": "labcat-desktop",
        "outside": "unexpected",
        "missing": "labcat-desktop/nested",
    }[kind]
    with tarfile.open(archive, "w:gz") as bundle:
        info = tarfile.TarInfo(name)
        if kind == "symlink":
            info.type = tarfile.SYMTYPE
            info.linkname = "/tmp/escaped"
        bundle.addfile(info)
    result = run()
    assert result.returncode != 0
    assert not (root / "escaped").exists()
    assert not (root / "desktop-bin/labcat-desktop").exists()


def test_existing_binary_is_untouched(native_download):
    root, _, env, run = native_download
    (root / "desktop-bin").mkdir()
    target = root / "desktop-bin/labcat-desktop"
    target.write_bytes(b"preserve")
    assert run().returncode != 0
    assert target.read_bytes() == b"preserve"
    assert not Path(env["CURL_CALL"]).exists()


def test_manifest_cannot_redirect_to_arbitrary_repository(native_download):
    _, _, env, run = native_download
    result = run(
        entry="x86_64-unknown-linux-gnu\t../../other\tother.tar.gz\t" + "a" * 64 + "\n"
    )
    assert result.returncode != 0
    assert not Path(env["CURL_CALL"]).exists()


def test_release_builder_preserves_executable_and_rejects_symlinks(tmp_path):
    executable = tmp_path / "labcat-desktop"
    executable.write_bytes(b"clean native fixture")
    executable.chmod(0o755)
    output = tmp_path / "release"
    command = [
        sys.executable,
        str(ROOT / "scripts/build_desktop_release.py"),
        "--target",
        "x86_64-unknown-linux-gnu",
        "--app",
        str(executable),
        "--output",
        str(output),
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    archive = output / "Labcat-x86_64-unknown-linux-gnu.tar.gz"
    with tarfile.open(archive) as bundle:
        assert bundle.getnames() == ["labcat-desktop"]
        assert bundle.getmember("labcat-desktop").mode & 0o111
        assert bundle.extractfile("labcat-desktop").read() == executable.read_bytes()
    assert (
        archive.with_name(archive.name + ".sha256")
        .read_text()
        .startswith(hashlib.sha256(archive.read_bytes()).hexdigest())
    )
    if os.name != "nt":
        executable.unlink()
        executable.symlink_to(tmp_path / "not-native")
        assert subprocess.run(command, capture_output=True, timeout=15).returncode != 0
