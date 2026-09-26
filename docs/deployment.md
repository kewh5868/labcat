# Installation and portable delivery

## Supported target

The React/TypeScript interface is compiled during the image build and served
by FastAPI. Node is not installed in the final image. One image contains the
Python service, CLI, browser assets and pinned agent binaries. Compose runs it
in three roles: the workspace app, an isolated Goose worker, and a restricted
provider-network proxy. Only the app has the persistent workspace volume. The
worker has an internal network and no host folders, Docker socket or workspace
mount. Native report exports add files only to the OS Downloads folder; Goose
cannot browse that folder. Browser-mode downloads follow the browser settings.

The delivery target is a versioned **Linux container**, supplied for both
`linux/amd64` (Intel/AMD) and `linux/arm64` (ARM). The same application code and
version run on macOS, Windows and Linux through a compatible container runtime.
A container image is not a bootable VM disk. The optional Tauri desktop shell
is a separate native executable around the same Docker-hosted interface.

| Host                   | Runtime prerequisite                                             | Image choice                          |
| ---------------------- | ---------------------------------------------------------------- | ------------------------------------- |
| macOS on Intel         | Docker Desktop or compatible Linux-container runtime             | amd64                                 |
| macOS on Apple Silicon | Docker Desktop or compatible Linux-container runtime             | arm64                                 |
| Windows on Intel/AMD   | Docker Desktop with Linux containers, typically WSL 2            | amd64                                 |
| Windows on ARM         | A runtime supporting Linux ARM containers; verify the host setup | arm64, pending target-host validation |
| Linux                  | Docker Engine or a tested compatible runtime                     | Match the host CPU                    |

Host/runtime support and virtualization requirements still apply; this is not a
claim that every OS version or computer can run Docker. Consult current
[Docker Desktop installation requirements](https://docs.docker.com/desktop/)
or [Docker Engine installation](https://docs.docker.com/engine/install/).

## Primary end-user path: load an image and open a window

For a source checkout without an install archive, follow the
[README Docker quick start](installation.md): build
`labcat:0.1.0.dev0` once, then run the supplied launcher. The following
bundle instructions are an alternative; an archive is not required to build from source.

**Local development archives are generated in `dist/`.** Use the validation
record and checksum for the exact artifact: an older archive may predate recent
source changes. The prototype searches live public sources across material classes
and preserves retrieved provenance; it does not establish experimental suitability.
No image/archive is published to an external registry. The manual CI image
workflow is configured to build and smoke-test both architectures, then retain
install ZIPs and SHA-256 checksums
as artifacts. ZIPs contain the image archive, its checksum, Compose file, host
launchers and instructions. Promote only verified artifacts. Each archive must
identify application version and architecture.

Extract the complete install ZIP into a folder and keep the launchers beside
`compose.yaml`. Verify the supplied checksum and load the matching archive once
(example amd64 artifact):

```text
docker load --input labcat-0.1.0.dev0-linux-amd64.tar
```

Substitute the arm64 archive on an ARM host. When using the source checkout,
prefix the archive path with `dist/`. Then start the UI:

| Host    | Launch                                                      | Stop               | Find the running UI address |
| ------- | ----------------------------------------------------------- | ------------------ | --------------------------- |
| Mac     | Open `Labcat.app`, `Start Labcat.command`, or `./labcat.sh` | `./labcat.sh stop` | `./labcat.sh status`        |
| Windows | Open `Labcat.exe`, or double-click `labcat.cmd`             | `labcat.cmd stop`  | `labcat.cmd status`         |
| Linux   | `./labcat.sh`                                               | `./labcat.sh stop` | `./labcat.sh status`        |

**No installed Chrome browser is required.** A native install bundle contains
the standalone application under `desktop-bin/`. It uses the operating system's
webview: WKWebView on macOS, WebView2 Runtime on Windows, and WebKitGTK on Linux.
The webview is an OS/runtime component, not a requirement to install the Edge or
Chrome browser. See [Tauri's webview requirements](https://v2.tauri.app/reference/webview-versions/).
Linux requires WebKitGTK 4.1; Windows may need a WebView2 Runtime installation.
These desktop prerequisites do not apply to command-line or browser mode.

Opening the native application directly starts/reuses the backend and displays
startup progress or an error in its own window. The small script launchers prefer
that native shell when bundled. Portable image-only bundles fall back to the
default browser. The Mac `.command` entry point shows progress in Terminal.
No Python, Node, Git or compiler is required to run a prebuilt install bundle.

The launcher checks Docker, waits for the container's health check, discovers
its local address, and opens the window. It uses one stable Compose project
named `labcat`, including when launched from another directory. Reopening
reuses the service. Docker allocates an available loopback port; the URL can
change after a stop/restart or recreation, so use the launcher instead of an old
bookmark. Only the Compose-managed application services are stopped by the stop command.
Other containers, including old manually launched copies, are left alone.

The launchers also load an optional private `compose.local.yaml` beside them to retain installation-specific volumes, credential mounts and other deployment settings.

Closing a UI window does not stop the service. For no window, use
`./labcat.sh start --no-open` or `labcat.cmd start -NoOpen`.
To force your default browser, use `./labcat.sh --browser` or
`labcat.cmd -Browser`; the same local URL can be opened manually in a modern
browser of your choice. No browser-specific extension or API is used.
For a command that needs no GUI or running web server, use
`./labcat.sh cli status --style audit --format json` or
`labcat.cmd cli status --style audit --format json`. This runs the shared CLI
in a temporary container. For public-source research, use
`./labcat.sh cli research "Find oxide dielectric candidates" --style audit --format json`
(Windows: `labcat.cmd cli research "Find oxide dielectric candidates" --style audit --format json`).
Research starts or reuses the full Compose application without opening a window.
The CLI executes inside the application container and submits one stateless
request to its fixed loopback service, using the already connected model,
ranking profiles and source settings. It does not add a chat or copy credentials
out of the server. Complete model setup first; after restarting, unlock a saved
vault or reconnect a session-only account before research. An optional
`--ranking-profile PROFILE_ID` selects a saved profile; otherwise the request
infers one from the prompt. Use text or JSON stdout for headless output. No host
folder is mounted into any of these services.

Status/configuration commands run in an isolated temporary container without
access to saved accounts. Add `--offline` immediately after `cli` to disable
container networking: `./labcat.sh cli --offline status --format json` or
`labcat.cmd cli --offline status --format json`. Offline research refuses to
start without a connected model. Launcher help is available
through `./labcat.sh --help` or `labcat.cmd help`.
View diagnostics with `./labcat.sh logs` or `labcat.cmd logs`.
The image contains no local LLM weights. First-run setup requires a supported
model account; optional AWS and research data APIs can be skipped. Setup does
not download a model, invoke inference or provision cloud resources.

### Checksums

Before loading a supplied archive, calculate its SHA-256 digest and compare it
with the matching `.tar.sha256` file in the bundle. Substitute your archive's
actual filename in these examples:

| Host               | Calculate the digest                                                 |
| ------------------ | -------------------------------------------------------------------- |
| macOS              | `shasum -a 256 labcat-0.1.0.dev0-linux-arm64.tar`                    |
| Linux              | `sha256sum labcat-0.1.0.dev0-linux-amd64.tar`                        |
| Windows PowerShell | `Get-FileHash .\labcat-0.1.0.dev0-linux-amd64.tar -Algorithm SHA256` |

The full digest must match. If it does not, obtain an intact copy before loading
it. A matching checksum detects altered bytes; it does not establish that a
bundle is current or from a trusted distributor.

### Model setup and optional connections

First launch opens the Model, Compute, Public sources and Ready setup steps.
Choose **Model provider** and connect ChatGPT through Goose-owned browser
authorization, one of the API providers through its API key, or Bedrock through
an existing container-provisioned AWS profile. Select a model, enable the
hosted-context consent, then choose **Save and test connections**. Once verified,
choose **Continue** through the optional steps and **Finish setup** on Ready to
open the main workspace. **Verify connection** checks already-saved settings;
unsaved changes must first be saved.
New research requires a connected account; the prior model-free and local-Ollama
paths do not qualify in this release. The application and workspace run locally
by default. Optional Bedrock offloads model inference to AWS; it does not host
the entire application there. AWS profile setup requires site configuration;
an interactive AWS SSO wizard is not included.

Supported keyless data APIs include NOMAD, HybriD³, Europe PMC and arXiv. A
Materials Project API key adds its live quantitative source. These data API
connections are optional and multiple services can be selected together.
Hosted model use requires explicit cost and data consent. It sends bounded
prompt/project context to the chosen model. Goose can request only the fixed
public-search and ranked-report stages; it cannot create scientific facts or
select arbitrary network destinations. The direct Python planner uses closed
intent enums instead of Goose tools.
Model-list checks do not prove inference authorization. AWS checks use STS and
do not prove Bedrock model access. No connection check invokes a paid model.

Nonsecret profiles survive restart. Keys are session-only by default; optional
encrypted storage uses a dedicated vault passphrase or a deployment-provided
`LABCAT_VAULT_KEY` / `LABCAT_VAULT_KEY_FILE`. Never bake these into an image.
Passphrase vaults restart locked; unlocking restores encrypted keys. An external
key can support automatic unlock when supplied by the deployment. The app writes
no plaintext credentials or passphrases to SQLite, ordinary config, browser
storage or logs. See [connection setup](onboarding.md) for storage and recovery.

### ChatGPT browser callback

Goose's pinned OAuth provider redirects to
`http://localhost:1455/auth/callback`. Compose publishes host
`127.0.0.1:1455` to the app's callback-only port 1456. That listener forwards
only the matching pending flow through the authenticated private worker channel
to Goose's own loopback listener. The worker has no published port; the callback
listener exposes neither the workspace API nor an arbitrary forwarding service.
It discards provider response HTML and returns fixed receipt text. Login is
complete only after Goose confirms authorization and reaches model selection;
the broker then terminates configure before its built-in model test.

The supplied launcher detects a collision on port 1455 without stopping the
other service. It uses `LABCAT_OAUTH_CALLBACK_PORT=0` to keep the workspace
running with new ChatGPT browser login disabled. Already saved connections and
other supported providers remain usable. Finish the conflicting login process
and explicitly relaunch with `LABCAT_OAUTH_CALLBACK_PORT=1455` to restore browser
sign-in. Reopening a running disabled deployment preserves it, including its
session credentials, rather than recreating its containers unexpectedly.
On macOS/Linux, run `LABCAT_OAUTH_CALLBACK_PORT=1455 ./labcat.sh start`.
In PowerShell, set `$env:LABCAT_OAUTH_CALLBACK_PORT = '1455'`, then run
`labcat.cmd start`. Administrators can also set
that variable to `0` explicitly for a deployment without browser OAuth. Do not
set an arbitrary alternate callback port: Goose's registered redirect remains 1455. Direct Compose users must handle a conflicting port themselves or choose
the disabled mode. This callback recipe targets a local Docker engine and a
browser on the same host; a remote deployment needs a reviewed tunnel.

Closing setup allows reviewing saved workspace contents without enabling new
research. Selecting legacy local defaults cannot bypass the model requirement.
Local computation does not imply offline public-data retrieval. A model failure
does not silently run model-free research or select another provider. Shared ECS hosting remains a separate,
planned deployment requiring identity, authorization and operational controls.

### Saved projects and chat history

The Compose service stores projects, chats, paired PI/technical overview reports, source
relationships, pins, ranking profiles and presentation preferences in
`workspace.sqlite3` under `/var/lib/labcat`. Its
named `workspace-data` volume survives normal launcher stops, restarts, and
container recreation. Keep the same Compose project name, `labcat`, to
reuse that workspace. The rest of the container filesystem remains read-only;
the application runs as a non-root user with a private data directory.

Scientific messages query selected public repositories before targeted searches
for missing attributes in available open-access text. Optional database credentials
add coverage. Discovery metadata and cited literature passages remain separate
from verified property evidence.
Only verified property records can support scores. Unavailable or offline sources
produce explicit evidence gaps, never predetermined materials or measurements.
Pinned reports and saved messages are reusable project context, never independent
scientific evidence. Project moves preserve history and move report/source
associations while clearing the moved chat's report pins from its previous project.

Search Criterion contains ranking profiles and selected public-source filters.
Connections manages the credentials; keyed APIs require a successful connection
check before use. Report Format contains presentation controls and format previews.
The currently active profile appears above the editing preview. Property category
headings appear directly; new selections start at 0.5 importance. Existing saved
weights are retained. Built-in or custom class/application profiles define
the selected attributes. Each
attribute importance is independently entered from zero to one and normalized
across selected criteria; unavailable attributes retain weight and contribute
zero. Profiles organize research across material classes; source coverage and
implemented scoring functions determine the available quantitative assessment.
A class label does not supply missing measurements or validate an application.
Changes affect new reports, while saved reports retain their original contents.
Report Format controls include PI Summary and/or Technical Overview output, verbosity,
general/research/specialist terminology, and TXT/JSON/PDF/Word formats. Downloads
read saved evidence using current Report Format preferences for ordinary and
tracked project reports; pinned snapshots retain their recorded format.
Formatting does not rerun retrieval or change saved evidence, rankings, the
original report archive or legacy prose. Layouts include paper size, font,
spacing, accent, table style
and page numbers. TXT width and JSON indentation apply to their respective exports.
Template previews contain placeholders, not scientific results. Word pagination
can vary with the document reader. See [developer edition setup](developer-mode.md)
for optional bounded deployment controls. Consult
the validation record for the exact image and host checks.

Closing the window or using the launcher `stop` command preserves this data.
Removing the named volume, including with `docker compose down --volumes`, deletes
it. Stop the service before backing up workspace records, and use the site's
supported volume-backup procedure. Do not copy credentials, vault keys or
passphrases into ordinary backups. The SQLite history and nonsecret
`workspace.connections.json` profile can be restored without preserving login
secrets; re-enter credentials afterward. Scientific history itself is not encrypted
by the application; host and volume access controls protect it. Optional credential
ciphertext is separate in `workspace.credentials.enc.json`. Credentials do not
belong in chats or the database, and vault storage is not promised to be incorruptible.

For native Python service runs, the default database locations are:

| Host    | Default database                                                                        |
| ------- | --------------------------------------------------------------------------------------- |
| macOS   | `~/Library/Application Support/Labcat/workspace.sqlite3`                                |
| Windows | `%LOCALAPPDATA%\Labcat\workspace.sqlite3`                                               |
| Linux   | `$XDG_DATA_HOME/labcat/workspace.sqlite3`, or `~/.local/share/labcat/workspace.sqlite3` |

Set `LABCAT_DATA_DIR` to select another data directory before starting the
service. In a container, a changed directory also needs an appropriate writable
volume and ownership. Changing this environment variable does not move existing
history. The service rejects unsupported database schema versions rather than
silently resetting them; back up data before upgrades and verify both application
and database compatibility before rollback.

### Troubleshooting

- **No window after `docker run`:** that command starts the server only. Use the
  supplied host launcher to open the window. A container cannot open a host
  window by itself with this deployment.
- **Port 8000 already allocated:** use the launcher; it requests a free port
  without stopping other applications. Repeating a raw fixed-port `docker run`
  will still conflict with any existing service on that port.
- **ChatGPT callback port unavailable:** port 1455 is fixed by Goose's provider.
  The launcher keeps the workspace available with new browser sign-in disabled.
  Finish the other login process, relaunch with
  `LABCAT_OAUTH_CALLBACK_PORT=1455`, and start a fresh sign-in.
  Changing a vault passphrase or selecting another arbitrary port cannot fix it.
- **Docker unavailable:** start Docker Desktop, or your local Docker Engine,
  and retry. Compose must support `up --wait --wait-timeout`.
- **Image unavailable:** build from source with `docker build -t labcat:0.1.0.dev0 .`
  in the repository root, or run `docker load` for your matching supplied archive.
  Startup never downloads another image silently.
- **macOS/Linux permission denied:** preserve executable permissions when
  extracting, or run `chmod +x labcat.sh 'Start Labcat.command'` once.
- **Windows script policy:** the `.cmd` wrapper uses Windows PowerShell without
  bypassing execution policy. If your site blocks local scripts, ask site IT to
  approve/sign the launcher. The direct Compose route below remains available.
- **Native app prerequisites:** use the default-browser or headless mode when
  the host's webview is unavailable. Native release builds need per-OS testing
  and normal code-signing/notarization before broad distribution; local
  development builds do not establish that release gate.
- **Remote Docker context:** switch to your local Docker context. These desktop
  launchers refuse remote endpoints because their loopback address is not this
  machine. AWS hosting is a separate deployment path.
- **Headless Linux/VM:** use the printed address on that host, or an SSH tunnel
  to its loopback port. Do not expose the single-user service publicly.
  Host/Origin checks and connection CSRF protection are not user authentication.

### Direct Docker Compose route

If you want to manage the server manually without opening a window:

```text
docker compose --project-name labcat up --detach --wait --wait-timeout 60
docker compose --project-name labcat port labcat 8000
```

Open `http://` followed by the printed `127.0.0.1:PORT` in your browser. Stop with
`docker compose --project-name labcat stop`. Run these commands beside the
supplied `compose.yaml`. The binding is local to this machine; shared hosting
requires authentication. The use of an omitted host port and Compose reuse is
documented in [Docker port mappings](https://docs.docker.com/reference/compose-file/services/#ports)
and [Compose startup](https://docs.docker.com/reference/cli/docker/compose/up/).

After completing setup in that server, invoke the same research engine directly:

```text
docker compose --project-name labcat exec --no-TTY labcat labcat research --server "Find materials for optical applications" --format json
```

The client accepts only the fixed same-container loopback backend. It cannot
target arbitrary servers, import host account files or retry a failed model run.

For a command-line status run with no container network:

```text
docker run --rm --pull never --network none labcat:0.1.0.dev0 status --style audit --format json
```

## Developer path: build locally

```text
docker build -t labcat:0.1.0.dev0 .
./labcat.sh
```

The build uses pinned, hashed runtime/build dependencies and an allowlisted
build context. It excludes the private brief, Git history, local config, model
credentials and runtime records. The application runs as a non-root user.
The Python and Node base images are pinned to multi-platform manifest digests.
Update these deliberately and record the resulting image ID/digest alongside
the application version. Pinned inputs do not alone guarantee byte-for-byte
reproducible builds.

Use a read-only mount of a specific configuration file when needed, not a mount
of the repository or lab filesystem. AWS profiles and source credentials must
never be baked into an image. Local mode does not require them. See [AWS setup](aws.md).
Deployment-wide egress restrictions require an explicit network
design; these container flags alone do not implement a public-source firewall.

To create an install ZIP from an existing image archive and its checksum:

```text
python scripts/build_install_bundle.py dist/labcat-0.1.0.dev0-linux-arm64.tar
```

This packaging step verifies the image checksum and includes an explicit list
of public install files; it does not copy the project folder or private notes.

For a macOS native bundle after building the desktop shell:

```text
python scripts/build_install_bundle.py dist/labcat-0.1.0.dev0-linux-arm64.tar --host macos --desktop-app "desktop/target/release/bundle/macos/Labcat.app"
```

This creates `labcat-0.1.0.dev0-macos-arm64.zip` with the app in
`desktop-bin/`. Windows/Linux native bundles include fixed adjacent launcher
resources as well as the executable; do not distribute a binary alone. Build
instructions and native OS prerequisites are in [the desktop shell guide](https://github.com/kewh5868/labcat/blob/main/desktop/README.md).
The native CI workflow builds per-OS artifacts; those jobs still need to run on
the target systems before their results can be claimed.

## Version and platform verification

- Native CI builds the React interface and runs package/interface/config/AWS-mock tests on macOS, Windows and
  Linux with Python 3.11 and 3.13. These jobs are configured; they have not run
  on a remote repository in this setup session.
- The manual container workflow builds amd64 and arm64 images and runs isolated
  health, UI/API, offline CLI, and workspace-persistence checks on Linux (ARM via
  emulation), including saved messages and pins across container recreation.
  It emits archives only after success. Emulation does not replace a host test.
- Before calling a version portable, install the exact versioned archive on
  macOS, Windows and Linux, record runtime/OS/CPU versions and checksums, and test
  start, browser access, both report styles, CLI, stop and restart.
- Test upgrades by loading a new tag; retain the old tag for rollback. Avoid a
  floating `latest` tag for an interview demonstration or site installation.

Local validation includes macOS/Python 3.13, the ARM64 Linux container on Docker
Desktop, and the AMD64 Linux container under emulation. Windows and native Linux
host installation tests remain pending; configured CI has not run remotely.
See [the validation record](validation.md) for exact checks and limitations.
