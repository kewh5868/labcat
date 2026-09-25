"""Install checksum-pinned official agent binaries while building the
image.

No latest/stable lookup, package-manager bootstrap, or downloaded shell
executes. Digests are the official GitHub release asset SHA256 values,
reviewed 2026-09-09.
"""

import argparse
import hashlib
import io
import os
import tarfile
from pathlib import Path
from urllib.request import urlopen

GOOSE_VERSION = "1.50.0"
CODEX_VERSION = "0.154.0"
RELEASES = {
    "goose": {
        "repository": "aaif-goose/goose",
        "tag": "v" + GOOSE_VERSION,
        "arm64": (
            "goose-aarch64-unknown-linux-musl.tar.gz",
            "ab3c61208c5919dac9d069159f4445d3202973ebebb066e90bb72ece99cab417",
            "goose",
        ),
        "amd64": (
            "goose-x86_64-unknown-linux-musl.tar.gz",
            "ff8c51428180142e5c92e2a0b67b3d1762698499d028f6f5fe370fdbec8c84af",
            "goose",
        ),
    },
    "codex": {
        "repository": "openai/codex",
        "tag": "rust-v" + CODEX_VERSION,
        "arm64": (
            "codex-aarch64-unknown-linux-musl.tar.gz",
            "583b48df32804213bdcd338c2e5adb06b34340821fa757a726cc0a524fa33c27",
            "codex-aarch64-unknown-linux-musl",
        ),
        "amd64": (
            "codex-x86_64-unknown-linux-musl.tar.gz",
            "d7e18b2597ae8f242f5f31ee9e90deef48dbc9edd634d9868fb6435d08c07f02",
            "codex-x86_64-unknown-linux-musl",
        ),
    },
}
MAX_ARCHIVE_BYTES = 160_000_000


def install(name: str, architecture: str, destination: Path):
    release = RELEASES[name]
    filename, expected_digest, member_name = release[architecture]
    url = (
        f"https://github.com/{release['repository']}/releases/download/"
        f"{release['tag']}/{filename}"
    )
    with urlopen(url, timeout=120) as response:
        data = response.read(MAX_ARCHIVE_BYTES + 1)
    if len(data) > MAX_ARCHIVE_BYTES:
        raise RuntimeError("Agent release archive exceeds the expected size limit.")
    if hashlib.sha256(data).hexdigest() != expected_digest:
        raise RuntimeError("Agent release archive failed SHA256 verification.")
    # Extract exactly the expected regular file, never archive paths/symlinks.
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        matches = [
            member
            for member in archive.getmembers()
            if member.name in {member_name, "./" + member_name}
        ]
        if len(matches) != 1:
            raise RuntimeError("Agent archive binary is missing or ambiguous.")
        member = matches[0]
        if not member.isfile() or member.size > 400_000_000:
            raise RuntimeError("Agent archive binary is invalid.")
        source = archive.extractfile(member)
        if source is None:
            raise RuntimeError("Agent archive binary is missing.")
        binary = source.read()
    destination.mkdir(parents=True, exist_ok=True)
    output = destination / name
    with output.open("wb") as handle:
        handle.write(binary)
    os.chmod(output, 0o755)
    print(f"Installed verified {name} {release['tag']} for {architecture}.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("architecture", choices=("arm64", "amd64"))
    parser.add_argument("--destination", type=Path, default=Path("/agent-bin"))
    args = parser.parse_args()
    for name in RELEASES:
        install(name, args.architecture, args.destination)


if __name__ == "__main__":
    main()
