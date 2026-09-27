# Setup and remembered connections

First launch opens a setup window. A supported model account and a selected model
are required before submitting new research. This is the current product setting;
the application does not offer a model-free or local-Ollama bypass. The workspace,
source validation and ranking still run locally by default.

Labcat's developer currently recommends **ChatGPT account sign-in** because it
is the application's most thoroughly tested model connection.

1. **Model:** choose **Model provider**, complete provider-owned sign-in or
   connect using that provider's API key, then select an available model and
   allow the bounded research context to be sent to that provider. Choose
   **Save and test connections**, wait for a successful result, then
   **Continue**. Unsaved model or consent changes must be saved first.
   **Verify connection** checks an already saved selection again; when offered,
   **Verify and continue** checks it before advancing. These checks use
   credentials and model metadata without starting inference.
2. **Public sources:** choose supported keyless services or add an optional
   Materials Project API key for its live quantitative source. Multiple public
   services can be enabled together.
3. **Ready:** review the active model. You can change it here; the selection is
   saved and checked before completion. Choose **Finish setup** after the active
   account passes its check to enter the main workspace. Non-secret setup
   progress survives restart. **View workspace** closes setup to review existing
   work; it does not bypass the connection requirement.

The active account is checked again before each research prompt. Expired,
revoked or unavailable credentials, a missing model selection or missing hosted
consent prevent a new run. The credential vault is optional: a working session
connection remains usable while saved credentials are locked. No account or model
is silently substituted. Account checks cannot guarantee that a later inference
request will succeed.

Public discovery sends search hints to selected public services. It does not
supply preselected materials when evidence is missing. Turning off reference
discovery does not disable quantitative adapters or the connected model.
The launcher's `cli --offline` option disables container networking and is useful
for status/configuration checks; it cannot perform authenticated research.

Connection profiles remember only provider/model identifiers, local endpoint
and hosted-inference consent. Keys are write-only fields; responses show
availability rather than key values. No third-party passwords,
browser localStorage credentials, automatic cloud fallback or account provisioning
are used. Local workspace processing still requires a model connection. Saved
legacy model-free settings cannot bypass it.

In **Connections**, use **Model provider** to connect or switch providers.
Choose ChatGPT for browser account sign-in, **Anthropic (Claude Code sign-in)**
for the native terminal flow below, or an API provider for its own key. Use **Connect [provider]** or **Save API key** to save API credentials
and load the model catalog.
Use **Account** to switch between saved connections for the selected provider.
Choose **Connect another account…** to add a separate connection; an optional
**Account label** helps distinguish it. Existing connections, model choices and
consent settings are retained when switching. A new connection with an empty key
stays unconnected and never inherits another account's key. Leaving an existing
connection's key field blank retains its current key; a locked saved key still
needs unlocking or a fresh session key. Saving or switching does not run inference.

To switch from a chat, open the language-model control below the prompt. Choose a
saved account, then use **Active model** to select a model or Claude Code alias.
The list distinguishes connections by account, provider and model. Changes apply
to subsequent requests; saved reports keep their original model record.
Available models load automatically after connecting, signing in, unlocking
credentials or switching to an existing provider connection. Choose a model from
that catalog, save model and consent changes with **Save and test connections**,
and review the check result before starting research.
**Refresh models** retries discovery and **Advanced model settings** allows a manual
identifier supplied by the provider. Catalog requests do not run inference or
change the selected model automatically. Catalog access does not prove
that a particular model supports the planning protocol or can be invoked.
Claude Code offers configured aliases rather than an account-reported catalog.

The same page offers optional materials database connections.

Public source filters are also available in Search Criterion. Help
shows the application's developer, version and license; the repository link will
be enabled when a GitHub URL is configured.

## Suggested supported public APIs

These connections are optional additions to the required model connection.
An API credential never grants access to private or paywalled data in Labcat.
Database availability and coverage determine whether a search improves.

In **Connections → Supported research databases**, or the public-sources step
of setup, choose [Register or get an API key](https://next-gen.materialsproject.org/api)
on the Materials Project card. Register or sign in on its website, copy the key from
your [account dashboard](https://next-gen.materialsproject.org/dashboard), then
paste it into that card's API-key field and choose **Save and verify**. This follows
the provider's [API setup guide](https://docs.materialsproject.org/downloading-data/using-the-api/getting-started).
The other supported source cards provide **Visit database** and **API access
guide** links and identify public lookup as requiring no account or key. Links
open separately, preserving the current form and saved preferences.

| Service                                                                   | Account or key needed here                               | Current use in Labcat                                                                                        |
| ------------------------------------------------------------------------- | -------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------ |
| [Materials Project](https://next-gen.materialsproject.org/api)            | Optional provider API key; register/sign in to obtain it | Public material records and supported properties                                                             |
| [NOMAD](https://docs.nomad-lab.eu/develop/howto/manage/program/api.html)  | No                                                       | Published, non-embargoed identities and selected validated properties for supported bulk-composition queries |
| [HybriD³](https://hybrid3-database.readthedocs.io/en/latest/website.html) | No                                                       | Public compound identities and validated scalar band-gap datasets                                            |
| [Europe PMC](https://europepmc.org/RestfulWebService)                     | No                                                       | Open-access references and available article-text passages for missing-property review                       |
| [arXiv](https://info.arxiv.org/help/api/user-manual.html)                 | No                                                       | Public preprint titles and links                                                                             |

Choose **Remember key securely between sessions** in the card to use the local
encrypted vault. Create or unlock the vault when prompted. Unlock it once after
the Labcat server restarts; leave the API-key field blank to use the saved key
without entering it again. Its value is never sent back to the browser.
Without this option, the key stays in server memory only. When the vault is
unlocked, clearing **Remember key securely between sessions** and choosing
**Save and verify** removes that key's saved encrypted copy; enter it again
after restarting. If the vault is locked,
choose **Use a key for this session**, paste the same or another API key, and
choose **Save and verify**. This session override leaves saved encrypted keys
unchanged. Saving, verifying or forgetting a database key does not change
model-account settings. Keys stay out of chat and session history.

In **Search Criterion**, use **Add a research database** to select a verified
Materials Project connection alongside other databases, or **Remove database**
to stop using it. An unavailable or unverified key cannot enable API research.
There is no separate property-API dropdown. Only Materials
Project currently accepts a data API key; the other adapters do not need or store
one. Publication titles and links are references, not verified property evidence.
Available open-access XML can be skimmed through the approved article adapter;
the app does not browse arbitrary websites or bypass paywalls. See
[source coverage](scientific-sources.md) for the distinction between references
and ranked material evidence.

## Claude Code account sign-in

Choose **Anthropic (Claude Code sign-in)**, then **Set up Claude Code sign-in**.
The saved connection shows a command containing its account ID. From your
`labcat` repository folder in Terminal or PowerShell, run that copied command:

```text
docker compose exec goose-worker python -m labcat.claude_auth login <account-id>
```

The `<account-id>` above is a placeholder; the command in **Connections** already
contains the correct value. Docker and the Labcat worker must be running.
Follow the native Claude Code terminal instructions to open its provider sign-in
page and complete authorization. Any code entry belongs in that native flow,
never in Labcat. Return to **Connections** and choose **Check Claude Code
sign-in**. Select `default`, `sonnet` or `haiku`, save model and consent settings,
and check the connection before continuing setup.

These choices are provider aliases, not verified account entitlements. The check
reports whether the native CLI detects sign-in; it does not test model access,
quota or inference. Live Claude account inference has not yet been validated in
Labcat. Eligibility and charges remain subject to your Claude Code account.

The unmodified native CLI owns authentication and keeps its files in private
memory-backed storage inside the worker. Labcat does not read, copy or put its
tokens in the vault, and does not import an existing host login. Multiple saved
Labcat accounts have separate native sessions. **End Claude Code session**
clears the selected session; restarting the worker container clears all of them.
Creating, unlocking, locking, changing or resetting the optional vault does not
change these native sessions. Reconnect through the same terminal command after
restart. See the [runtime boundary](goose.md#native-claude-code-runtime).

## Persisting API keys and ChatGPT credentials

For **ChatGPT · account sign-in**, choose **Sign in with ChatGPT**, open the
provider-owned browser authorization page, complete the provider's sign-in,
and return to Labcat. Goose owns this OAuth flow inside the Docker worker.
No device code is needed, and Labcat does not collect your password or change
account security settings. Sign-in expires after five minutes; use the sign-in
retry action for a new authorization rather than reusing an expired page.
The app stays pending until the provider confirms completion.

Goose requires the fixed browser callback `localhost:1455`. If another application
uses that port, the launcher keeps Labcat available with browser sign-in
disabled. Finish or close that other login process, then relaunch with
`LABCAT_OAUTH_CALLBACK_PORT=1455` to retry; do not change Goose's registered
redirect. An existing saved connection or a
different supported provider can still be used. See [deployment](deployment.md).

Legacy configurations may still show the older device-code flow. Only that
flow requires ChatGPT **Settings → Security → device-code authorization** (or
workspace administrator permission). Follow the displayed device instructions;
it is not an automatic replacement for a failed browser sign-in.

Sign-in must run against the Docker backend, which supplies the pinned helper
and memory-backed temporary credential storage. A development preview running
directly on the host cannot provide that storage. If either prerequisite is
unavailable, the app displays deployment guidance; changing your password or
vault passphrase will not repair a missing runtime component.

After successful login, available models load automatically. Select a model,
save the selection and enable hosted-context consent before sending a research prompt.
**Check usage** shows returned quota percentages/reset times and per-run tokens;
unknown values stay unavailable. [Official authentication](https://learn.chatgpt.com/docs/auth)

The Docker image includes Goose for browser authorization and inference, and the
pinned Codex helper for account/model/usage metadata. They use temporary
credential files only on memory-backed Linux storage. Tokens saved for restart
enter the existing encrypted vault in separate OAuth slots. Temporary files are
removed at completion, cancellation, expiry or shutdown. The app never reads
another installation's Codex login. Anthropic API connections use API keys;
Claude Code account sign-in uses the separate native flow above. Never paste
subscription tokens into an API-key field.

Session-only storage is the default and loses credentials when the server stops.
You can connect, reconnect and switch accounts without creating or unlocking a
vault. To remember model credentials, open **Advanced credential options**, create a
vault password of at least 12 characters, and choose **Encrypted credential
vault**. Then choose **Save and test connections**. An available API key can be
remembered without entering it again: leave its field blank. For ChatGPT, choose
encrypted storage before signing in or reconnecting. For a research database key,
use **Remember key securely between sessions** in its own card.

After a server restart, open **Connections → Unlock saved credentials**, enter
the vault password, and choose **Unlock credentials**. Unlocking once makes all
saved credentials available for that server session. API-key fields stay blank
because saved values are never sent back to the browser; blank fields do not
mean the keys were lost. Expired or revoked provider credentials still need
reconnecting. Closing and reopening a browser window does not lock a running
server's vault.

To change a known password, open **Advanced credential options → Change vault
password**. Enter the current password, the new password, and its confirmation,
then choose **Change vault password**. Saved credentials remain encrypted and
available. Use the new password after the next server restart.

If you forgot the password, open **Advanced credential options → Forgot
password? Reset vault**. Read the consequences, check the confirmation box, then
choose **Reset vault and clear credentials**. This removes the vault password
and clears **all vault-managed encrypted and session-only credentials**,
including API keys and ChatGPT sign-ins. Re-enter keys or sign in again; you can
then create a new vault password. Native Claude Code sessions are unaffected;
end them with **End Claude Code session** or restart the worker container.
Connection preferences, projects, chats and reports are kept. Labcat cannot
recover cleared credentials.

You can keep the vault locked and connect for **This server session**. For
ChatGPT, choose **Reconnect ChatGPT** and complete provider sign-in again, or add
another account and sign in there. No vault password or prior sign-out is needed.
Starting a different account's sign-in replaces an unfinished sign-in challenge;
it does not remove saved credentials. **End session** disconnects a fresh ChatGPT
session while its older encrypted sign-in remains locked.

For an API provider, paste the same or another key and choose **Save API key**.
A database key uses its card's **Use a key for this session** and **Save and
verify** actions. These session connections leave saved encrypted credentials
unchanged. Unlocking is needed only to reuse those saved credentials without
entering a key or signing in again. Labcat does not offer unencrypted credential
persistence.

The app derives an encryption key with Scrypt and authenticates ciphertext with
Fernet. Only ciphertext, salt and version metadata are saved. The unlocked key
remains in server memory. Files are workspace-specific and written atomically
with restrictive owner permissions where supported. Tampered or unreadable
files produce redacted errors and preserve the existing file. Encryption at rest
does not protect against an attacker controlling the running OS process.
For unattended installations an administrator may supply `LABCAT_VAULT_KEY` or
`LABCAT_VAULT_KEY_FILE` externally; password changes for that configuration are
managed by the administrator. Never store that key alongside the vault.

An interrupted connection save leaves a non-secret pending marker. On restart,
the app keeps research unavailable until an explicit successful save or selection
clears it and the connection is checked. Failed saves restore the previous
in-memory credentials and encrypted vault
when possible; reload the connection status after an error before retrying.

## Tests and costs

Connection tests are explicit metadata/identity checks. They report whether
inference was tested; none invokes a model or creates cloud resources. Catalog
availability is not proof that the selected model can be invoked. Hosted model
planning requires a separate saved consent choice; prompts and bounded project
context will be transmitted and
provider charges may apply. Saving settings and restarting never invoke models.

Invalid model output or a failed model request produces an explicit unsuccessful
run; it does not trigger model-free research. Source retrieval failure does not silently supply model guesses or
substitute stored demonstration results for a live search. A blocked source run keeps
scientific fields empty.

In Docker, Goose coordinates the configured research stages. Labcat owns source
validation, deterministic ranking and report rendering. It does not retry a failed
whole model run, bypass the required model connection or select another paid provider.
Goose's provider library may retry internally within the bounded run. An interrupted
sign-in or connection change must be reloaded before retrying.
