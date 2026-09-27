"""Install the pinned, unmodified official Claude Code native binary.

Release metadata was reviewed from Anthropic's manifest on 2026-09-27.
No downloaded installer executes and no moving release channel is read.
"""

import argparse
import hashlib
import os
import tempfile
from pathlib import Path
from urllib.request import urlopen

CLAUDE_VERSION = "2.1.274"
RELEASE_BASE = "https://downloads.claude.ai/claude-code-releases"
RELEASES = {
    "arm64": {
        "platform": "linux-arm64",
        "size": 230_482_160,
        "sha256": "2db904daea17addff9de557ba26a725916888aa7b546e2c5dd989c20d9d49ab3",
    },
    "amd64": {
        "platform": "linux-x64",
        "size": 230_580_536,
        "sha256": "15e2d05148f801b5774032faad87e624ecd172e9903288bda448b892eb58fa07",
    },
}
CHUNK_BYTES = 1024 * 1024


def install(architecture: str, destination: Path):
    if architecture not in RELEASES:
        raise ValueError("Choose Linux arm64 or amd64 for the native Claude binary.")
    release = RELEASES[architecture]
    url = f"{RELEASE_BASE}/{CLAUDE_VERSION}/{release['platform']}/claude"
    destination.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        # Keep a failed or interrupted download separate from the installed file.
        with tempfile.NamedTemporaryFile(
            dir=destination, prefix=".claude-", suffix=".download", delete=False
        ) as output:
            temporary = Path(output.name)
            digest = hashlib.sha256()
            size = 0
            with urlopen(url, timeout=120) as response:
                while chunk := response.read(
                    min(CHUNK_BYTES, release["size"] - size + 1)
                ):
                    size += len(chunk)
                    if size > release["size"]:
                        raise RuntimeError("Claude release exceeds its pinned size.")
                    digest.update(chunk)
                    output.write(chunk)
            if size != release["size"]:
                raise RuntimeError("Claude release does not match its pinned size.")
            if digest.hexdigest() != release["sha256"]:
                raise RuntimeError("Claude release failed SHA256 verification.")
        os.chmod(temporary, 0o755)
        os.replace(temporary, destination / "claude")
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    print(f"Installed verified Claude Code {CLAUDE_VERSION} for {architecture}.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("architecture", choices=("arm64", "amd64"))
    parser.add_argument("--destination", type=Path, default=Path("/agent-bin"))
    args = parser.parse_args()
    install(args.architecture, args.destination)


if __name__ == "__main__":
    main()
