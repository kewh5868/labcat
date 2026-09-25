# Independent Goose + ChatGPT browser-login test

This diagnostic installs checksum-pinned **Goose 1.50.0** in its own image with
a small Python standard-library harness. It contains no Labcat package,
Codex helper, scientific data or API key. It does not use the installed app's
settings or credentials. The user signs in directly on the provider's website.

The main Labcat Docker application now uses the same native Goose browser
authorization approach with its own private worker, callback relay and encrypted
storage integration. This independent diagnostic remains disposable and never
imports or exports the application's login. Main-application live authorization
and report-generation validation are recorded separately in [validation](validation.md).

## Run on macOS, Windows or Linux

Install Docker with Linux-container support and Compose. Run these commands from
the repository root; they work in PowerShell and macOS/Linux terminals:

```sh
docker compose -f docker/goose-chatgpt/compose.yaml up --build -d
docker compose -f docker/goose-chatgpt/compose.yaml port goose 8080
```

The second command prints a local address, such as `127.0.0.1:54321`. Open
`http://` followed by that address in your ordinary browser, then select
**Sign in with ChatGPT**. If the browser blocks the popup, use **Open ChatGPT
sign-in** on the diagnostic page. No Chrome dependency is required.

The provider login must finish within Goose's five-minute window. After login,
the diagnostic automatically asks `gpt-5.6-luna` to reply `Connected.` in two
separate Goose processes. The second process verifies reuse of the cached
login. The page reports actual completion and per-request token usage when
Goose supplies it. It does not display an account balance or claim access to
every model in Goose's static catalog.

The requests use the account's allowance. Each has one turn, no enabled tools,
reasoning set to `none`, a 90-second timeout and a bounded captured response.
This Goose provider does not enforce a maximum output-token setting; these
limits must not be described as a hard token/spend cap. The expected reply is
a diagnostic assertion, not a synthetic model response or scientific result.

To stop the test and erase its temporary login:

```sh
docker compose -f docker/goose-chatgpt/compose.yaml down
```

The initial development test was launched directly as
`goose-chatgpt-standalone`. If it is still running, stop that specific container
before starting Compose: `docker stop goose-chatgpt-standalone`. This affects
only the diagnostic. Stopping it clears its login and requires sign-in again.

## Browser callback and isolation

Goose's native ChatGPT provider uses browser authorization with PKCE. Its
redirect is fixed at `http://localhost:1455/auth/callback`, and its listener
binds to the container's loopback address. Publishing container port 1455
directly therefore does not reach that listener. The harness relays only the
fixed callback route:

```text
Provider website → browser → host localhost:1455
                                  ↓ Docker loopback-only publish
                            container :1456
                                  ↓ fixed HTTP relay
                            container 127.0.0.1:1455 → Goose OAuth
```

Port 1455 must be free on the browser's machine. If another login process owns
it, finish or close that process first. Do not kill arbitrary services or change
the redirect port: it is fixed by this Goose version. The diagnostic page itself
gets a free port automatically. A remote Docker engine would additionally need
an explicitly configured local port tunnel; this recipe targets local Docker.

The image runs as an unprivileged user, with a read-only root filesystem,
capabilities dropped, no privilege escalation, resource limits and no host
mounts. All Goose configuration, logs and credentials are on temporary
memory-backed `/tmp`. No host Goose/Codex profile, browser credential store,
Labcat workspace, Docker socket or Downloads folder is mounted. This test
does not need to write any downloaded files.

Goose owns the OAuth state, PKCE verification and token exchange. The browser
URL capture accepts only the reviewed provider, client, redirect and PKCE
parameters. The fixed relay never logs callback queries or auth codes. The
same-origin test page uses a CSRF token for actions and exposes only reviewed
status, exact diagnostic replies and bounded usage counts. Raw model output,
provider errors, account identifiers and tokens are not returned by the page.

An existing nonsecret Goose configuration explicitly disables all extensions.
The harness stops `goose configure` at model selection after OAuth, before its
extra built-in weather-tool test. Its own `goose run` requests use
`--no-profile --no-session` and the selected provider/model. No user-controlled
shell commands, arbitrary prompts or tool configuration are exposed.

This temporary credential lifecycle is for proving the integration. Persistent
encrypted account storage and the Labcat research-tool boundary are separate
application features; this diagnostic does not change either one.

## Actual verification — 2026-09-10

- Native ChatGPT browser OAuth completed in the independent Linux ARM64
  container on Docker Desktop for macOS, without an API key.
- Both real `gpt-5.6-luna` requests completed with the exact expected reply.
  Each reported 293 input and 6 output tokens (299 total). The second Goose
  process reused the same temporary login without another provider sign-in.
- The host-browser callback relay passed a separate synthetic transport check
  before login. Inspection confirmed no host mounts and the documented
  read-only, unprivileged container settings.
- Actual Goose configuration was also exercised with a simulated provider and
  external networking disabled in ARM64 and AMD64 Linux images. AMD64 runs
  under Docker emulation on this Mac. These simulated checks establish no
  additional real-account access.
- Native Windows/Linux browser login and other provider accounts have not been
  exercised. The cross-platform recipe is not proof of those environments.

A separate live research diagnostic, `scripts/smoke_goose_public_web.py`, reused
the isolated login to exercise only fixed Europe PMC open-access search and XML
retrieval tools. It retrieved actual public responses and preserved source IDs,
retrieval URLs, times and response digests. It did not use a general web crawler,
closed sources or preset scientific results.

The initial literal-quote check passed with `gpt-5.6-luna` and `gpt-5.5` but
rejected `gpt-5.6-terra` with `quote_not_in_retrieved_fulltext`. That rejection is
retained: model-written text was not silently treated as source evidence. The
follow-up span-selection mode lets the model choose only a returned source ID
and quote ID; the application validates that selection and assembles the literal
quote and citation from its retrieved response. All three models passed that
mode, reporting 3,326, 3,832 and 3,844 total tokens respectively. These bounded
retrieval checks do not establish scientific accuracy, exhaustive source coverage
or successful ranked-report generation through the main application.

The live proof used image
`sha256:cae74547bab7bc25279a600c61a1a4d8e0a8f91c390076f898b7758689dca130`.
Subsequent diagnostic hardening adds stricter response validation and retry
handling; it does not update the running Labcat installation.

Primary implementation references:
[pinned Goose ChatGPT provider](https://github.com/aaif-goose/goose/blob/v1.50.0/crates/goose/src/providers/chatgpt_codex.rs),
[pinned Goose setup](https://github.com/aaif-goose/goose/blob/v1.50.0/crates/goose-cli/src/commands/configure.rs),
and [official Codex authentication guidance](https://developers.openai.com/codex/auth/).
