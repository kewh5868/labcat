# Model connections and evidence boundaries

New research requires a connected model account and a selected model. First-run
setup guides the user through connecting and checking that account; there is no
model-free or local-Ollama bypass in this release. The application and research
workspace still run locally by default. The Docker application embeds Goose for
model orchestration.
A model can request a bounded set of server-owned research stages. It cannot supply
scientific facts, choose arbitrary destinations or replace the report. See the
[Goose and sign-in guide](goose.md) for the complete runtime boundary.

| Connection      | Authentication                                              | Model selection                                                    |
| --------------- | ----------------------------------------------------------- | ------------------------------------------------------------------ |
| ChatGPT         | Goose-owned browser OAuth, session or encrypted credentials | Account-reported model catalog                                     |
| OpenAI Platform | OpenAI API key                                              | Provider catalog or configured identifier                          |
| Anthropic       | Anthropic API key                                           | Provider catalog or configured identifier                          |
| Kimi            | Moonshot API key                                            | Provider catalog or configured identifier                          |
| Google Gemini   | Gemini API key                                              | Google OpenAI-compatible model catalog                             |
| DeepSeek        | DeepSeek API key                                            | Provider catalog or configured identifier                          |
| xAI / Grok      | xAI API key                                                 | Provider catalog or configured identifier                          |
| OpenRouter      | OpenRouter API key                                          | Account-filtered model catalog                                     |
| Local Ollama    | Local service connection retained for future optional use   | Does not satisfy the current account-required setup                |
| AWS Bedrock     | Existing AWS profile/SSO session                            | Regional foundation-model and active inference-profile identifiers |

Choose a provider directly in Connections. Existing connection records are retained
internally so switching providers preserves the current ChatGPT account and each
provider's model settings; saved-account management is not a required setup step.
The active provider connection determines the credentials and selected model for a run.
A provider can be connected before choosing a model, but research remains unavailable
until credentials, model selection and hosted-context consent pass the readiness
check. Checks use provider authentication and model metadata; they do not invoke
inference. Research checks the active connection again before retrieving sources.
An expired login or locked vault returns to connection setup and cannot silently
start model-free research.

Consumer subscriptions are not interchangeable with API keys. ChatGPT has the
specific supported sign-in flow described above. Claude subscription login is
not implemented; Claude models currently use Anthropic API or Bedrock access.
Labcat never collects third-party passwords. There is no assumed permanent free
hosted API tier. Local Ollama avoids hosted inference fees but still requires a
model download, memory and compute; it is not an account option in the initial
required-login flow.

The main Docker application uses Goose's native browser authorization and fixed
localhost callback; it does not require a device-code setting. The isolated
configure process stops before model inference. A separate Codex helper reads
account/model/usage metadata. Legacy device configurations are retained without
silently substituting them when browser login fails. See [onboarding](onboarding.md)
for callback availability and credential storage.

ChatGPT account quota windows, optional activity and last-run usage are separate
fields. Missing account balances or token counts remain unavailable. Other
providers currently expose per-run usage only when Goose reports it. No model
request happens merely because the application starts. Provider errors omit
credentials, response bodies and identity details.

Bedrock model selection reads the foundation-model catalog and at most two pages
of 100 active inference profiles using `ListInferenceProfiles`. Cross-region
profile IDs are used exactly as returned; no region prefixes are guessed. If the
account lacks permission to list profiles, foundation models remain available.
Catalog presence does not verify tool support or inference authorization. This
connection supports the isolated Goose AWS-session/Converse path; Goose models
requiring Bedrock Mantle and bearer-token authentication are not supported here.

The plain Python installation retains the existing bounded intent classifier
unless Goose is explicitly enabled. It accepts only a closed six-field enumeration
of task preferences, rejects extra fields and tool calls, and cannot establish
facts. The Docker/desktop workflow records the actual Goose tools and server
completion stages instead. In both modes, saved numeric ranking preferences are
authoritative and reports derive only from independently verified adapter records.

Connection and provider tests use protocol fixtures. Actual live authorization and
inference checks are listed separately in [validation](validation.md), never inferred
from mocked tests. See [onboarding](onboarding.md) for vault and restart behavior.

## Additional API providers

Gemini, DeepSeek, xAI and OpenRouter use their documented OpenAI-compatible Chat
Completions protocols for bounded planning and Goose tool calls. The selected
provider key is passed only to that provider's fixed endpoint. Hosted endpoints
cannot be entered or overridden by a prompt, profile or inherited environment.
The isolated worker's egress permits those four exact provider domains in addition
to the existing providers; it still has no general web destination capability.

Goose 1.50.0 uses an explicit complete `OPENAI_BASE_PATH` for these connections,
including Gemini's `v1beta/openai/chat/completions` and OpenRouter's
`api/v1/chat/completions`. API keys stay in the selected credential storage mode;
using a Gemini, DeepSeek, xAI or OpenRouter key does not reuse a ChatGPT login.
OpenRouter's metadata check uses its authenticated `/api/v1/models/user` route,
which filters models according to the user's provider, privacy and guardrail
settings. It does not treat the public model catalog as proof of authentication.
OpenRouter routes inference through its service and its selected downstream
provider under the user's OpenRouter settings.

These integrations are tested with synthetic provider responses for metadata,
readiness, schema enforcement, selected-key isolation, fixed Goose paths and safe
failure handling. The actual pinned Goose CLI also passed tool-call roundtrips for
all four provider paths in separate network-disabled ARM64 containers with a local
synthetic endpoint, including rejected shell calls and discarded model prose.
No live API credentials were available for these four providers, so successful paid
inference or scientific results are not claimed. Provider model
catalogs may include entries that do not support the required text/tool protocol;
select a compatible language model. Metadata checks do not test inference. The
existing catalog size and response limits remain in effect, and unsupported
responses produce an explicit error rather than silently substituting a model.

Official protocol references:

- [Gemini OpenAI compatibility](https://ai.google.dev/gemini-api/docs/openai)
- [DeepSeek API introduction](https://api-docs.deepseek.com/)
- [xAI Chat Completions](https://docs.x.ai/developers/rest-api-reference/inference/chat-completions)
- [xAI model catalog](https://docs.x.ai/developers/rest-api-reference/inference/models)
- [OpenRouter API overview](https://openrouter.ai/docs/api/reference/overview)
- [OpenRouter account-filtered models](https://openrouter.ai/docs/api/api-reference/models/list-models-filtered-by-user-provider-preferences-privacy-settings-and-guardrails)
