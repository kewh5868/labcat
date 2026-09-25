# Embedded Goose and account sign-in

The Docker image installs checksum-pinned Goose 1.50.0 and the Codex 0.154.0
account helper for Linux ARM64 and AMD64. Native desktop clients use the same
Docker backend. First-run setup requires connecting a supported model account
and choosing a model before new research. Installation or startup does not sign
in, download a model, or invoke a hosted model automatically.

## Connect and run

Every supported hosted connection in the Docker application uses the isolated
Goose worker and the same research tools. ChatGPT is one provider option, not a
requirement. A failed provider request never falls back to a direct model call
or another account.

| Connection         | Authentication                                          | Goose provider                            |
| ------------------ | ------------------------------------------------------- | ----------------------------------------- |
| ChatGPT            | Goose-owned browser OAuth, session or encrypted storage | `chatgpt_codex`                           |
| OpenAI API         | OpenAI Platform API key                                 | `openai`                                  |
| Anthropic / Claude | Anthropic API key                                       | `anthropic`                               |
| Kimi               | Moonshot API key                                        | `openai` with the fixed Moonshot endpoint |
| Amazon Bedrock     | Dedicated AWS profile supplied to the container         | `aws_bedrock`                             |

1. In setup or **Connections**, select a provider. Its name is used automatically.
   Choose session-only credentials or unlock/create the encrypted vault before
   choosing encrypted storage.
2. Complete that provider's supported connection method. For ChatGPT, choose
   **Sign in with ChatGPT**, complete browser authorization on the provider's
   website, and return to Labcat. This native Goose flow does not require
   device-code authorization. Other providers use their API key or configured AWS profile.
   Labcat never asks for a third-party password.
3. Available models load automatically after connecting. Choose one and enable the
   consent setting before sending research context to the selected provider.
4. Check the connection and finish setup. AWS and additional data API credentials
   are optional. Choose a Ranking Profile, review source filters and send a research prompt.
   **Check usage** requests account metadata; it does not invoke inference.

ChatGPT account limits may be reported as percentage windows and reset times.
These are not a remaining-token balance. Account activity and per-run token
usage are displayed only when reported; unsupported fields remain unavailable.
The app does not import another application's login or account usage. The
connection test checks metadata, not the quality or success of a research run.

Anthropic API and AWS Bedrock connections can select Claude models. Claude
subscription sign-in is not implemented. It needs a separate provider-supported
integration; consumer OAuth tokens cannot be pasted into an API-key field.
Local Ollama remains an integration option for future model-free setup, but does not satisfy the current
required account connection.

## Research boundary

Goose runs in its own container using the same distributed image, with all
profile/default extensions disabled and a stripped environment. The container
root is read-only; only private temporary scratch is writable. It has no host
home, Downloads, repository, Docker socket or saved-workspace mount. A separate
proxy permits selected provider connections from its internal Docker network.
It cannot use that proxy to reach arbitrary websites or the app API. Research
source requests run through the app's fixed public adapters. Its extension exposes
five bounded tools:

- `assess_research_intent`: a required closed decision: `materials_research`,
  `needs_clarification`, `out_of_scope`, or `unsafe`.
- `search_public_references`: use saved source filters and a short,
  plain-language class/application topic supplied by the coordinator. The topic
  is a search hint, not evidence.
- `propose_candidate_leads`: select literal material names and exact short quotes
  from the returned public documents. The server validates every selector against
  retained source text. These mentions establish neither properties nor suitability.
- `evaluate_candidate_fit`: interpret application fit, demonstrated use, selected
  attributes and stability using exact passages for admitted candidates. The
  server computes the preliminary priority and attribute refinement; the model
  cannot submit scores or measurements.
- `generate_ranked_report`: retain a preliminary shortlist even when admitted
  candidates have no assessed attributes, alongside any separate validated
  property comparison. Unknown evidence and tied priorities stay explicit.

The fixed [preliminary ranking method](literature-ranking.md) applies across
classes. Source-bound assessments remain qualitative interpretations. An
unassessed named candidate receives only the documented review prior, not a
positive finding or invented application evidence.

Report generation takes empty arguments. The model cannot supply network destinations,
measurements, invented citations, weights, commands, files, credentials or replacement
report text. The server owns retrieval records, source validation, scoring and rendering.
The fixed server intake decision can only be narrowed by the model assessment;
retrieval tools reject calls made before assessment. Model prose is discarded.
Project messages and pinned identifiers are untrusted
context. Public reference discovery runs before repository lookup, regardless of
tool-call order. Bounded titles, read abstracts and encyclopedia introductions
can be supplied to the model as untrusted data for selecting named candidates.
Only literal matches survive validation; a mention cannot establish phase,
property values, stability or suitability. Missing selected attributes can trigger
bounded open-access text searches; cited passages remain unscored review leads.

The model tool schema requires a short search topic covering both the material
class and functional use. The coordinator chooses that phrase rather than taking
the first words of conversational prose. Processing and environmental wish lists
should not displace the functional role. Internal dependency calls and older
clients retain the empty-argument fallback; this does not silently approve an
unassessed request. The full original request still controls identity restrictions
and policy checks; the topic remains a search hint.
Model-facing documents include their source/document identifiers and unchanged
retained text. Navigation metadata remains in the server's complete references,
so redundant fields do not consume the byte budget at the expense of abstracts.

After candidate admission, tool feedback identifies the outstanding general
assessments and remaining assessment batches. The first batch covers application
relevance and demonstrated use for every candidate, including explicit unknowns.
The remaining batch prioritizes user-requested attributes and stability using
already retrieved passages. A premature generation request receives its reminder
before any repository fetch. No extra model call is launched to obtain missing
judgments. Provider completion and candidate-assessment completion are distinct:
an agent can finish its turn while leaving scientific work unattempted.

Each saved result records the actual Build Plan, Ranking Profile, provider/model,
stage ownership, bounded tool activity and reported usage. Discovery and candidate
selection allow one bounded refinement/correction; assessment allows one correction
batch. Once assessment starts, discovery and candidate selection are frozen.
An interrupted model request can complete already-authorized server stages after
accepted intake, preserving available source results without launching another
model request. Skipped or invalid qualitative assessments leave valid candidates
at preliminary priority with unknowns. Missing intake assessment produces
clarification without retrieval; the server never approves it automatically.
Source/data failures cannot erase healthy retained discovery; invalid policy or
preference requests remain blocked. Reports record which stages the server completed.
Clarification and refusal are conversation messages, not pin-able reports.
The wrapper never retries a whole failed run or chooses another paid provider. Goose provider
implementations can retry individual requests internally.

Runs have a 180-second process limit, eight model turns, bounded output and tool-call
limits. This limits exposure; it is not a guaranteed currency budget. No general
shell, browser, arbitrary HTTP, private lab or wetlab extension is enabled.
Broad open-web scraping is not implemented. A fixed Europe PMC adapter can read
available open-access article XML for missing-property follow-up. An enabled
OpenAlex adapter can supply targeted public abstracts within the same search
budget; no publisher pages are downloaded. Article text cannot change tool access.
The approved adapters and evidence limitations are in [scientific sources](scientific-sources.md).

## Credentials and deployment

ChatGPT browser login runs through pinned Goose in the isolated worker. A private
PTY answers only the first two `goose configure` menus. The broker stops the
process at model selection, before Goose's own connectivity-inference test.
Browser authorization has a five-minute window. The callback-only app listener
maps host `127.0.0.1:1455` to container port 1456, then forwards the matching
active OAuth state through the authenticated worker channel to Goose's fixed
`127.0.0.1:1455/auth/callback`. No worker port is published. The relay returns
fixed receipt text; only provider-confirmed completion marks the flow complete.

ChatGPT credentials briefly exist in owner-only files on verified memory-backed
storage in the worker, then move into session memory or the authenticated
encrypted vault. Completion, cancellation, expiry and shutdown remove the
temporary configuration and token files. A completed credential handoff can be
consumed only once. The browser URL is validated for the pinned client, provider,
redirect and PKCE settings; callback codes and provider HTML are not exposed in
application logs or connection responses.
The app and worker must retain their `/tmp` tmpfs mounts for this flow. The
separate read-only worker authentication channel is also memory-backed; it
contains only a random service key, never the workspace or credential vault. Saved vaults remain
locked after restart until unlocked. Host credential directories are not imported.

The Codex helper supplies account/model/usage metadata for the main Docker flow;
Goose owns its browser authorization and bounded inference. The older device
broker remains for legacy configurations and is not an automatic fallback.
Access-token refreshes are serialized with metadata checks
and returned to the selected credential store. Sign-out and vault changes prevent
an older response from restoring removed credentials. External account revocation
is controlled by the provider.

The ordinary Python installation retains the existing closed-enum planner by
default. To use the embedded runtime, launch the Compose application. The app will not
fall back to launching Goose inside the workspace container or on the host. Its pinned
binaries and licenses are included in the image and portable install bundle.
See [validation](validation.md) for actual checks and deployment limitations.

References: [Goose releases](https://github.com/aaif-goose/goose/releases/tag/v1.50.0),
[pinned Goose OAuth provider](https://github.com/aaif-goose/goose/blob/v1.50.0/crates/goose/src/providers/chatgpt_codex.rs),
[pinned configure sequence](https://github.com/aaif-goose/goose/blob/v1.50.0/crates/goose-cli/src/commands/configure.rs),
[Codex app-server](https://learn.chatgpt.com/docs/app-server),
[Codex authentication](https://learn.chatgpt.com/docs/auth),
[Claude Code legal and compliance](https://code.claude.com/docs/en/legal-and-compliance).

### Partial research and completion budget

The model receives three minutes for one bounded run; the eight-turn/eight-tool
limits still apply. The desktop client and live evaluator allow five minutes for
the full request so selected public-source completion and report saving can
finish after model interruption. This is not an inference retry. Status polling
continues while the request runs.

When a materials request has enough subject and application context, missing
numerical targets do not by themselves require clarification. An incomplete
catalog interpretation returns a structured correction before intake is frozen.
The agent is instructed to submit application/use judgments for the candidate
set early. Feedback identifies missing candidate assessments and permits one
completion reminder within the existing two-batch and tool limits. Explicit
unknown judgments remain unknown; they do not earn suitability credit.

Interrupted results retain the requested model and, when the parent worker call
establishes it, the attempted model. A fixed failure-code vocabulary distinguishes
runtime, output-size, process and usage-metadata failures without saving provider
error bodies or credentials. Missing usage remains unavailable, never a zero
usage claim. Historical reports without these fields retain their original data.
