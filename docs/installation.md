# Install and run Labcat

The recommended path is to build the Docker image from this repository and open
Labcat in your browser. Docker runs the application locally; new research still
requires a connected model provider and access to public sources. The image does
not include a local AI model.

**First time?** Follow the [first-run walkthrough](first-run.md) for exact terminal
commands and a guided tour of setup, your first question and report downloads.

Already installed? Start Docker and skip to [everyday use](#everyday-use).

## 1. Prepare Docker

- **Mac or Windows:** install and start [Docker Desktop](https://docs.docker.com/desktop/).
  On Windows, select Linux containers.
- **Linux:** install [Docker Engine](https://docs.docker.com/engine/install/) and
  the [Compose plugin](https://docs.docker.com/compose/install/linux/), then start
  the Docker service.

Use a local Docker context. Wait for Docker to finish starting, then check these
commands in Terminal or PowerShell:

```text
docker info
docker compose version
```

Compose must support `up --wait --wait-timeout`. You also need Git for the clone
commands below and a browser. The Docker build provides Python, Node and the
agent runtime; you do not need to install them separately. Internet access is
needed for the initial build, provider sign-in and live research.

## 2. Get the source and build

Run these commands in the folder where you want to keep Labcat. They work in
Mac/Linux Terminal and Windows PowerShell:

```text
git clone https://github.com/kewh5868/labcat.git
cd labcat
docker build -t labcat:0.1.0.dev0 .
```

Use the exact image tag shown above: the supplied Compose configuration expects
it. The first build downloads dependencies and may take several minutes. Wait
for a successful build before launching. You only rebuild when updating the
application.

You can also download and extract the repository source, open a terminal in the
folder containing `Dockerfile` and `compose.yaml`, and run the same build command.
A source checkout does not require a supplied image archive. No Labcat image is
currently published to a container registry.

Docker builds for its local runtime architecture by default. Use `linux/arm64`
for Apple Silicon and other supported ARM hosts, or `linux/amd64` for Intel/AMD
hosts. Windows needs a runtime that supports the corresponding Linux containers;
Windows on ARM still needs target-host validation. See
[platform requirements and validation limits](deployment.md#supported-target).

## 3. Open Labcat

Keep using the source folder from step 2.

### Mac or Linux

```sh
./labcat.sh --browser
```

If the launcher reports permission denied, run `chmod +x labcat.sh` once and
retry.

### Windows PowerShell

```powershell
.\labcat.cmd -Browser
```

If your organization's PowerShell policy blocks the launcher, follow its
script-signing policy or use [direct Compose startup](#start-directly-with-compose).

The launcher starts the services, waits for readiness, prints the local URL and
opens your browser. Use the actual address it prints, such as
`http://127.0.0.1:PORT/`; the port is chosen automatically. If no window opens,
paste that URL into a browser on the same computer.

### Optional native window

The native desktop shell is a separate build or supplied bundle. Building the
Docker image does not install it. When a native shell is present in the
installation's `desktop-bin/` folder, `./labcat.sh` or `.\labcat.cmd` without the
browser flag opens it. Otherwise, those commands fall back to the browser.
Both interfaces use the same Docker workspace.

See the [native desktop guide](https://github.com/kewh5868/labcat/blob/main/desktop/README.md) for build instructions and
OS webview requirements. Docker remains required for the native application.

## 4. Complete first-time setup

1. **Model:** choose **Model provider**. For ChatGPT, select **Sign in with
   ChatGPT** and complete authorization in your browser. For an API provider,
   enter its API key and choose **Connect [provider]** or **Save API key**.
   ChatGPT account sign-in and OpenAI API billing are separate options.
2. Select an available model, enable the consent checkbox for sending research
   context to that provider, and choose **Save and test connections**. After a
   successful check, choose **Continue**. Unsaved model or consent changes must
   be saved first. Connection checks do not run model inference.
3. **Compute:** keep the default local workspace. [AWS setup](aws.md) is optional;
   local workspace processing still uses your selected provider for AI.
4. **Public sources:** keep the databases you want to search. A Materials Project
   API key is optional; enter and verify it on its database card if you have one.
5. **Ready:** review the selected model and choose **Finish setup**. Start a
   **New chat**, or create a project and enter a research question. Research may
   use your provider's allowance or incur charges.

Credentials are session-only by default. To retain supported credentials across
restarts, create or unlock the vault under **Advanced credential options** and
choose encrypted storage. A passphrase vault must be unlocked after a restart;
otherwise, sign in or enter your API key again. Chats, reports and settings
persist independently of credentials. See [connection setup and recovery](onboarding.md)
and the [workspace guide](projects.md).

## Everyday use

Start Docker first, then run the launcher from your installation folder.

| Action                                     | Mac / Linux                   | Windows PowerShell           |
| ------------------------------------------ | ----------------------------- | ---------------------------- |
| Open in a browser                          | `./labcat.sh --browser`       | `.\labcat.cmd -Browser`      |
| Open the available native shell or browser | `./labcat.sh`                 | `.\labcat.cmd`               |
| Start without opening a window             | `./labcat.sh start --no-open` | `.\labcat.cmd start -NoOpen` |
| Show status and current URL                | `./labcat.sh status`          | `.\labcat.cmd status`        |
| Stop, keeping saved work                   | `./labcat.sh stop`            | `.\labcat.cmd stop`          |
| Read recent logs                           | `./labcat.sh logs`            | `.\labcat.cmd logs`          |

Closing a window leaves the services running. To restart, stop and then launch
again; there is no `restart` launcher action. After a computer restart, start
Docker and launch Labcat again. Use `status` to find the current URL instead of
relying on an old bookmark.

### Saved work and updates

By default, projects, chats, reports and settings live in the Docker volume
`labcat_workspace-data`. The launchers use the stable Compose project `labcat`.
Keep the same Docker context and project name to reuse your workspace. Normal
stopping preserves this data. **Do not use `docker compose down --volumes`, prune
volumes or reset Docker Desktop to stop or update Labcat:** those actions can
delete saved work.

Before an upgrade, [back up your workspace](deployment.md#saved-projects-and-chat-history).
Stop Labcat, then update an unmodified source checkout and rebuild:

```text
git pull --ff-only
docker build -t labcat:0.1.0.dev0 .
```

Launch again using the commands above. Keep any installation-specific
`compose.local.yaml` beside the launchers; they load it automatically. Container
recreation can require signing in or unlocking the vault again. Image rollback
alone does not reverse database changes.

## Alternative installation routes

### Load a supplied image bundle

If you received an install ZIP, extract the entire bundle and keep its launchers
beside `compose.yaml`. Check its version and validation record: a local archive
may predate the current source. [Verify its checksum](deployment.md#checksums),
then load the archive matching your host architecture. For example, on Apple
Silicon:

```text
docker load --input labcat-0.1.0.dev0-linux-arm64.tar
```

Use the `linux-amd64.tar` archive on Intel/AMD computers, substituting your
bundle's actual filename. Build from source **or** load an image; there is no
need to do both. Then follow [Open Labcat](#3-open-labcat) and first-time setup.
Loading a supplied archive avoids the source build; provider connections and
live research still require network access. See the
[bundle delivery guide](deployment.md#primary-end-user-path-load-an-image-and-open-a-window).

### Start directly with Compose

After building or loading the image, run these commands from the folder
containing `compose.yaml`:

```text
docker compose --project-name labcat --file compose.yaml up --detach --wait --wait-timeout 60
docker compose --project-name labcat --file compose.yaml port labcat 8000
```

Open `http://` followed by the returned address. Stop with:

```text
docker compose --project-name labcat --file compose.yaml stop
```

These commands do not build the image or open a browser. If your installation
uses `compose.local.yaml`, add `--file compose.local.yaml` after
`--file compose.yaml` in each command. Direct Compose startup also does not
provide the launcher's fallback for a busy ChatGPT callback port; see
[ChatGPT callback recovery](deployment.md#chatgpt-browser-callback).

## If something does not start

Check that Docker is running, the image build or load succeeded, and you are
using the URL from `status`. Inspect `logs` for startup errors. If setup will
not continue, save the selected model and consent and resolve any reported
connection error. For callback conflicts, missing history and other startup
issues, follow [deployment troubleshooting](deployment.md#troubleshooting).
