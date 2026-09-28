# Installation requirements

Follow [Install & setup](first-run.md) for the commands and illustrated setup.
Both Desktop and Browser use Docker on the same computer.

## Docker and browser requirements

Install Git and a running local Docker engine with the Compose plugin. Compose
must support `up --wait --wait-timeout`. Use Linux containers on Windows.
Internet access is needed for builds, sign-in and live research. Browser mode
needs no host Python, Node or Rust.

## Desktop prerequisites

The source checkout does not include a prebuilt native app. Install **Node 24
with npm**, **Rust/Cargo 1.88 or newer** for the committed dependency lockfile,
and these OS prerequisites:

- **macOS:** Xcode Command Line Tools.
- **Windows:** Microsoft C++ Build Tools with a Windows SDK, and WebView2 Runtime.
- **Linux:** a C/C++ compiler, `pkg-config`, and WebKitGTK 4.1, GTK 3, libsoup 3
  and librsvg development packages.

Follow [Tauri's platform prerequisite guide](https://v2.tauri.app/start/prerequisites/)
for installation steps. Labcat checks basic tool availability; it does not
install system dependencies or validate every tool version. Choose Browser
if you prefer to avoid compiling a native app.

## Stop, reopen or troubleshoot

Closing a window leaves the backend running. Use these commands from your
`labcat` folder:

| Action                   | Mac / Linux          | Windows PowerShell    |
| ------------------------ | -------------------- | --------------------- |
| Open again               | `./labcat.sh`        | `.\labcat.cmd`        |
| Current status and URL   | `./labcat.sh status` | `.\labcat.cmd status` |
| Stop, keeping saved work | `./labcat.sh stop`   | `.\labcat.cmd stop`   |
| Startup logs             | `./labcat.sh logs`   | `.\labcat.cmd logs`   |

If startup fails, confirm Docker is running and the image build succeeded.
If a browser window does not open, use the local URL printed by `status`.
Reopen the terminal after installing missing tools. For updates, bundles or
persistent startup errors, consult the
[deployment notes](https://github.com/kewh5868/labcat/blob/main/docs/deployment.md).
