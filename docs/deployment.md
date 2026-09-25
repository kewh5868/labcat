# Local Docker deployment

The Docker build compiles the React interface and serves it through FastAPI.
Compose starts the workspace application, an isolated Goose worker and a
provider-network proxy. Only the application receives the persistent workspace
volume. The worker has no host folder, Docker socket or workspace mount.

## Build and launch from this checkout

Install and start a compatible Docker runtime with Compose, then run:

```sh
docker build -t labcat:0.1.0.dev0 .
./labcat.sh
```

On Windows, double-click `labcat.cmd` or run `./labcat.ps1` in PowerShell after
building the image. On macOS, `Start Labcat.command` is also available. Keep the
launchers beside `compose.yaml`. The launchers check Docker, start or reuse the
stable `labcat` Compose project, wait for health and open the assigned loopback
address in the default browser. They accept an optional private
`compose.local.yaml` for installation-specific settings.

Docker assigns a local port, which can change after recreation. Use
`./labcat.sh status` or `labcat.cmd status` to find it. Reopening reuses the
services; `./labcat.sh stop` or `labcat.cmd stop` stops only those services.
Closing the browser leaves the backend running. No host Python, Node or compiler
is required once the image has been built.

The optional [native desktop wrapper](../desktop/README.md) now displays the
same Docker-served workspace in the operating system webview. Build it for the
target host using its guide; native signing and per-host validation remain
release work. The install-ZIP builder and native/container artifact workflows
are planned additions. Windows and Linux host behavior requires testing on
those systems; an implementation or workflow definition alone does not establish
that validation passed.

## Connection setup and saved work

Complete model setup before starting research. Select a supported provider,
connect the account, consent to hosted context and choose **Save and test
connections**. Continue through optional compute/public-source settings and
finish setup. Connection checks do not invoke a paid model, and listing models
does not prove inference access. Data-source credentials and AWS are optional.
The application does not provision cloud resources or download model weights.

Research requires the verified model connection. Public retrieval supplies
scientific evidence; the model and user prompt cannot create measurements.
See [public-source coverage](public-sources.md) for source limits. If an endpoint
fails or evidence is missing, the result retains the gap.

Keys are session-only unless encrypted vault storage is explicitly configured.
Passphrase vaults restart locked. The workspace volume retains projects, chats,
reports, profiles and nonsecret preferences across normal stop/start operations.
Removing the volume deletes those records. Keep credentials, passphrases and
vault keys out of source, images, ordinary configuration and backups.

ChatGPT browser authorization uses the fixed callback port 1455. If another
service owns that port, the launcher keeps the workspace available with new
ChatGPT browser login disabled. It does not stop the other service. Finish the
conflicting flow, then explicitly relaunch with
`LABCAT_OAUTH_CALLBACK_PORT=1455` to restore browser sign-in. Existing saved
connections and other supported providers remain usable.

## Headless and manual use

Use `./labcat.sh start --no-open` or `labcat.cmd start -NoOpen` to start without
opening a browser. `./labcat.sh cli status --format json` runs the shared CLI in
a temporary container. Add `--offline` immediately after `cli` to disable its
network. For connected research through the running application:

```sh
./labcat.sh cli research "Find oxide dielectric candidates" --format json
```

The research command starts or reuses the full Compose application without
opening a window. It uses the saved model/source settings and reports to stdout;
it does not create a chat or export credentials. After restart, unlock a saved
vault or reconnect a session-only account first.

For direct service management:

```sh
docker compose --project-name labcat up --detach --wait --wait-timeout 60
docker compose --project-name labcat port labcat 8000
docker compose --project-name labcat stop
```

Open HTTP at the returned `127.0.0.1:PORT`. These launchers target a local Docker
engine and refuse remote Docker endpoints. Loopback and origin checks do not
provide shared-user authentication. Shared hosting needs separate identity and
operational controls.
