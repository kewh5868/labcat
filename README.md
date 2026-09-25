# Labcat

**Curious. Clever. Companionable.**

A local materials-research workspace built with React/TypeScript, FastAPI and a
shared Python CLI, using a scikit-package Level 4 foundation. One Docker image
contains the runtime; an optional Tauri shell opens a native application window.

The prototype discovers materials from public sources and saves paired Summary
and Technical View reports, citations and ranking provenance. A preliminary
shortlist uses cited application evidence; validated material properties provide
an additional ranking. Missing measurements remain explicit. Coverage and answer
quality vary by material class and source, and the research audit is still in
progress. Results are provisional screening aids. See [how ranking works](docs/ranking.md).

## Run with Docker

**Already installed?** Start Docker, open a terminal in your Labcat folder, and
run `./labcat.sh` on Mac/Linux or `.\labcat.cmd` in Windows PowerShell. Skip
building/loading the image and go to [everyday use](#everyday-use).

### 1. Install and start Docker

- **Mac or Windows:** install [Docker Desktop](https://docs.docker.com/desktop/)
  and open it. On Windows, use Linux containers.
- **Linux:** install [Docker Engine](https://docs.docker.com/engine/install/) and
  the [Compose plugin](https://docs.docker.com/compose/install/linux/), then start
  the Docker service.

Wait until Docker is running. These commands should succeed in Terminal or
PowerShell:

```text
docker info
docker compose version
```

Use a local Docker context. The Docker route builds the frontend and Python
runtime inside the image; you do **not** need Python, Node, Rust or a separate
Goose installation on your computer. Internet access is needed for the initial
build, provider sign-in and live research.

### 2. Build from source, or load a supplied bundle

**From this repository:** download/extract or clone the source, then open a
terminal in the folder containing `Dockerfile`, `compose.yaml` and `labcat.sh`.
Build once with this exact image tag:

```text
docker build -t labcat:0.1.0.dev0 .
```

The first build downloads dependencies and can take several minutes. Wait for
it to finish successfully before launching. Docker builds for your computer's
architecture by default. You do not need to rebuild each time you use the app.

**If you received an install ZIP instead:** extract the entire bundle, keep its
launcher files beside `compose.yaml`, and open a terminal in that extracted
folder. Verify the supplied checksum using the [installation guide](docs/deployment.md#checksums),
then load its image archive once. For example, on Apple Silicon/ARM:

```text
docker load --input labcat-0.1.0.dev0-linux-arm64.tar
```

Use the `linux-amd64.tar` archive on Intel/AMD computers. Build **or** load;
there is no need to do both. This project does not currently publish an image to
a registry. Local development bundles under `dist/`, when present, may predate
the current source; use a bundle's own version and validation record.

### 3. Open Labcat

From that same folder, run:

| Mac / Linux             | Windows PowerShell      |
| ----------------------- | ----------------------- |
| `./labcat.sh --browser` | `.\labcat.cmd -Browser` |

The launcher starts the three application services, waits for readiness, prints
a local address such as `http://127.0.0.1:PORT/`, and opens your browser. Use the
actual URL it prints; the port is chosen automatically and is not necessarily 8000. If no
window opens, paste that URL into a browser on the same computer.

To open a bundled native desktop window instead, use `./labcat.sh` or
`.\labcat.cmd` without the browser flag. If no native shell is present, this
also opens the browser. Both interfaces use the same Docker workspace.

### 4. Complete first-time setup

1. **Model:** choose **Model provider**. For a ChatGPT subscription/account,
   select **ChatGPT**, choose **Sign in with ChatGPT**, open the sign-in page and
   finish authorization in your browser. Return to Labcat afterward; do not
   paste your password into the app. For **OpenAI API**, **Anthropic**, **Gemini**,
   **Kimi**, **DeepSeek**, **xAI** or **OpenRouter**, enter that provider's API key,
   then choose **Connect [provider]** or **Save API key** to load its models.
   **Amazon Bedrock** needs a provisioned AWS profile; see [AWS setup](docs/aws.md).
2. Select an available model and enable the consent checkbox for sending research
   context to that provider. Choose **Save and test connections**, wait for a
   successful result, then **Continue**. If the settings are already saved,
   **Verify connection** checks them again. Unsaved model or consent changes
   must be saved before Continue is enabled. These checks do not run inference.
3. **Compute:** keep the default local workspace. AWS configuration is optional;
   local workspace processing still uses your selected model provider for AI.
4. **Public sources:** keep the public databases you want to search. A
   **Materials Project** API key is optional; enter and verify it on its database
   card if you have one. You can adjust database choices later in **Search Criterion**.
5. **Ready:** review the selected model, then choose **Finish setup** to enter the
   main workspace. Start a **New chat**, or create a project and write your
   research question. Actual research uses the selected provider and may consume
   its allowance or incur charges.

ChatGPT account sign-in and OpenAI API billing are separate connection options.
The normal ChatGPT browser flow does not require device-code authorization.
Credentials stay in memory for the server session by default. To retain supported
credentials across restarts, create/unlock the vault under **Advanced credential
options** and choose encrypted storage. A passphrase vault must be unlocked after
restart. Without persistence, sign in or enter the API key again after stopping
the server. Chats, reports and settings persist independently of login credentials.
See [connection setup and recovery](docs/onboarding.md).

## Everyday use

Start Docker first, then run these commands from the source or extracted bundle
folder. You can also double-click a bundled native Labcat application.

| Action                          | Mac / Linux                   | Windows PowerShell           |
| ------------------------------- | ----------------------------- | ---------------------------- |
| Open the app                    | `./labcat.sh`                 | `.\labcat.cmd`               |
| Open in a browser               | `./labcat.sh --browser`       | `.\labcat.cmd -Browser`      |
| Start without opening a window  | `./labcat.sh start --no-open` | `.\labcat.cmd start -NoOpen` |
| Show status and current address | `./labcat.sh status`          | `.\labcat.cmd status`        |
| Stop, keeping saved work        | `./labcat.sh stop`            | `.\labcat.cmd stop`          |
| Read recent application logs    | `./labcat.sh logs`            | `.\labcat.cmd logs`          |

**Restart:** run the stop command, then the open/start command. There is no
`restart` launcher action. Closing the app window does not stop Docker or the
backend. After a computer restart, start Docker and launch Labcat again.
Repeated launches normally reuse the service; an image/configuration update can
recreate containers and require signing in or unlocking the vault again.

By default, saved work lives in Docker volume **`labcat_workspace-data`**. The supplied
launchers use the stable Compose project **`labcat`**. Keep the same Docker
context and project name to use existing history, including history created in
the native desktop app. Normal stopping preserves this volume. **Do not use
`docker compose down --volumes`, prune volumes, or reset Docker Desktop to stop
or update Labcat:** those actions can delete saved work. See [backup and storage](docs/deployment.md#saved-projects-and-chat-history).

The launchers also load an optional private `compose.local.yaml` beside them to retain installation-specific volumes, credential mounts and other deployment settings.

### Start directly with Compose

The launchers are the easiest path, but these commands also work from the folder
containing `compose.yaml`, after building or loading the image:

```text
docker compose --project-name labcat --file compose.yaml up --detach --wait --wait-timeout 60
docker compose --project-name labcat --file compose.yaml port labcat 8000
```

Open `http://` followed by the returned address. Stop with:

```text
docker compose --project-name labcat --file compose.yaml stop
```

Compose does not build the image or open a browser here. The launcher also handles
a busy ChatGPT callback port; direct Compose startup does not provide that fallback.

### If something does not start

| Symptom                                             | What to do                                                                                                                                              |
| --------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Docker unavailable                                  | Open Docker Desktop or start the local Docker Engine, then retry `docker info`.                                                                         |
| Image missing / startup asks you to load an archive | Complete step 2: build from source or load your supplied archive.                                                                                       |
| Old bookmark does not load                          | Start Labcat, then use `status` to find its current URL.                                                                                                |
| Continue unavailable                                | Save the selected model and consent with **Save and test connections**, and resolve any reported connection error.                                      |
| ChatGPT sign-in cannot complete on port 1455        | Finish or close the other login process using that port, then follow the [callback recovery instructions](docs/deployment.md#chatgpt-browser-callback). |
| Mac/Linux says permission denied for the launcher   | Run `chmod +x labcat.sh` once, then launch again.                                                                                                       |
| History appears missing                             | Check the Docker context and Compose project name before creating another workspace or resetting anything.                                              |
| Other startup error                                 | Run `logs`; see [deployment troubleshooting](docs/deployment.md#troubleshooting).                                                                       |

For source updates, stop the app, rebuild with the same command in step 2, then
launch again. Back up your workspace before upgrades; image rollback alone does
not reverse database changes. To check build storage use `docker system df`.
`docker builder prune` removes unused build cache without deleting saved work;
future builds will need to download/rebuild more. Review old images separately
so you can retain the installed version and any rollback images you need.

### Research from the command line

After connecting a model in setup, run research without opening a window:

```bash
./labcat.sh cli research "Find promising oxide dielectric candidates for thin-film experiments" --style audit
```

Windows accepts the same arguments after `.\labcat.cmd cli`. Research starts or
reuses the local backend and its connected model, saved ranking profiles and
source settings. It returns a stateless report without adding a chat. Credentials
stay in the backend; a locked vault or expired login must be resolved in the app.
Use `--format json` to return structured output, or `--ranking-profile PROFILE_ID`
to choose a saved profile instead of inferring one. Status/configuration commands
remain available without an account. For example, `./labcat.sh cli --offline
status --format json` disables container networking; offline research cannot
meet the model connection requirement.

## Workspace and settings

Complete model setup, then start a standalone chat or enter a project and use the prompt beneath
its title. Each new project starts with one untitled chat; its first prompt gives
it a topic name automatically. Projects expand into their chats in the sidebar.
Clicking a project opens pinned
resources and report pairs; clicking a chat opens its latest Summary/Technical View and
its history. Counts show pinned reports and resources per chat and project.
Existing chats can be assigned to projects later. [Workspace guide](docs/projects.md)
Drag a General Chat onto a sidebar project to add it, or use the chat's Project
selector. The destination expands and updates automatically; history is retained.

Use **Search workspace** in the sidebar to find project names/descriptions, chat
titles, or text in saved messages and reports. Search matches a phrase without
regard to capitalization; it also recognizes equivalent Unicode forms such as
SiO2 and SiO₂. Results show matching excerpts and the chat's project. Select a
result to open it; message matches open the relevant conversation history.
Clear the search or press Escape to return to the independently scrollable
Projects and General Chats lists. Search runs locally, excludes Removed items,
and makes no model calls.

At the bottom of each prompt, **Infer from prompt** interprets the material class,
application and requested goals using the supported criteria catalog. This
interpretation can be imperfect; review the profile recorded with the result.
Choose a profile explicitly from the same popup to use it for that request.
See [request interpretation](docs/semantic-intake.md). **Connect model** opens provider and model selection; its
setup link opens Connections while keeping your draft. Ranking settings open
the same way. Each report retains its exact profile and selection rationale.

**Search Criterion** provides material-class/application presets, custom saved
ranking profiles, and grouped predefined attributes. Every importance value is
independently adjustable from 0–1 by slider or numeric entry; relative weights
are calculated automatically. The visualization distinguishes the active saved
ranking profile from edits. Select **New ranking profile**, give it a name,
choose preset or custom priorities, then **Save ranking profile**. Saved ranking
profiles appear in the selector and persist across restarts. **Use ranking profile**
makes a saved profile the workspace default. The prompt's profile selection
can override it without changing that default. Attributes outside the current adapter's coverage stay
explicitly unavailable. Class presets organize preferences; source coverage still
determines which material properties can be scored. Ranking controls have vertically
stacked previews: the active profile first, followed by unsaved edits. Property
categories are shown directly; newly selected attributes start at 0.5 importance.
Saved weights remain unchanged. The catalog includes polymers,
perovskites, ceramics, metals/alloys, MOFs, nanocrystals, composites and the other
requested classes as editable exploratory templates.

**Connections** owns model, compute and public API credentials. **Search Criterion**
selects public services and a per-source result limit. Credentialed APIs require
a successful connection check; changed, locked or failed credentials disable
their use. Keyless public services remain selectable. Add a verified Materials
Project connection alongside the selected public databases when you want to use its API.
New installations enable public reference search, including bounded searches for
missing attributes in available open-access article text. Eligible cited passages
can inform the preliminary candidate assessment. They remain separate from
validated numerical properties and do not silently fill measurement fields.
Saved source preferences remain respected. A failed source never causes prefilled results to appear.
[Source coverage and limits](docs/scientific-sources.md)

**Report Format** contains output checkboxes, verbosity, terminology and
TXT/JSON/PDF/Word previews. Adjust paper size, font, spacing, accent, table style
and page numbering for documents; adjust text width and JSON indentation for
text formats. Download a clearly labeled template preview without running
research. Ordinary reports and tracked project reports automatically use your
current Report Format for display and downloads. Pinned snapshots keep their
recorded format. Formatting does not change saved evidence, rankings or the
original report archive; legacy reports retain their original prose.
Terminology tiers are General overview, Research context and Specialist detail.
Each saved report has a single toolbar with Summary, Technical View and Sources
tabs. Check the box beside each tab to include that section in the download,
then choose a format and select Download at the right. Sources is included by
default and can also be downloaded on its own. The checkboxes only select
download contents; all tabs remain available to view. Downloads do not rerun
research.

Both **Summary** and **Technical View** lead with findings and conditional
recommendations, followed by the candidate shortlist and a discussion of the
evidence, alternatives and tradeoffs. Summary keeps this discussion compact;
Technical View expands the assessments, measurements and uncertainties. Candidate
names, reasons and comparisons come from the report's retained source records
and cited assessments. Missing evidence, tied ranks and reported concerns do not
become favorable findings. Search status, calculation details and processing
notes remain available in **Search and analysis details** at the bottom; downloads
include that complete appendix. Existing structured reports receive the improved
presentation without rerunning research, changing rankings or rewriting their
saved archive or pin snapshots. Legacy free-text reports remain literal.
Choosing a download format
does not change the readable on-screen report. PDF and Word exports retain formatted
tables and linked source titles; the Sources section lists the report's saved
references with access and provenance details. JSON downloads can include the
structured technical result and source records. The original saved text remains
available in the report archive.

For supported saved shortlist entries, **Technical View** can retrieve a public
crystal structure, display it in the bundled JSmol viewer and download a derived
CIF. Source identity, retrieval time and representation caveats remain visible.
Developer Settings can turn the viewer off while retaining structure downloads.
See [structure coverage and safeguards](docs/structures.md).

The Docker image preinstalls pinned Goose and a Codex account-metadata helper.
Compose runs the app, Goose worker and restricted network proxy separately using
that same image. Goose has no host folders or saved-workspace volume; explicit
desktop report exports go to Downloads.
ChatGPT browser sign-in uses the fixed localhost callback port 1455; the launcher
keeps the workspace available if that port is occupied and explains how to retry
sign-in. The worker itself has no published port. [Sign-in deployment](docs/deployment.md)
Goose receives a bounded set of application-defined research tools, with
general-purpose extensions disabled. A missing or rejected assessment
cannot start retrieval. Unclear questions receive guiding questions; harmful
requests are refused. These responses stay in chat without adding a report.
Each report retains the actual public-search, evidence and ranking
stages and its selected Ranking Profile. Model prose
cannot replace scientific records or reports. [Embedded agent](docs/goose.md)

The Technical View includes every positively weighted property from the saved
Ranking Profile, with unknown values, citations and score contributions. Rank
colors follow the absolute derived utility from red to green; they do not imply
confidence, safety or proven experimental performance. See the
[ranking algorithm](docs/ranking.md) and [research safeguards](docs/research-safeguards.md).

Keys are session-only by default. Optional persistence uses an encrypted vault
unlocked with an application passphrase, or an externally supplied encryption
key. The passphrase is not saved; after restart a passphrase vault remains locked
until unlocked. Closing setup permits reviewing existing work but does not
bypass the model requirement for new research.
Passwords for third-party accounts are never requested. [Security](docs/providers.md)

The optional **Developer Settings** tab is enabled only at server startup with
`LABCAT_EDITION=developer`. It controls bounded research stages, search budgets,
project-history use and a default saved model connection. The user edition
exposes neither the tab nor its settings API. Direct CLI research with
`--connections` uses that workspace’s saved research limits and source selections.
[Developer edition](docs/developer-mode.md)

Labcat's small decorative animations are optional. Developers can disable every
mascot with one source switch or a frontend build flag; see
[animation controls and sprite sheets](docs/labcat-animations.md).

## Develop without the Docker build

For code development on the host (not required for the Docker instructions above),
use Python 3.11+ and Node 22.12+ (CI uses Node 24):

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[web,aws,connections,exports,dev]'
npm ci --prefix frontend
npm run build --prefix frontend
labcat serve
```

Open <http://127.0.0.1:8000>. On Windows use `py -m venv .venv` and
`.venv\Scripts\Activate.ps1`. The base CLI requires no third-party runtime
packages. For research, choose `--server` to use an already configured backend
at its fixed same-machine address `127.0.0.1:8000`, or `--connections WORKSPACE_PATH`
to use an explicitly saved and accessible API/Bedrock connection from Python.
`--server` uses the app's saved settings and cannot be combined with `--config`
or `--connections`. ChatGPT research uses the Docker backend and its Goose worker.

```bash
python -m pre_commit run --all-files
python -m pytest
npm test --prefix frontend
npm run build --prefix frontend
ruff check .
python -m build
python scripts/check_distributions.py
python scripts/smoke_container.py --workspace
```

The scikit-package Level 4 pre-commit checks cover Python formatting and linting,
YAML/TOML validation, text formatting, merge conflicts, file-name case conflicts,
and large-file checks. Black is the Python formatter; Ruff adds application lint
rules. Upstream vendor files and reviewed binary assets have documented exceptions.
Run `python -m pre_commit install` once in your development clone to run the hooks
before each commit. After a hook edits files, review the changes and rerun it.
The application tests and distribution checks above run separately from the hooks.
See [scaffold and hook provenance](docs/scaffolding.md).

See the [three-page design note](docs/design-note.pdf), [evaluation](docs/evaluation.md),
[validation record](docs/validation.md), and [preserved earlier layout](docs/ui-layouts.md).
Hard evidence rules cannot be overridden through settings, prompts, models or
retrieved content. This is a single-user loopback service, not shared lab hosting.

Private requirements remain in ignored `LOCAL_BRIEF.md`; never force-add it.
Project code retains the template BSD-3-Clause license. The bundled scientific
subset has separate MIT attribution in `src/labcat/science/data/`.
