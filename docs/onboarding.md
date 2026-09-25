# Setup and remembered connections

First launch opens a setup window. A supported model account and a selected model
are required before submitting new research. This is the current product setting;
the application does not offer a model-free or local-Ollama bypass. The workspace,
source validation and ranking still run locally by default.

1. **Model:** choose **Model provider**, complete provider-owned sign-in or
   connect using that provider's API key, then select an available model and
   allow the bounded research context to be sent to that provider. Choose
   **Save and test connections**, wait for a successful result, then
   **Continue**. Unsaved model or consent changes must be saved first.
   **Verify connection** checks an already saved selection again; when offered,
   **Verify and continue** checks it before advancing. These checks use
   credentials and model metadata without starting inference.
2. **Compute:** keep the workspace local, or optionally configure Amazon Bedrock
   model compute through a container-provisioned AWS profile. Another supported
   model account is sufficient; an AWS account is not required.
3. **Public sources:** choose supported keyless services or add an optional
   Materials Project API key for its live quantitative source. Multiple public
   services can be enabled together.
4. **Ready:** review the active model. You can change it here; the selection is
   saved and checked before completion. Choose **Finish setup** after the active
   account passes its check to enter the main workspace. Non-secret setup
   progress survives restart. **View workspace** closes setup to review existing
   work; it does not bypass the connection requirement.

The active account is checked again before each research prompt. Expired or
revoked credentials, a locked vault, missing model selection or missing hosted
consent prevent a new run. No account or model is silently substituted. Account
checks cannot guarantee that a later inference request will succeed.

Public discovery sends search hints to selected public services. It does not
supply preselected materials when evidence is missing. Turning off reference
discovery does not disable quantitative adapters or the connected model.
The launcher's `cli --offline` option disables container networking and is useful
for status/configuration checks; it cannot perform authenticated research.

Connection profiles remember only provider/model identifiers, local endpoint,
AWS profile/region and hosted-inference consent. Keys are write-only fields;
responses show availability rather than key values. No third-party passwords,
browser localStorage credentials, automatic cloud fallback or account provisioning
are used. Choosing local application compute does not remove the model connection
requirement. Saved legacy model-free settings cannot bypass it.

In **Connections**, use **Model provider** to connect or switch providers.
Choose ChatGPT for browser account sign-in, or choose an API provider and enter
its own key. Use **Connect [provider]** or **Save API key** to save API credentials
and load the model catalog. Amazon Bedrock uses an AWS profile instead.
Connections are retained internally when switching providers, including the
existing ChatGPT account; there is no named-account list to manage. New
connections with an empty key remain unconnected and never inherit another
provider's key. Leaving the key blank when editing an existing connection keeps
its current key. Previously saved account identities and names are preserved.
Saving or switching providers does not run inference.
Available models load automatically after connecting, signing in, unlocking
credentials or switching to an existing provider connection. Choose a model from
that catalog, save model and consent changes with **Save and test connections**,
and review the check result before starting research.
**Refresh models** retries discovery and **Advanced model settings** allows a manual
identifier supplied by the provider. Catalog requests do not run inference or
change the selected model automatically. Catalog access does not prove
that a particular model supports the planning protocol or can be invoked.

The same page offers AWS profile setup guidance and optional materials database
connections. AWS runs model inference through Bedrock; it does not move the
workspace into AWS or provision EC2/ECS resources. The current image has no AWS
SSO login wizard. A site administrator must supply a dedicated profile through
the container's approved credential mechanism. See [AWS setup](aws.md).

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
encrypted vault. Create or unlock the vault when prompted; it needs unlocking
after a restart. Without this option, the key stays in server memory only.
Saving, verifying or forgetting a database key does not change model-account
settings. Keys are write-only and stay out of chat and session history.

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

## Persisting credentials

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
another installation's Codex login. Claude currently connects through Anthropic
API or Bedrock; Claude subscription login is not implemented and subscription
tokens must not be pasted into an API-key field.

Session-only storage is the default and loses keys when the server stops.
To remember keys, create an application vault passphrase and choose encrypted
storage. The app derives an encryption key with Scrypt and authenticates the
ciphertext with Fernet. Only ciphertext, salt and version metadata are saved.
The passphrase and derived key remain in server memory. Restart leaves a
passphrase vault locked; unlock it explicitly before starting new research, or
connect another supported account for the session.
For unattended installations an admin may supply `LABCAT_VAULT_KEY` or
`LABCAT_VAULT_KEY_FILE` externally. Never store that key alongside the vault.

Files are workspace-specific and written atomically with restrictive owner
permissions where supported. No storage is incorruptible: tampered or unreadable
files produce redacted errors and preserve the existing file. Reset removes only
the application's vault and requires confirmation; lost keys cannot be recovered.
This is encryption at rest, not protection from an attacker controlling the
running OS process. Workspace conversation history is separate from the vault.

An interrupted connection save leaves a non-secret pending marker. On restart,
the app keeps research unavailable until an explicit successful save or selection
clears it and the connection is checked. Failed saves restore the previous
in-memory credentials and encrypted vault
when possible; reload the connection status after an error before retrying.

## Tests and costs

Connection tests are explicit metadata/identity checks. They report whether
inference was tested; none invokes a model or creates cloud resources. AWS STS
success establishes identity only. Bedrock availability is not proof that the
selected model can be invoked. Hosted model planning requires a separate saved
consent choice; prompts and bounded project context will be transmitted and
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
