# Installation requirements

Follow [Install & setup](first-run.md) for the commands and illustrated setup.
All three launch modes run the same Labcat backend in Docker on your computer.
The choice controls the window used to display it.

## Choose a launch mode

| Option                                             | What opens                                            | Installation requirements                                                           |
| -------------------------------------------------- | ----------------------------------------------------- | ----------------------------------------------------------------------------------- |
| **1. Native Labcat app (Docker backend, default)** | The native Labcat app, connected to Docker            | The automatically downloaded native shell and OS webview; no Node, Rust or compiler |
| **2. Browser**                                     | The Docker application in your normal default browser | A current web browser                                                               |
| **3. Build desktop application from source**       | The same native Labcat app, compiled locally          | Node/npm, Rust/Cargo, OS build tools and the webview                                |

Press **Enter** for option 1 on first launch. The launcher remembers the
successful choice, including choices saved by an earlier version. Use
`./labcat.sh --choose` on Mac/Linux or `.\labcat.cmd -Choose` on Windows to
choose again. You can also select directly:

| Mode                        | Mac / Linux                   | Windows PowerShell           |
| --------------------------- | ----------------------------- | ---------------------------- |
| Prebuilt Docker application | `./labcat.sh --docker`        | `.\labcat.cmd -Docker`       |
| Browser                     | `./labcat.sh --browser`       | `.\labcat.cmd -Browser`      |
| Source-built native app     | `./labcat.sh --desktop`       | `.\labcat.cmd -Desktop`      |
| Containers only, no window  | `./labcat.sh start --no-open` | `.\labcat.cmd start -NoOpen` |

**All modes use the same Docker image, workspace and research services.**
Options 1 and 3 use the same Tauri native shell and OS webview; option 1 installs
an already compiled shell, while option 3 builds it on your machine when needed.
Docker and Browser modes need no host Python, Node, npm, Rust or Cargo.

### Prebuilt native availability

On supported platforms, the launcher automatically downloads the native shell
from an official Labcat release using the version and checksum pinned in this
checkout. It verifies the artifact before installation and reuses an existing
matching installation. You do not need to find a bundle or install build tools.
A supplied matching `desktop-bin/` bundle can also be used.

Prebuilt shell targets are **macOS Apple Silicon**, **macOS Intel**,
**Windows x64** and **Linux x64**. **Linux ARM64** uses Browser mode or an
explicit native source build. See [Labcat releases](https://github.com/kewh5868/labcat/releases)
for released artifacts; native runtime requirements still apply.

The automatic Mac/Linux download uses `curl`, `tar`, and either `shasum` or
`sha256sum`; these are normally present on macOS and may need installation on
minimal Linux systems. Windows uses its PowerShell/.NET download, archive and
hash tools. These utilities do not compile the native app.

If the required download is unavailable or fails verification, the launcher
reports the problem. It does not silently install compilers or build from
source. Choose **Browser (2)** to use the Docker image immediately, or explicitly
select **Build desktop application from source (3)** after installing its
prerequisites.

## Requirements for every mode

- **Supported host:** a Mac, Windows PC or Linux computer that meets its Docker
  runtime's OS, virtualization, memory and storage requirements. Use a Linux
  image matching your CPU: `arm64` for Apple Silicon, `amd64` for Intel/AMD.
  Check [Docker's Mac requirements](https://docs.docker.com/desktop/setup/install/mac-install/),
  [Windows requirements](https://docs.docker.com/desktop/setup/install/windows-install/)
  or [Linux Engine installation](https://docs.docker.com/engine/install/).
- **Docker engine, CLI and Compose:** Docker Desktop includes all three. Linux
  Engine installations also need the
  [Compose plugin](https://docs.docker.com/compose/install/linux/).
  Compose must support `up --wait --wait-timeout`; check with
  `docker compose up --help`. Docker must be running, use a local context and
  be able to start Linux containers. Windows-container mode is not supported.
- **Git** for the documented source-clone installation, plus a terminal:
  Terminal on Mac/Linux or Windows PowerShell with the supplied `.cmd` launcher.
  A supplied image/install bundle does not need Git.
- **Windows script policy:** the launcher and native app honor your PowerShell
  execution policy. Restricted or managed systems may require an approved or
  signed script before launch; follow your site's policy. The
  [direct Docker Compose browser route](https://github.com/kewh5868/labcat/blob/main/docs/deployment.md#direct-docker-compose-route)
  is an alternative that does not run the PowerShell launcher.
- **Internet access** for image builds, provider sign-in and public-source
  research. Docker must be able to download build dependencies. Research needs
  a supported model account with agent/tool access and available allowance;
  see [model setup](first-run.md#4-connect-your-model).
- **A current web browser** for provider sign-in and Browser mode. A graphical
  desktop session is needed to open windows; headless servers can use
  `--no-open` or `-NoOpen` and the printed local URL.
- **Local ports and writable storage:** the launcher selects an available
  loopback port for the workspace. ChatGPT browser sign-in also needs local
  port **1455**. Keep space for the image, build cache and saved workspace;
  native source builds additionally keep Node and Rust build dependencies.
  Labcat does not install local model weights. A fixed minimum disk/RAM size
  for Labcat has not been established; follow the Docker requirements and
  allow headroom for your saved research.

Check the core tools before building:

```text
git --version
docker info
docker compose version
```

## Desktop prerequisites

**Only option 3 needs the build tools.** Both native options need their OS
webview runtime. The Docker build creates the backend image; building the
separate native shell from source requires host compilers. The default uses a
prebuilt shell instead.

For a source installation, install **Node 24 with npm**, **Rust and Cargo 1.88
or newer**, and the matching platform prerequisites below. Node/npm are used
for the native build tooling; Rust compiles the shell. Their checks are separate
from the Docker image build.

| Platform | Native source build requirements                                                                                | Native runtime                                             |
| -------- | --------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------- |
| macOS    | Xcode Command Line Tools, including a selected developer directory and the code-signing tools                   | System WKWebView                                           |
| Windows  | Microsoft C++ Build Tools with **Desktop development with C++**, a Windows SDK, and the Rust **MSVC** toolchain | Microsoft Edge WebView2 Runtime                            |
| Linux    | C/C++ compiler, `pkg-config`, and development packages for WebKitGTK 4.1, GTK 3, libsoup 3 and librsvg          | Compatible WebKitGTK/GTK libraries and a graphical session |

Use [Tauri's platform prerequisite instructions](https://v2.tauri.app/start/prerequisites/)
for installation and distribution-specific packages. On macOS, install the
command-line tools with `xcode-select --install`. Reopen your terminal after
installing tools so they are on its `PATH`. Check versions with:

```text
node --version
npm --version
rustc --version
cargo --version
```

When option 3 needs a source build, Labcat lists the detected tools and version
requirements, marks missing or incompatible prerequisites, and stops before
building if any check fails. It does not install system dependencies for you.
Correct the listed items and retry `--desktop` / `-Desktop`, choose the prebuilt
option when a matching bundle is available, or use Browser immediately. Passing these checks establishes
build prerequisites; it does not guarantee a successful native build.

To check without building or installing anything, run from the source folder:

| Mac / Linux                                            | Windows PowerShell                                                                  |
| ------------------------------------------------------ | ----------------------------------------------------------------------------------- |
| `sh scripts/install_desktop.sh --build-source --check` | `powershell -NoProfile -File .\scripts\install_desktop.ps1 -BuildSource -CheckOnly` |

A matching supplied native bundle skips source compilation and therefore does
not need Node, npm or Rust. It still needs Docker and the platform webview.
Native installation is per user, without administrator elevation:
`~/Applications/Labcat.app` on macOS, `%LOCALAPPDATA%\Programs\Labcat` on Windows,
or the user's local application-data directory on Linux. Ordinary launches
reuse the installed shell. See the
[native shell guide](https://github.com/kewh5868/labcat/blob/main/desktop/README.md)
for builds, updates and distribution details.

## Stop, reopen or troubleshoot

Closing the window leaves Docker and the Labcat containers running. To reopen
Labcat after closing it or restarting your computer:

1. Start Docker Desktop, or your Linux Docker engine, and wait until it is ready.
2. For either native option, open **Labcat** from `~/Applications` on Mac, the
   Start menu on Windows, or the application menu on Linux. It starts or reuses
   the Docker services. Browser users should run the launcher from the original
   `labcat` folder instead of relying on an old browser bookmark.
3. Alternatively, use the mode-specific command below from the `labcat` folder.

| What to reopen                         | Mac / Linux             | Windows PowerShell      |
| -------------------------------------- | ----------------------- | ----------------------- |
| Prebuilt native app (option 1)         | `./labcat.sh --docker`  | `.\labcat.cmd -Docker`  |
| Browser (option 2)                     | `./labcat.sh --browser` | `.\labcat.cmd -Browser` |
| Source-installed native app (option 3) | `./labcat.sh --desktop` | `.\labcat.cmd -Desktop` |
| Remembered mode                        | `./labcat.sh`           | `.\labcat.cmd`          |
| Choose a different mode                | `./labcat.sh --choose`  | `.\labcat.cmd -Choose`  |

The launcher starts or reuses the existing containers and opens their current
local address. **Do not rebuild the image or native app for each launch.**
Option 3 reuses its installed shell on subsequent launches. Rebuild only after
updating application code or when the new version's instructions require it.
Changing launch modes keeps the same workspace and saved research.

| Action                   | Mac / Linux          | Windows PowerShell    |
| ------------------------ | -------------------- | --------------------- |
| Current status and URL   | `./labcat.sh status` | `.\labcat.cmd status` |
| Stop, keeping saved work | `./labcat.sh stop`   | `.\labcat.cmd stop`   |
| Startup logs             | `./labcat.sh logs`   | `.\labcat.cmd logs`   |

To restart the backend, run **stop**, then your normal open command. If Docker
itself is stopped, start it before reopening Labcat. A backend restart ends
session-only sign-ins; reconnect your provider or unlock supported saved vault
credentials afterward. Closing only the window does not end that server session.

You can see the `labcat` Compose application in Docker Desktop. Use the supplied
launcher or native app icon to reopen it: research needs the app, worker and
network-proxy services, so starting just the app container is insufficient.
If a window cannot open, use the current local URL printed by `status` in your
browser. Saved work stays in the Docker volume when stopped; removing volumes
deletes it. Do not use `docker compose down --volumes` as a routine shutdown.

If startup fails, confirm Docker is running and the image build succeeded.
Keep the original installation folder for updates and launcher commands.
For updates, supplied bundles or persistent startup errors, consult the
[deployment notes](https://github.com/kewh5868/labcat/blob/main/docs/deployment.md).
