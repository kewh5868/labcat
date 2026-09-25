"""Verify encrypted synthetic OAuth across disposable Docker
replacements.

All provider interactions are simulated and networking is disabled. No
actual workspace, provider account, or production deployment key is
mounted. Tiny test volumes are removed after the checks; Docker images
are never downloaded.
"""

import argparse
import base64
import copy
import json
import os
import subprocess
import tempfile
from pathlib import Path
from uuid import uuid4


def auth_fixture():
    def jwt(value):
        encoded = base64.urlsafe_b64encode(json.dumps(value).encode()).decode()
        return "eyJhbGciOiJIUzI1NiJ9." + encoded.rstrip("=") + ".c2lnbmF0dXJl"

    return {
        "auth_mode": "chatgpt",
        "OPENAI_API_KEY": None,
        "tokens": {
            "access_token": jwt({"exp": 2_000_000_000}),
            "refresh_token": "synthetic-not-a-provider-credential",
            "id_token": jwt({"test": "synthetic"}),
            "account_id": "synthetic-account",
        },
        "last_refresh": "2026-09-16T00:00:00Z",
    }


class SyntheticBroker:
    def start(self):
        return {"flow_id": "synthetic-flow", "status": "pending"}

    def poll(self, _):
        return {"flow_id": "synthetic-flow", "status": "complete"}

    def take_credentials(self, _):
        return auth_fixture()

    def metadata(self, auth):
        refreshed = copy.deepcopy(auth)
        refreshed["tokens"]["refresh_token"] = "synthetic-rotated-credential"
        return {"account_ready": True}, refreshed


def container_stage(stage):
    from labcat.connections import DEFAULT_PROFILE, ConnectionManager
    from labcat.credentials import ConnectionError

    workspace = Path("/var/lib/labcat/synthetic.sqlite3")
    manager = ConnectionManager(workspace)
    if stage == "seed":
        identifier = manager.save_account(
            {
                "label": "Synthetic restart check",
                "profile": {
                    **DEFAULT_PROFILE,
                    "provider": "chatgpt",
                    "model": "synthetic-model",
                },
                "secret_storage": "encrypted",
            }
        )["active_account_id"]
        manager.agent._auth = SyntheticBroker()
        manager.agent.start_login(identifier, {"secret_storage": "encrypted"})
        manager.agent.login_action(identifier, "synthetic-flow", "poll")
    else:
        identifier = manager.status()["active_account_id"]
    if stage == "missing-key":
        ciphertext = manager.vault.path.read_bytes()
        assert manager.status()["vault"]["locked"] is True
        try:
            manager.agent._credential_snapshot(identifier)
        except ConnectionError:
            pass
        else:
            raise AssertionError("Missing deployment key allowed credential use")
        assert manager.vault.path.read_bytes() == ciphertext
    else:
        assert manager.status()["vault"]["key_source"] == "file"
        assert manager.status()["accounts"][0]["credential_state"] == "encrypted"
        if stage == "rotate":
            manager.agent._auth = SyntheticBroker()
            assert manager.agent.metadata(identifier)["account_ready"] is True
        if stage == "verify":
            assert (
                manager.agent._credential_snapshot(identifier)[0]["tokens"][
                    "refresh_token"
                ]
                == "synthetic-rotated-credential"
            )
        key = Path(os.environ["LABCAT_VAULT_KEY_FILE"]).read_bytes()
        for saved in workspace.parent.iterdir():
            data = saved.read_bytes()
            assert key not in data
            assert b"synthetic-not-a-provider-credential" not in data
            assert b"synthetic-rotated-credential" not in data
    public = json.dumps(manager.status())
    assert "refresh_token" not in public
    assert "synthetic-rotated-credential" not in public
    print(json.dumps({"stage": stage, "passed": True, "synthetic_only": True}))


def smoke(image):
    from prepare_unattended_vault import prepare

    prefix = "labcat-auth-smoke-" + uuid4().hex[:12]
    key_volume, data_volume = prefix + "-vault-key", prefix + "-state"

    def docker(arguments):
        result = subprocess.run(
            ["docker", *arguments], text=True, capture_output=True, timeout=60
        )
        if result.returncode:
            raise RuntimeError("Synthetic container authentication check failed.")
        return result.stdout

    try:
        with tempfile.TemporaryDirectory(prefix="labcat-auth-smoke-") as folder:
            prepare(image, key_volume, Path(folder) / "compose.json")
            docker(
                [
                    "volume",
                    "create",
                    "--label",
                    "org.labcat.test=auth",
                    data_volume,
                ]
            )
            results = []
            for stage in ("seed", "rotate", "verify", "missing-key", "verify"):
                mounts = [
                    "--mount",
                    f"type=volume,src={data_volume},dst=/var/lib/labcat",
                    "--mount",
                    f"type=bind,src={Path(__file__).resolve()},"
                    "dst=/opt/smoke.py,readonly",
                ]
                if stage != "missing-key":
                    mounts += [
                        "--mount",
                        f"type=volume,src={key_volume},dst=/run/labcat-vault,readonly",
                        "--env",
                        "LABCAT_VAULT_KEY_FILE=/run/labcat-vault/key",
                    ]
                result = docker(
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
                        "--memory",
                        "128m",
                        "--cpus",
                        "1",
                        "--pids-limit",
                        "64",
                        *mounts,
                        "--entrypoint",
                        "python",
                        image,
                        "/opt/smoke.py",
                        "--stage",
                        stage,
                    ]
                )
                results.append(json.loads(result))
            return {"image": image, "synthetic_only": True, "stages": results}
    finally:
        # Only names allocated by this invocation; never prune other volumes.
        for name in (data_volume, key_volume):
            subprocess.run(
                ["docker", "volume", "rm", name], capture_output=True, timeout=30
            )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", help="Existing local Labcat image")
    parser.add_argument("--stage", choices=("seed", "rotate", "verify", "missing-key"))
    args = parser.parse_args()
    if args.stage:
        container_stage(args.stage)
    elif args.image:
        print(json.dumps(smoke(args.image), indent=2))
    else:
        parser.error("--image is required")


if __name__ == "__main__":
    main()
