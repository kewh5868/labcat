"""Source redistribution integrity and safe, deterministic archive
selection."""

import hashlib
import importlib.util
import io
import json
import tarfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "vendor_jsmol_source", ROOT / "scripts/vendor_jsmol_source.py"
)
assert SPEC is not None and SPEC.loader is not None
vendor = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(vendor)


def test_shipped_source_archive_has_every_manifest_member_and_no_site_examples():
    folder = ROOT / "frontend/public/structure-viewer/vendor"
    manifest = json.loads((folder / "SOURCE-MANIFEST.json").read_text())
    archive = folder / "SOURCE.tar.gz"
    assert manifest["version"] == vendor.VERSION
    assert manifest["upstream_source_sha256"] == vendor.SOURCE_SHA256
    assert vendor.digest(archive) == manifest["archive_sha256"]
    with tarfile.open(archive) as source:
        assert set(source.getnames()) == set(manifest["files"])
        for member in source.getmembers():
            assert member.isfile() and member.mtime == member.uid == member.gid == 0
            assert member.mode == 0o644
            assert not member.name.startswith("site-resources/jsmol/data/")
            assert not member.name.endswith(("/Jmol.jar", "/jsmol.zip"))
            stream = source.extractfile(member)
            assert stream is not None
            assert (
                hashlib.sha256(stream.read()).hexdigest()
                == manifest["files"][member.name]
            )
    assert vendor.digest(ROOT / "third_party/JSMOL-LICENSE") == vendor.digest(
        folder / "LICENSE.txt"
    )


def source_fixture(path, extra=None):
    files = {name: b"UPSTREAM TEST BUILD NOTICE\r\n" for name in vendor.FILES}
    files.update(
        {
            vendor.ROOT + "/src/Test.java": b"// TEST SOURCE\r\n",
            "site-resources/jsmol/data/test.cif": b"TEST DEMONSTRATION MUST BE OMITTED",
        }
    )
    with tarfile.open(path, "w:gz") as archive:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.mtime, info.uid, info.gid = 987654321, 501, 20
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
        if extra is not None:
            archive.addfile(extra)


def test_repackaging_preserves_bytes_and_normalizes_metadata(tmp_path, monkeypatch):
    source = tmp_path / "upstream.tar.gz"
    source_fixture(source)
    monkeypatch.setattr(vendor, "SOURCE_SHA256", vendor.digest(source))
    first, second = tmp_path / "first.gz", tmp_path / "second.gz"
    assert vendor.make_source(source, first) == vendor.make_source(source, second)
    assert first.read_bytes() == second.read_bytes()
    with tarfile.open(first) as packaged:
        assert "site-resources/jsmol/data/test.cif" not in packaged.getnames()
        stream = packaged.extractfile(vendor.ROOT + "/src/Test.java")
        assert stream is not None and stream.read() == b"// TEST SOURCE\r\n"


@pytest.mark.parametrize("mutation", ["hash", "symlink", "traversal", "duplicate"])
def test_unsafe_source_inputs_cannot_be_repackaged(tmp_path, monkeypatch, mutation):
    source = tmp_path / "upstream.tar.gz"
    extra = None
    if mutation == "symlink":
        extra = tarfile.TarInfo(vendor.ROOT + "/src/link")
        extra.type, extra.linkname = tarfile.SYMTYPE, "/private/file"
    elif mutation == "traversal":
        extra = tarfile.TarInfo(vendor.ROOT + "/src/../../outside")
    elif mutation == "duplicate":
        extra = tarfile.TarInfo(vendor.ROOT + "/src/Test.java")
    source_fixture(source, extra)
    if mutation != "hash":
        monkeypatch.setattr(vendor, "SOURCE_SHA256", vendor.digest(source))
    with pytest.raises(ValueError):
        vendor.make_source(source, tmp_path / "output.gz")
