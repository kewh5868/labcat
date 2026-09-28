"""Run the real PowerShell downloader against an offline loopback
fixture.

Only the fixed origin is replaced in a disposable script copy.
Production URLs, artifact names and digests still come only from the
checked-in manifest.
"""

import hashlib
import io
import os
import shutil
import stat
import subprocess
import threading
import zipfile
from contextlib import nullcontext
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
POWERSHELL = shutil.which("powershell") or shutil.which("pwsh")
pytestmark = pytest.mark.skipif(
    POWERSHELL is None, reason="PowerShell is not installed on this host"
)
ORIGIN = "https://github.com/kewh5868/labcat/releases/download/"
TARGET = "x86_64-pc-windows-msvc"
ASSET = f"Labcat-{TARGET}.zip"


def native_archive(entries=None):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content, mode in entries or [("Labcat.exe", b"native-fixture", None)]:
            entry = zipfile.ZipInfo(name)
            entry.compress_type = zipfile.ZIP_DEFLATED
            if mode is not None:
                entry.create_system = 3
                entry.external_attr = mode << 16
            archive.writestr(entry, content)
    return buffer.getvalue()


@pytest.fixture
def downloader(tmp_path):
    payload = {"body": native_archive(), "status": 200, "length": None}
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            self.send_response(payload["status"])
            if payload["length"] != "omit":
                self.send_header(
                    "Content-Length", payload["length"] or str(len(payload["body"]))
                )
            self.end_headers()
            try:
                self.wfile.write(payload["body"])
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    source = tmp_path / "download checkout with spaces"
    scripts = source / "scripts"
    scripts.mkdir(parents=True)
    script = scripts / "download_desktop.ps1"
    original = (ROOT / "scripts/download_desktop.ps1").read_text()
    assert original.count(ORIGIN) == 1
    script.write_text(
        original.replace(ORIGIN, f"http://127.0.0.1:{server.server_port}/")
    )
    manifest = scripts / "desktop-release.tsv"

    def run(*, archive=None, manifest_text=None, status=200, length=None, env=None):
        payload["body"] = archive if archive is not None else native_archive()
        payload["status"] = status
        payload["length"] = length
        digest = hashlib.sha256(payload["body"]).hexdigest()
        manifest.write_text(
            manifest_text
            if manifest_text is not None
            else f"{TARGET}\tnative-v0.1.0-1\t{ASSET}\t{digest}\n"
        )
        return subprocess.run(
            [POWERSHELL, "-NoProfile", "-NonInteractive", "-File", str(script)],
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "OS": "Windows_NT",
                "PROCESSOR_ARCHITECTURE": "AMD64",
                "PROCESSOR_ARCHITEW6432": "",
                **(env or {}),
            },
            timeout=30,
            check=False,
        )

    run.source = source
    run.manifest = manifest
    run.native = source / "desktop-bin/Labcat.exe"
    run.requests = requests
    run.script = script
    yield run
    server.shutdown()
    server.server_close()
    thread.join()


def test_download_verifies_and_installs_only_pinned_native_binary(downloader):
    result = downloader(env={"PRIVATE_CREDENTIAL_CANARY": "do-not-copy-or-print"})
    assert result.returncode == 0, result.stderr
    assert downloader.native.read_bytes() == b"native-fixture"
    assert downloader.requests == [f"/native-v0.1.0-1/{ASSET}"]
    assert "No Node, Rust or compiler was used" in result.stdout
    assert "do-not-copy-or-print" not in result.stdout + result.stderr
    assert list(downloader.native.parent.iterdir()) == [downloader.native]
    assert not list(downloader.source.glob(".labcat-desktop-download-*"))


def test_existing_native_shell_is_never_overwritten(downloader):
    downloader.native.parent.mkdir()
    downloader.native.write_bytes(b"existing-native")
    result = downloader()
    assert result.returncode == 0, result.stderr
    assert downloader.native.read_bytes() == b"existing-native"
    assert downloader.requests == []


@pytest.mark.parametrize(
    "record",
    [
        "bad row",
        f"{TARGET}\t../../other\t{ASSET}\t" + "a" * 64,
        f"{TARGET}\tnative-v1\tunrelated.zip\t" + "a" * 64,
        f"{TARGET}\tnative-v1\t{ASSET}\tbad-checksum",
        f"{TARGET}\tnative-v1\t{ASSET}\t"
        + "a" * 64
        + "\n"
        + f"{TARGET}\tnative-v1\t{ASSET}\t"
        + "b" * 64,
        "# No matching release yet\n",
    ],
)
def test_untrusted_or_unavailable_manifest_fails_before_network(downloader, record):
    result = downloader(manifest_text=record)
    assert result.returncode != 0
    assert downloader.requests == []
    assert not downloader.native.exists()
    assert not list(downloader.source.glob(".labcat-desktop-download-*"))


def test_checksum_failure_leaves_no_native_file_or_download(downloader):
    result = downloader(manifest_text=f"{TARGET}\tnative-v1\t{ASSET}\t" + "0" * 64)
    assert result.returncode != 0
    assert "checksum verification failed" in result.stderr
    assert not downloader.native.exists()
    assert not list(downloader.source.glob(".labcat-desktop-download-*"))


@pytest.mark.parametrize(
    "entries",
    [
        [("../Labcat.exe", b"bad", None)],
        [("nested/Labcat.exe", b"bad", None)],
        [("Labcat.exe", b"", None)],
        [("Labcat.exe", b"target", stat.S_IFLNK | 0o777)],
        [("Labcat.exe", b"directory", stat.S_IFDIR | 0o755)],
        [("Labcat.exe", b"native", None), ("extra.txt", b"extra", None)],
        [("Labcat.exe", b"native", None), ("Labcat.exe", b"duplicate", None)],
    ],
)
def test_invalid_archive_entries_fail_closed(downloader, entries):
    with (
        pytest.warns(UserWarning)
        if len(entries) == 2 and entries[1][0] == "Labcat.exe"
        else nullcontext()
    ):
        archive = native_archive(entries)
    result = downloader(archive=archive)
    assert result.returncode != 0
    assert "native archive" in result.stderr
    assert not downloader.native.exists()
    assert not list(downloader.source.glob(".labcat-desktop-download-*"))


def test_http_failure_cannot_install(downloader):
    result = downloader(status=404)
    assert result.returncode != 0
    assert not downloader.native.exists()
    assert not list(downloader.source.glob(".labcat-desktop-download-*"))


def test_large_download_is_rejected_before_body_read(downloader):
    result = downloader(length=str(129 * 1024 * 1024))
    assert result.returncode != 0
    assert "exceeds the permitted size" in result.stderr
    assert not downloader.native.exists()
    assert not list(downloader.source.glob(".labcat-desktop-download-*"))


def test_unsupported_architecture_does_not_download_an_unrelated_binary(downloader):
    result = downloader(env={"PROCESSOR_ARCHITECTURE": "ARM64"})
    assert result.returncode != 0
    assert "matching native Windows bundle is not available" in result.stderr
    assert downloader.requests == []


def test_production_origin_has_no_user_url_override():
    source = (ROOT / "scripts/download_desktop.ps1").read_text()
    assert source.count(ORIGIN) == 1
    assert "$env:LABCAT_DESKTOP_URL" not in source
    assert "ServerCertificateCustomValidationCallback" not in source


def test_download_stream_is_bounded_without_content_length(downloader):
    downloader.script.write_text(
        downloader.script.read_text().replace(
            "$maximumBytes = 128MB", "$maximumBytes = 4096"
        )
    )
    result = downloader(archive=b"invalid archive" * 500, length="omit")
    assert result.returncode != 0
    assert "exceeds the permitted size" in result.stderr
    assert not downloader.native.exists()
    assert not list(downloader.source.glob(".labcat-desktop-download-*"))


def test_compressed_executable_is_bounded_before_extraction(downloader):
    downloader.script.write_text(
        downloader.script.read_text().replace(
            "$maximumBytes = 128MB", "$maximumBytes = 4096"
        )
    )
    archive = native_archive([("Labcat.exe", b"a" * 8192, None)])
    assert len(archive) < 4096
    result = downloader(archive=archive)
    assert result.returncode != 0
    assert "invalid executable entry" in result.stderr
    assert not downloader.native.exists()
    assert not list(downloader.source.glob(".labcat-desktop-download-*"))


def test_invalid_zip_cannot_leave_a_partial_download(downloader):
    result = downloader(archive=b"not a ZIP archive")
    assert result.returncode != 0
    assert not downloader.native.exists()
    assert not list(downloader.source.glob(".labcat-desktop-download-*"))


def test_framework_digest_works_with_an_invalid_inherited_module_path(downloader):
    result = downloader(
        env={"PSModulePath": str(downloader.source / "missing-modules")}
    )
    assert result.returncode == 0, result.stderr
    assert downloader.native.read_bytes() == b"native-fixture"
    assert "Get-FileHash" not in (ROOT / "scripts/download_desktop.ps1").read_text()
