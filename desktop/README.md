# Native desktop shell

This Tauri v2 application displays the Docker-served React interface in the
operating system's webview. Docker remains the backend runtime. The default
launcher option installs a prebuilt native shell; the source-build option
compiles this same shell locally. Browser and CLI modes use the same backend.

The application is named Labcat. Native bundles use `Labcat.app` on macOS,
`labcat-desktop` as the executable name, and `org.labcat.desktop` as the
application identifier.

The native shell has version `0.1.0`; the research application reports its own
version (`0.1.0.dev0` in this prototype). The shared backend supports bounded
public-source materials screening and deterministic ranking through a required
connected model planner.
See [source coverage](../docs/scientific-sources.md) for its scientific limits.

## Run

Build the Docker image from the repository, or load a verified supplied image
archive, then start Docker. From the repository or install-bundle folder, run
`./labcat.sh` on Mac/Linux or `.\labcat.cmd` in Windows PowerShell. The chooser
offers **Native Labcat app with Docker (1, default Enter)**, **Browser (2)** and
**Build desktop application from source (3)**. All use the same Docker image.
Options 1 and 3 open this same native application.

Option 1 installs a matching prebuilt shell without host Node, Rust or compiler
tools. The launcher downloads a native shell from the official release using
the version and checksum pinned in the checkout, verifies it, and installs it
for your user. A supplied matching `desktop-bin/` bundle is also supported.
Prebuilt targets are macOS Apple Silicon/Intel, Windows x64 and Linux x64;
Linux ARM64 uses Browser or an explicit source build. If the matching download
is unavailable or fails verification, the launcher reports the problem and
suggests Browser or an explicit source build; it does not silently compile or
change modes.

To build from source, choose **3**, or run `./labcat.sh --desktop` /
`.\labcat.cmd -Desktop`. The launcher remembers successful selections, including
existing preferences; `--choose` / `-Choose` opens the chooser again.
`--docker` / `-Docker` selects the prebuilt native route, and `--browser` /
`-Browser` opens a browser. The source installation checks and reports all
prerequisites before compiling. Docker and Browser modes do not need build tools.

Desktop setup installs for the current user: `~/Applications/Labcat.app` on macOS,
`%LOCALAPPDATA%\Programs\Labcat\Labcat.exe` with a Start menu shortcut on Windows,
or `${XDG_DATA_HOME:-$HOME/.local/share}/labcat/desktop` with an application menu
entry on Linux. No administrator elevation or system dependency installation is
performed. Keep the original folder for updates and launcher commands. After
updating the native source, run `sh scripts/install_desktop.sh --build-source`
or `powershell -NoProfile -File .\scripts\install_desktop.ps1 -BuildSource`
from that folder to rebuild the shell and refresh its launcher configuration.
For supplied prebuilt updates, use the matching release/bundle instructions.
Ordinary launches reuse the installed app; rebuilding Docker alone does not
update it.

To reopen either native installation, start Docker and open **Labcat** from
`~/Applications` on macOS, the Windows Start menu or the Linux application menu.
From the installation folder, `./labcat.sh --docker` / `.\labcat.cmd -Docker`
reopens the default app, and `./labcat.sh --desktop` / `.\labcat.cmd -Desktop`
reuses the source-installed app without recompiling it. `./labcat.sh` /
`.\labcat.cmd` uses the saved mode. Browser users reopen with `--browser` /
`-Browser`; the launcher's current URL is more reliable than a saved bookmark.

Opening the installed native application starts or reuses the local
backend using its installed host launcher. A loading view appears immediately;
startup, status verification, and UI loading share a bounded deadline. Errors
remain visible in the native window. Closing the window leaves Docker running.
Stop with `./labcat.sh stop` or `.\labcat.cmd stop`; saved work is preserved.
Restart by opening the app again. If Docker itself has stopped, start its engine
first. See [all mode and lifecycle commands](../docs/installation.md#stop-reopen-or-troubleshoot).

To attach to an already running backend without starting Docker resources:

```text
labcat-desktop --url http://127.0.0.1:PORT/
```

Only the literal `127.0.0.1` host, HTTP, an explicit numeric port, and a root URL
are accepted. The shell verifies the health and application-status endpoints
before opening the page. It never follows redirects during these checks.

On macOS the executable is inside
`Labcat.app/Contents/MacOS/labcat-desktop`. On Windows use the
installed `labcat-desktop.exe`; keep its bundled resources with it. Linux
distribution targets are AppImage and Debian packages, in addition to the build
binary. A bare binary without its resources is not a complete installation.
Portable host bundles may rename the Windows binary to `Labcat.exe`.
When the normal Tauri resource directory has no launcher, the shell checks only
the fixed `launcher/` folder alongside its executable. It never searches the
current working directory for executable scripts.

For macOS GUI testing, open the app bundle through LaunchServices, for example
`open -n -a "/absolute/path/Labcat.app" --args --url http://127.0.0.1:PORT/`.
Use a desktop-capable execution context. A direct executable launch inside a
restricted command sandbox can abort in macOS application registration before
the webview starts; it is not a supported GUI test environment.

## Window zoom

Use **Command +** (or **Command =**) to enlarge the interface on macOS,
**Command −** to reduce it, and **Command 0** to return to actual size.
Windows and Linux use **Ctrl** instead of Command. The native **View** menu
provides the same actions. Zoom ranges from 50% to 200%, scales text and controls
together, and belongs to the focused window for that session. Closing and
reopening the application returns to 100%. It does not change report downloads
or saved research. The shortcuts also work while an embedded structure viewer
has keyboard focus.

Zoom is handled in the native shell, without granting the web interface native
API access. Ordinary browser use retains the browser's own zoom controls.

## Build

Use Rust/Cargo 1.88 or newer, Node 24 with npm, and the operating-system build
prerequisites from
[Tauri's official guide](https://v2.tauri.app/start/prerequisites/). macOS uses
the system WebKit webview. Windows uses the WebView2 runtime; the NSIS installer
can offer its bootstrapper if needed. Linux requires the WebKitGTK runtime.
The first-run source installer reports Node/npm and Rust/Cargo availability
and versions, plus the platform build prerequisites: Xcode Command Line Tools on
macOS; Visual Studio C++ Build Tools, a Windows SDK, an MSVC Rust toolchain and
WebView2 on Windows; or a compiler, `pkg-config` and WebKitGTK 4.1/GTK 3/libsoup 3/
librsvg development packages on Linux. Missing or incompatible prerequisites
stop the source installation before compiling. Install them yourself, then
retry. The Docker application and Browser choices need only the common
[installation requirements](../docs/installation.md#requirements-for-every-mode).

To inspect the prerequisite report without installing, run
`sh scripts/install_desktop.sh --build-source --check` from the repository root on Mac/Linux,
or `powershell -NoProfile -File .\scripts\install_desktop.ps1 -BuildSource -CheckOnly` on Windows.
A supplied native binary skips build-tool checks; required webview runtime
checks still apply. Passing prerequisites does not guarantee build success.

The automatic source build uses the committed npm and Cargo lockfiles. It builds
a macOS app bundle or the Windows/Linux native binary and then installs fixed
launcher resources beside it. It does not install a local AI model. Workspace
data and the credential vault remain in Docker; native installation carries the
shell and launcher configuration.

From `desktop/`:

```sh
npm ci
cargo fmt --check
cargo test --locked
npm run build -- --bundles app -- --locked
```

`app` is the macOS target. Use `nsis` on Windows and `deb,appimage` on Linux.
Tauri passes arguments after the final `--` to Cargo; this is how the build honors
`Cargo.lock`. `package-lock.json` pins the native build CLI. The configured icon
assets are generated from the approved `ui/labcat-mark.png`; `npm run icon` regenerates them and may
also produce unused mobile variants that should not be committed.

For the repository-local Rust installation used during development, point
`CARGO_HOME` to `.local/native-tools/cargo`, `RUSTUP_HOME` to
`.local/native-tools/rustup`, and prepend the cargo `bin` directory to the
command's `PATH`. These locations are under the repository root. No shell-profile
changes or global Rust installation are required.

macOS output is `desktop/target/release/bundle/macos/Labcat.app` for an
untargeted native build. Explicit `--target` builds add the target triple beneath
`desktop/target`. The native CI matrix builds macOS ARM64/Intel, Windows x64, and
Linux x64 artifacts. A workflow definition is not evidence those platforms have
passed; see the repository's validation record for actual results. Releases are
currently development artifacts without platform signing or notarization.
Linux packages build on Ubuntu 22.04 as a compatibility baseline; other Linux
distributions still need their own installation checks.

## Native boundary

The remote localhost page receives no Tauri API or IPC permissions. There are no
shell, filesystem, browser-opener, or other native plugins and no custom invoke
commands. The only process launch is the fixed bundled launcher during startup,
with fixed arguments and no user-provided command text. Root `labcat.sh`,
`labcat.ps1`, and `compose.yaml` are copied into `launcher/` by Tauri's explicit
resource mapping; no private notes or credentials are bundled.

Navigation is restricted to the selected loopback origin. Downloads are limited
to that backend's saved report exports, complete chat PDFs, previews and
report-scoped structure endpoints. Chat PDFs use a fresh `.pdf` filename and
structure files use a fresh `.cif` filename in the OS Downloads folder.
Approved public-reference
links open in the default browser; other external destinations are rejected.
Same-origin popups use an unprivileged native view. Loading/error content is embedded
and diagnostic text is inserted as text, not interpreted as markup. The
application does not stop the backend on window close.

These controls limit the native bridge; they do not establish scientific
provenance or prevent all browser/network risks. The backend's public-source and
evidence policies remain separately enforced work.
