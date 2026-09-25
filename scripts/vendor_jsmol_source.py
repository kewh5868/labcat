"""Verify pinned upstream archives and package the unmodified JSmol
source subset.

Reads local archives only. No archive extraction, download, or third-
party code execution occurs. JavaScript runtime files are verified but
never rewritten.
"""

import argparse
import gzip
import hashlib
import io
import json
import tarfile
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

VERSION = "16.4.23"
BINARY_SHA256 = "1c4aa04d6b4fc96cfd1b2cb3649f5ba39048620a8358799bc1b78ee1041bc4b2"
SOURCE_SHA256 = "ecb76e7d0ce06f1a69c757ad379dd5f979ce538f35b63613a0366383db348085"
RELEASE = (
    "https://sourceforge.net/projects/jmol/files/Jmol/Version%2016.4/Jmol%2016.4.23/"
)
SOURCE_URL = RELEASE + "Jmol-16.4.23-full.tar.gz/download"
ROOT = f"jmol-{VERSION}"
PREFIXES = (
    ROOT + "/src/",
    ROOT + "/tools/",
    ROOT + "/jars/",
    ROOT + "/manifest/",
    "j2s/",
    "site-resources/jsmol/js/",
    "site-resources/jsmol/jquery/",
    "site-resources/jsmol/j2s/",
)
FILES = frozenset(
    ROOT + "/" + name
    for name in (
        "build.README.txt",
        "LICENSE.txt",
        "COPYRIGHT.txt",
        "CHANGES.txt",
        "jspecview.properties",
    )
) | {
    "site-resources/jsmol/README.TXT",
    "site-resources-zip/README.TXT",
    "site-resources-zip/Jmol-j2s-site.zip",
}
MAX_FILE = 50_000_000
MAX_SELECTED_BYTES = 100_000_000


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def require_archive(path, expected):
    if path.is_symlink() or not path.is_file() or digest(path) != expected:
        raise ValueError("A local upstream archive failed its pinned SHA-256 check.")


def safe_name(name):
    path = PurePosixPath(name)
    if (
        not name
        or path.is_absolute()
        or ".." in path.parts
        or path.as_posix() != name
        or "\\" in name
        or ":" in name
        or any(ord(char) < 32 or ord(char) == 127 for char in name)
    ):
        raise ValueError("An archive contains an unsafe path.")
    return name


def selected(name):
    return name in FILES or name.startswith(PREFIXES)


def verify_runtime(binary, vendor):
    require_archive(binary, BINARY_SHA256)
    manifest = json.loads((vendor / "manifest.json").read_text())
    if manifest["version"] != VERSION or manifest["archive_sha256"] != BINARY_SHA256:
        raise ValueError("The vendor manifest does not match the pinned release.")
    with zipfile.ZipFile(binary) as upstream:
        with zipfile.ZipFile(io.BytesIO(upstream.read(ROOT + "/jsmol.zip"))) as browser:
            for name, expected in manifest["files"].items():
                safe_name(name)
                path = vendor / name
                if path.is_symlink() or not path.is_file():
                    raise ValueError("A runtime asset is missing or is a symlink.")
                data = (
                    upstream.read(ROOT + "/" + name)
                    if name in {"LICENSE.txt", "COPYRIGHT.txt"}
                    else browser.read("jsmol/" + name)
                )
                if (
                    hashlib.sha256(data).hexdigest() != expected
                    or path.read_bytes() != data
                ):
                    raise ValueError(
                        "A runtime asset differs from its upstream release."
                    )


def make_source(source, output):
    require_archive(source, SOURCE_SHA256)
    manifest, total = {}, 0
    with tarfile.open(source, "r:gz") as upstream:
        members = {}
        for member in upstream.getmembers():
            if member.isdir():
                continue
            name = safe_name(member.name)
            if name in members or not member.isfile():
                raise ValueError(
                    "The source archive has duplicate or nonregular files."
                )
            members[name] = member
        if not FILES <= members.keys():
            raise ValueError("The source release is missing required build notices.")
        with output.open("wb") as destination:
            with gzip.GzipFile(
                filename="", mode="wb", fileobj=destination, mtime=0
            ) as compressed:
                with tarfile.open(
                    fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT
                ) as packed:
                    for name, member in sorted(members.items()):
                        if not selected(name):
                            continue
                        total += member.size
                        if (
                            not 0 <= member.size <= MAX_FILE
                            or total > MAX_SELECTED_BYTES
                        ):
                            raise ValueError(
                                "The source selection exceeded its size budget."
                            )
                        stream = upstream.extractfile(member)
                        if stream is None:
                            raise ValueError("The source member cannot be read.")
                        data = stream.read()
                        if len(data) != member.size:
                            raise ValueError("The source member is truncated.")
                        entry = tarfile.TarInfo(name)
                        entry.size = len(data)
                        entry.mode = 0o644
                        entry.mtime = entry.uid = entry.gid = 0
                        packed.addfile(entry, io.BytesIO(data))
                        manifest[name] = hashlib.sha256(data).hexdigest()
    return {
        "version": VERSION,
        "upstream_source_url": SOURCE_URL,
        "upstream_source_sha256": SOURCE_SHA256,
        "upstream_binary_sha256": BINARY_SHA256,
        "archive": "SOURCE.tar.gz",
        "archive_sha256": digest(output),
        "source_file_count": len(manifest),
        "uncompressed_bytes": total,
        "included_prefixes": list(PREFIXES),
        "included_files": sorted(FILES),
        "excluded": [
            "demonstration sites and data outside src",
            "prebuilt application JARs",
            "duplicate bundled jsmol.zip files",
        ],
        "files": manifest,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary-archive", type=Path, required=True)
    parser.add_argument("--source-archive", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    vendor = (
        Path(__file__).resolve().parents[1] / "frontend/public/structure-viewer/vendor"
    )
    verify_runtime(args.binary_archive, vendor)
    with tempfile.TemporaryDirectory(prefix="jsmol-source-") as temporary:
        archive = Path(temporary) / "SOURCE.tar.gz"
        manifest = make_source(args.source_archive, archive)
        encoded = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
        if args.check:
            if (
                digest(vendor / "SOURCE.tar.gz") != manifest["archive_sha256"]
                or (vendor / "SOURCE-MANIFEST.json").read_bytes() != encoded
            ):
                raise ValueError("The shipped source archive or manifest differs.")
        else:
            (vendor / "SOURCE.tar.gz").write_bytes(archive.read_bytes())
            (vendor / "SOURCE-MANIFEST.json").write_bytes(encoded)
    print(
        f"Verified JSmol {VERSION}: unmodified runtime and "
        f"{manifest['source_file_count']} source/build files."
    )


if __name__ == "__main__":
    main()
