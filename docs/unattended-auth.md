# Restart-persistent account authorization

For an unattended Docker deployment, configure the application's existing
encrypted credential vault before signing in. Session-only credentials are lost
when the backend process stops. A passphrase vault needs an interactive unlock
after each restart. A deployment key allows the same encrypted vault to unlock
automatically, without storing a provider password or putting tokens in chat
history.

This does not guarantee that a provider will keep an account authorized. Account
revocation, provider policy, refresh-token expiration, and quota limits can still
stop live testing. Stop live requests when reauthentication is required; continue
offline tests instead. Do not repeatedly retry sign-in or switch providers.

## Prepare the deployment

Run from the source repository with the project's Python environment and an
already installed local Labcat Docker image:

```sh
python scripts/prepare_unattended_vault.py \
  --image labcat:0.1.0.dev0 \
  --output .local/unattended/compose.vault.yaml
```

The helper creates a dedicated `labcat-vault-key` Docker volume. Its key
is generated inside a non-root, network-disabled container and is never printed,
returned to the host, placed in an image, or inserted into an environment
variable. The volume directory is owner-only and the key is owner-read-only.
Rerunning the helper validates the existing key without replacing it. An existing
unrelated volume or a different output configuration is rejected.

The generated local Compose override mounts this volume read-only into the
workspace service and sets `LABCAT_VAULT_KEY_FILE` to its path. The Goose worker
and its egress service do not receive the key volume. Encrypted OAuth credentials
remain in the separate existing workspace volume. This separation keeps routine
workspace backups from also containing their decryption key; it does not protect
against an administrator controlling Docker or the host.

Start or update using **both** Compose files:

```sh
docker compose --project-name labcat \
  --file compose.yaml --file .local/unattended/compose.vault.yaml \
  up --detach --wait --wait-timeout 60

docker compose --project-name labcat \
  --file compose.yaml --file .local/unattended/compose.vault.yaml \
  port labcat 8000
```

Open the returned local address. In Connections, choose encrypted credential
storage before starting ChatGPT browser sign-in. Complete provider sign-in and
Verify connection. Public connection status must show the account's credential
state as `encrypted` and vault key source as `file`. No API returns tokens.

If a passphrase vault already exists, stop and explicitly unlock or migrate it
before proceeding; provisioning a deployment key does not reset or replace that
vault. Never delete an existing vault to make this setup succeed.

Keep this same override in every future Compose update or restart. The ordinary
launcher currently uses only the base Compose file; using it to recreate this
deployment omits the key mount and leaves its encrypted credentials locked.
Use the two-file commands above for unattended operation. Do not remove the key
volume, run volume pruning, or reset Docker while those credentials are needed.

## Verify before a final sign-in

```sh
python scripts/smoke_unattended_auth.py --image labcat:0.1.0.dev0
```

This uses inert synthetic credentials and replacement containers to check
encrypted storage, automatic unlock, refreshed-token persistence, and failure
with a missing key. It disables networking, limits each check to 128 MiB and one
CPU, and removes its small temporary volumes. It never mounts the actual
workspace or the deployment's real key and never runs provider inference.

After the real sign-in, check public account readiness once. A controlled
restart using the same override followed by another readiness check establishes
that the actual account is recoverable in this deployment. Do this while the
user is still available. Avoid resetting credentials or starting new sign-in
flows during later testing. The backend serializes refresh consumers and saves
rotated credentials back to the encrypted slot, including refreshes recovered
from a failed model run.

Record verification times, image IDs, account readiness, and test outcomes.
Do not record tokens, vault keys, provider passwords, or full process output
that could contain credentials.
