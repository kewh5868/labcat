#!/bin/sh
# Host launcher: Docker owns the service; the desktop shell or browser owns the UI.
set -eu

labcat_dir=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
labcat_action=start
labcat_open=yes
labcat_browser=no
labcat_cli_network=bridge
if [ "${1:-}" = cli ]; then
    labcat_action=cli
    shift
    if [ "${1:-}" = --offline ]; then
        labcat_cli_network=none
        shift
    fi
    if [ "$#" -eq 0 ]; then set -- status; fi
else
    for labcat_arg in "$@"; do
        case "$labcat_arg" in
            start|stop|status|logs) labcat_action=$labcat_arg ;;
            --no-open) labcat_open=no ;;
            --browser) labcat_browser=yes ;;
            -h|--help)
                echo 'Usage: ./labcat.sh [start|stop|status|logs] [--browser|--no-open]'
                echo '       ./labcat.sh cli [--offline] [application arguments, e.g. status --format json]'
                echo 'CLI research uses the running application account. Complete model setup first.'
                echo '--offline disables container networking; authenticated research requires network access.'
                exit 0 ;;
            *) echo "Unknown option: $labcat_arg" >&2; exit 2 ;;
        esac
    done
fi

# Finder launches with a smaller PATH than an interactive terminal.
PATH="$PATH:/usr/local/bin:/opt/homebrew/bin:/Applications/Docker.app/Contents/Resources/bin"
export PATH
fail() { echo "Labcat: $*" >&2; exit 1; }
command -v docker >/dev/null 2>&1 || fail 'Install Docker with Compose, then start Docker and try again.'
docker compose version >/dev/null 2>&1 || fail 'Docker Compose is required. Install/update Docker Desktop or the Compose plugin.'
docker info >/dev/null 2>&1 || fail 'Docker is not available. Start Docker Desktop (or your local Docker Engine) and try again.'

# A remote Docker daemon cannot provide a window at this machine's loopback URL.
if [ -n "${DOCKER_CONTEXT:-}" ] || [ -z "${DOCKER_HOST:-}" ]; then
    labcat_endpoint=$(docker context inspect --format '{{.Endpoints.docker.Host}}') || fail 'Cannot inspect the Docker context.'
else
    labcat_endpoint=$DOCKER_HOST
fi
case "$labcat_endpoint" in
    unix://*|npipe://*) ;;
    *) fail 'The desktop launcher requires a local Docker context. Select your local Docker Desktop/Engine context first.' ;;
esac

compose() {
    # Local deployment settings retain selected volumes and credential mounts
    # when the app is reopened. Keep this file beside the installed launcher.
    if [ -f "$labcat_dir/compose.local.yaml" ]; then
        set -- --file "$labcat_dir/compose.local.yaml" "$@"
    fi
    docker compose --project-name labcat --file "$labcat_dir/compose.yaml" "$@"
}

callback_notice() {
    echo 'Labcat: ChatGPT browser sign-in needs local port 1455. The app can still use other model connections.' >&2
    echo 'To enable it later, make port 1455 available, then run: LABCAT_OAUTH_CALLBACK_PORT=1455 ./labcat.sh start' >&2
}

start_service() {
    # Reopening an app already using a dynamic callback must not recreate it and
    # discard its in-memory credentials merely because the default is 1455.
    if [ -z "${LABCAT_OAUTH_CALLBACK_PORT:-}" ]; then
        labcat_existing_callback=$(compose port labcat 1456 2>/dev/null) || labcat_existing_callback=
        case "$labcat_existing_callback" in
            127.0.0.1:*)
                labcat_callback_number=${labcat_existing_callback#127.0.0.1:}
                case "$labcat_callback_number" in
                    ''|*[!0-9]*) ;;
                    *)
                        if [ "${#labcat_callback_number}" -le 5 ] && [ "$labcat_callback_number" -ge 1 ] && [ "$labcat_callback_number" -le 65535 ] && [ "$labcat_callback_number" -ne 1455 ]; then
                            LABCAT_OAUTH_CALLBACK_PORT=0
                            export LABCAT_OAUTH_CALLBACK_PORT
                        fi
                        ;;
                esac
                ;;
        esac
    fi
    if [ "${LABCAT_OAUTH_CALLBACK_PORT:-1455}" != 1455 ]; then callback_notice; fi
    if labcat_up_output=$(compose up --detach --wait --wait-timeout 60 2>&1); then
        printf '%s\n' "$labcat_up_output"
        return 0
    fi
    printf '%s\n' "$labcat_up_output" >&2
    [ "${LABCAT_OAUTH_CALLBACK_PORT:-1455}" = 1455 ] || return 1
    # Retry only this exact loopback callback collision, never image, health,
    # permission or unrelated network errors. Do not stop the port's owner.
    case "$labcat_up_output" in
        *'Bind for 127.0.0.1:1455 failed: port is already allocated'*|*'127.0.0.1:1455: bind: address already in use'*|*'127.0.0.1:1455: bind: Only one usage of each socket address'*) ;;
        *) return 1 ;;
    esac
    LABCAT_OAUTH_CALLBACK_PORT=0
    export LABCAT_OAUTH_CALLBACK_PORT
    echo 'Labcat: Port 1455 is already in use; retrying with a separate callback port.' >&2
    callback_notice
    compose up --detach --wait --wait-timeout 60
}

read_url() {
    labcat_binding=$(compose port labcat 8000) || fail 'Cannot find the UI port. Start Labcat first.'
    case "$labcat_binding" in
        127.0.0.1:*) labcat_port=${labcat_binding#127.0.0.1:} ;;
        *) fail 'Docker did not return a single local UI address. Check compose.yaml.' ;;
    esac
    case "$labcat_port" in
        ''|*[!0-9]*) fail 'Docker returned an invalid UI port.' ;;
    esac
    [ "${#labcat_port}" -le 5 ] && [ "$labcat_port" -ge 1 ] && [ "$labcat_port" -le 65535 ] || fail 'Docker returned an invalid UI port.'
    labcat_url="http://127.0.0.1:$labcat_port/"
    echo "Labcat UI: $labcat_url"
}

open_window() {
    case "$(uname -s)" in
        Darwin)
            labcat_native="$labcat_dir/desktop-bin/Labcat.app"
            if [ "$labcat_browser" = no ] && [ -d "$labcat_native" ]; then
                if open -n -a "$labcat_native" --args --url "$labcat_url"; then
                    echo 'Opened the standalone Labcat application.'
                    return
                fi
            fi
            echo 'Opening your default browser. A native install bundle provides the standalone window.'
            open "$labcat_url" || echo "Open $labcat_url in your browser." >&2
            ;;
        Linux)
            if [ -z "${DISPLAY:-}" ] && [ -z "${WAYLAND_DISPLAY:-}" ]; then
                echo 'No desktop display found. Open the UI URL on this machine, or use an SSH tunnel.'
                return
            fi
            labcat_native="$labcat_dir/desktop-bin/labcat-desktop"
            if [ "$labcat_browser" = no ] && [ -x "$labcat_native" ]; then
                nohup "$labcat_native" --url "$labcat_url" >/dev/null 2>&1 &
                echo 'Requested the standalone Labcat application. If none appears, open the UI URL above.'
                return
            fi
            if command -v xdg-open >/dev/null 2>&1; then
                echo 'Opening your default browser. A native install bundle provides the standalone window.'
                nohup xdg-open "$labcat_url" >/dev/null 2>&1 &
            else
                echo "Open $labcat_url in your browser."
            fi
            ;;
        *) echo "Open $labcat_url in your browser." ;;
    esac
}

case "$labcat_action" in
    start)
        echo 'Starting Labcat; waiting for the application to be ready...'
        if ! start_service; then
            fail 'Startup failed. Load the supplied image archive with docker load --input <archive.tar>, or inspect ./labcat.sh logs. No UI window was opened.'
        fi
        read_url
        echo 'Closing the window leaves the service running. Stop it with: ./labcat.sh stop'
        if [ "$labcat_open" = yes ]; then open_window; fi
        ;;
    stop) compose stop ;;
    status)
        compose ps
        labcat_running=$(compose ps --status running --quiet labcat)
        if [ -n "$labcat_running" ]; then read_url; else echo 'Labcat is stopped.'; fi
        ;;
    logs) compose logs --tail 100 labcat ;;
    cli)
        if [ "$labcat_cli_network" != none ] && [ "${1:-}" = research ]; then
            # Reuse the server's live credential session without exporting secrets.
            # Startup diagnostics stay off stdout so JSON output can be redirected.
            start_service >&2 || fail 'Start Labcat and complete model setup before CLI research.'
            shift
            compose exec --no-TTY labcat labcat research --server "$@"
            exit $?
        fi
        docker run --rm --pull never --network "$labcat_cli_network" \
            --read-only --cap-drop ALL --security-opt no-new-privileges \
            --init --tmpfs /tmp:size=64m,mode=1777 \
            --tmpfs /var/lib/labcat:size=64m,uid=10001,gid=10001,mode=0700 \
            labcat:0.1.0.dev0 "$@"
        ;;
esac
