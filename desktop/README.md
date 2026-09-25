# Native desktop shell

This Tauri v2 application displays the Docker-served React interface in the
operating system's webview. It does not require Chrome or launch a browser app
window. Docker remains the backend runtime; the CLI and ordinary browser modes
remain separate host-launcher options.

The application is named Labcat. Native bundles use `Labcat.app` on macOS,
`labcat-desktop` as the executable name, and `org.labcat.desktop` as the
application identifier.

The native shell has version `0.1.0`; the research application reports its own
version (`0.1.0.dev0` in this prototype). The shared backend supports bounded
public-source materials screening and deterministic ranking through a required
connected model planner.
See [source coverage](../docs/scientific-sources.md) for its scientific limits.

## Run

Install/start Docker and load the provided image archive before opening the
native application. Launching with no arguments starts or reuses the local
backend using the bundled host launcher. A loading view appears immediately;
startup, status verification, and UI loading share a bounded deadline. Errors
remain visible in the native window. Closing the window leaves Docker running.

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

Use a Rust toolchain, Node 24, and the operating-system build prerequisites from
[Tauri's official guide](https://v2.tauri.app/start/prerequisites/). macOS uses
the system WebKit webview. Windows uses the WebView2 runtime; the NSIS installer
can offer its bootstrapper if needed. Linux requires the WebKitGTK runtime.
Neither a separate Chrome installation nor a Chrome user profile is needed.

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
to that backend's saved report exports, previews and report-scoped structure
endpoints. Structure files use a fresh `.cif` filename in the OS Downloads folder.
Approved public-reference
links open in the default browser; other external destinations are rejected.
Same-origin popups use an unprivileged native view. Loading/error content is embedded
and diagnostic text is inserted as text, not interpreted as markup. The
application does not stop the backend on window close.

These controls limit the native bridge; they do not establish scientific
provenance or prevent all browser/network risks. The backend's public-source and
evidence policies remain separately enforced work.
