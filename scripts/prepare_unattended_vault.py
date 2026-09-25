"""Provision an opt-in Docker deployment key without exporting its
contents.

The key uses a separate persistent volume, never the workspace data
volume. Run before browser sign-in, then choose encrypted credential
storage in Labcat. This configures persistence, not account
authorization or model inference.
"""

import argparse
import json
import re
import subprocess
from pathlib import Path

LABEL = "org.labcat.role=deployment-vault-key"
PROVISION = r"""
import os
import stat
from pathlib import Path
from cryptography.fernet import Fernet
from labcat.credentials import read_private_file

folder = Path("/var/lib/labcat")
assert os.getuid() == 10001
assert folder.stat().st_uid == os.getuid()
assert stat.S_IMODE(folder.stat().st_mode) == 0o700
key = folder / "key"
try:
    fd = os.open(key, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o400)
except FileExistsError:
    assert not key.is_symlink()
    assert key.stat().st_uid == os.getuid()
    assert stat.S_IMODE(key.stat().st_mode) == 0o400
    Fernet(read_private_file(key, 256).strip())
else:
    with os.fdopen(fd, "wb") as stream:
        stream.write(Fernet.generate_key())
        stream.flush()
        os.fsync(stream.fileno())
print("Deployment key ready; contents were not exported.")
"""


def run(arguments, **kwargs):
    result = subprocess.run(
        ["docker", *arguments], capture_output=True, text=True, timeout=60, **kwargs
    )
    if result.returncode:
        # Unexpected process output must never become a credential diagnostic.
        raise RuntimeError("Docker deployment-key preparation failed; no key exported.")
    return result.stdout


def prepare(image, volume, output):
    if not re.fullmatch(r"labcat(?:-[a-z0-9][a-z0-9_-]{0,90})?-vault-key", volume):
        raise ValueError("Use a dedicated labcat-…-vault-key volume name.")
    existing = run(["volume", "ls", "--format", "{{.Name}}"])
    if volume in existing.splitlines():
        labels = json.loads(
            run(["volume", "inspect", "--format", "{{json .Labels}}", volume])
        )
        if not isinstance(labels, dict) or labels.get("org.labcat.role") != (
            "deployment-vault-key"
        ):
            raise ValueError("The existing volume is not a managed deployment key.")
    else:
        run(["volume", "create", "--label", LABEL, volume])
    run(
        [
            "run",
            "--rm",
            "--pull",
            "never",
            "--network",
            "none",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges:true",
            "--mount",
            f"type=volume,src={volume},dst=/var/lib/labcat",
            "--entrypoint",
            "python",
            "-i",
            image,
            "-",
        ],
        input=PROVISION,
    )
    override = {
        "services": {
            "labcat": {
                "environment": {
                    "LABCAT_VAULT_KEY_FILE": "/run/labcat-vault/key",
                },
                "volumes": [f"{volume}:/run/labcat-vault:ro"],
            }
        },
        "volumes": {volume: {"external": True, "name": volume}},
    }
    output = Path(output)
    if output.is_symlink() or output.parent.is_symlink():
        raise ValueError("The local override cannot be a symbolic link.")
    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    # The override is nonsecret; refuse to silently replace a different config.
    if output.exists() and json.loads(output.read_text()) != override:
        raise ValueError("The output already contains a different deployment override.")
    if not output.exists():
        with output.open("x") as stream:
            json.dump(override, stream, indent=2)
            stream.write("\n")
        output.chmod(0o600)
    return {"key_volume": volume, "override": str(output.resolve())}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True, help="Existing local Labcat image")
    parser.add_argument("--key-volume", default="labcat-vault-key")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.image, args.key_volume, args.output)))


if __name__ == "__main__":
    main()
