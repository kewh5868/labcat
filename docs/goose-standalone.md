# Validate Goose before connecting a real account

For the separate Goose-only image and a real ChatGPT account login without an
API key, see the [native browser-login test](goose-chatgpt-browser-test.md).
That diagnostic now has a successful real login, inference and cached-login
reuse result. The fixtures below remain independent simulated checks.

This diagnostic runs the actual pinned Goose executable in a disposable Docker
container. No Labcat web server, desktop window, host-folder mount, provider
account, model download or paid inference is needed. A simulated provider and two
small test tools run only on container loopback. The container has no network.

After building/loading the image, run from this checkout on macOS or Linux:

```sh
docker run --rm -i \
  --network none --read-only --cap-drop ALL \
  --security-opt no-new-privileges \
  --tmpfs /tmp:size=128m,mode=1777 \
  --entrypoint python labcat:0.1.0.dev0 - < scripts/smoke_goose.py
```

In PowerShell, send the script on standard input:

```powershell
Get-Content -Raw scripts/smoke_goose.py | docker run --rm -i --network none --read-only --cap-drop ALL --security-opt no-new-privileges --tmpfs /tmp:size=128m,mode=1777 --entrypoint python labcat:0.1.0.dev0 -
```

A passing result confirms that Goose starts, receives the configured provider and
model, performs its request/tool loop, rejects a fabricated shell-tool call,
reports the simulated usage, and discards untrusted final prose. It does **not**
prove real provider authorization or model quality. The reported test token counts
come from the simulated provider, not an account balance.

To exercise Goose's actual interactive configuration prompts independently, run
the same command with `scripts/smoke_goose_configure.py` in place of
`scripts/smoke_goose.py` (including the PowerShell command). The fixture creates
its own terminal inside the container and selects a provider, answers the
credential-storage prompt, chooses a model, and verifies one simulated connection
test. All credentials and responses are synthetic. Its temporary configuration
is deleted, it saves no credential, and no real account is contacted. This checks
the upstream setup sequence without exposing it as an application shell.

The next diagnostic, `scripts/smoke_goose_worker.py`, exercises the separate
worker and authenticated report handoff in an isolated Compose test project.
It exercises live-retrieval protocol fixtures separately from production sources,
checks an explicit ranking profile, and rejects a false numeric claim in the
prompt. These fixtures are test inputs and never production fallback results.
`scripts/smoke_container.py --workspace` additionally checks container
mounts, restricted egress, private-API isolation, report exports and persistence.
Test projects use disposable volumes and never the scientist's live workspace.

## Provider setup after these checks

The supported connection families are local Ollama, OpenAI Platform, Anthropic,
Kimi, AWS Bedrock and the specific ChatGPT account integration. Provider and model
choices are passed to Goose's backend subprocess. Each provider retains its own
supported authentication method; consumer subscriptions are not generic API keys.
No browser, host Codex, Goose or AWS credential directory is imported.

Goose's stock `configure` command requires a terminal, can make a model test call,
and falls back to a plaintext secrets file when a keyring is unavailable. It is
therefore not exposed as an unrestricted shell in the application. The app's
structured setup stores credentials in its encrypted vault and supplies selected
credentials to the isolated subprocess only for a run. OAuth temporary files live
on container memory-backed storage. A raw configure experiment, if needed, must
use disposable storage and an explicitly authorized test account.

ChatGPT uses a provider-owned verification flow. It does not collect a ChatGPT
password or reuse an existing host login. Other providers use supported API or
AWS credentials; Claude subscription sign-in is not implemented. Real account
connection, catalog and low-cost inference checks remain a separate explicit step.

See [runtime design](goose.md), [provider connections](providers.md) and the
[validation record](validation.md) for current results and limitations.

Upstream implementation references: [Goose configure](https://github.com/aaif-goose/goose/blob/v1.50.0/crates/goose-cli/src/commands/configure.rs)
and [credential storage fallback](https://github.com/aaif-goose/goose/blob/v1.50.0/crates/goose/src/config/base.rs).
