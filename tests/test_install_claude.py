"""Native agent downloads remain pinned and never replace a verified
binary on failure."""

import hashlib
import importlib.util
import io
import os
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/install_claude.py"
spec = importlib.util.spec_from_file_location("install_claude", SCRIPT)
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)
BINARY = b"inert native-release fixture, never executable"


@pytest.fixture
def release(monkeypatch):
    records = {
        arch: {
            **metadata,
            "size": len(BINARY),
            "sha256": hashlib.sha256(BINARY).hexdigest(),
        }
        for arch, metadata in installer.RELEASES.items()
    }
    monkeypatch.setattr(installer, "RELEASES", records)
    monkeypatch.setattr(installer, "CHUNK_BYTES", 8)
    return records


@pytest.mark.parametrize(
    "architecture,platform", [("arm64", "linux-arm64"), ("amd64", "linux-x64")]
)
def test_installs_exact_pinned_binary_using_bounded_reads(
    tmp_path, monkeypatch, release, architecture, platform
):
    requests, reads = [], []

    class Response(io.BytesIO):
        def read(self, size=-1):
            reads.append(size)
            return super().read(size)

    def download(url, timeout):
        requests.append((url, timeout))
        return Response(BINARY)

    monkeypatch.setattr(installer, "urlopen", download)
    output = tmp_path / "agents"
    installer.install(architecture, output)
    assert (output / "claude").read_bytes() == BINARY
    assert requests == [
        (
            "https://downloads.claude.ai/claude-code-releases/"
            f"{installer.CLAUDE_VERSION}/{platform}/claude",
            120,
        )
    ]
    assert reads and all(0 < size <= 8 for size in reads)
    assert list(output.iterdir()) == [output / "claude"]
    if os.name != "nt":
        assert (output / "claude").stat().st_mode & 0o777 == 0o755


@pytest.mark.parametrize(
    "body,message",
    [
        (BINARY[:-1], "pinned size"),
        (BINARY + b"x", "exceeds"),
        (b"x" * len(BINARY), "SHA256"),
    ],
)
def test_invalid_download_preserves_existing_install_and_removes_temporary_file(
    tmp_path, monkeypatch, release, body, message
):
    target = tmp_path / "claude"
    target.write_bytes(b"previous verified fixture")
    monkeypatch.setattr(installer, "urlopen", lambda *a, **k: io.BytesIO(body))
    with pytest.raises(RuntimeError, match=message):
        installer.install("arm64", tmp_path)
    assert target.read_bytes() == b"previous verified fixture"
    assert list(tmp_path.iterdir()) == [target]


def test_interrupted_download_cleans_partial_file_without_replacing_install(
    tmp_path, monkeypatch, release
):
    target = tmp_path / "claude"
    target.write_bytes(b"previous verified fixture")

    class Interrupted(io.BytesIO):
        def read(self, size=-1):
            if self.tell():
                raise OSError("Synthetic interrupted transfer")
            return super().read(size)

    monkeypatch.setattr(installer, "urlopen", lambda *a, **k: Interrupted(BINARY))
    with pytest.raises(OSError, match="interrupted"):
        installer.install("amd64", tmp_path)
    assert target.read_bytes() == b"previous verified fixture"
    assert list(tmp_path.iterdir()) == [target]


def test_replace_failure_cleans_verified_temporary_file(tmp_path, monkeypatch, release):
    target = tmp_path / "claude"
    target.write_bytes(b"previous verified fixture")
    monkeypatch.setattr(installer, "urlopen", lambda *a, **k: io.BytesIO(BINARY))

    def failed_replace(*args):
        raise OSError("Synthetic replace failure")

    monkeypatch.setattr(installer.os, "replace", failed_replace)
    with pytest.raises(OSError, match="replace"):
        installer.install("arm64", tmp_path)
    assert target.read_bytes() == b"previous verified fixture"
    assert list(tmp_path.iterdir()) == [target]


@pytest.mark.parametrize("architecture", ["x86", "x64", "darwin-arm64", "../arm64"])
def test_unsupported_architecture_never_starts_download(
    tmp_path, monkeypatch, architecture
):
    monkeypatch.setattr(
        installer, "urlopen", lambda *a, **k: pytest.fail("Unexpected download")
    )
    with pytest.raises(ValueError, match="Linux arm64 or amd64"):
        installer.install(architecture, tmp_path / "agents")
    assert not (tmp_path / "agents").exists()
