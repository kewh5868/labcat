# Provider and credential boundaries

The Python provider APIs use fixed hosted destinations and a bounded local Ollama
endpoint. Redirects and inherited HTTP proxies are disabled. Model output must
match the closed preference schema and cannot create scientific evidence.
Hosted inference requires an explicit `allow_paid_inference` profile setting;
no connection call is made merely by loading configuration or printing status.
Model-account lifecycle and saved profiles are added in a later snapshot.

Install `.[aws,connections]` for optional AWS and encrypted-vault support.
`labcat aws-check --profile NAME --region REGION` performs a bounded read-only
STS identity check and reports status without account identifiers. It creates no
resources and invokes no model; it does not prove Bedrock model access. Ordinary
local CLI operations do not import the AWS SDK.

`CredentialVault` keeps session keys in memory or encrypts explicitly saved
credentials using Fernet with a Scrypt-derived passphrase key, or a separately
supplied deployment key. Plaintext credentials and passphrases are not written to
the vault. Locked, corrupted and tampered data fail closed; reset is explicit.
Credential files must be regular files, and writes use atomic replacement.
Deployments must keep external keys separate from vault ciphertext. This snapshot
provides the storage API; it has no onboarding screen or automatic login workflow.

Unit tests use synthetic credentials and mocked provider/SDK transports. These
checks do not establish authenticated access, model availability or cloud-hosting
coverage for any account.
