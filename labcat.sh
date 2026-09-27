#!/bin/sh
# Host launcher: Docker owns the service; the desktop shell or browser owns the UI.
set -eu

labcat_dir=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
labcat_action=start
labcat_open=yes
labcat_mode=
labcat_choose=no
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
            --browser) labcat_mode=browser ;;
            --desktop) labcat_mode=desktop ;;
            --choose) labcat_choose=yes ;;
            -h|--help)
                echo 'Usage: ./labcat.sh [start|stop|status|logs] [--desktop|--browser|--choose|--no-open]'
                echo '       ./labcat.sh cli [--offline] [application arguments, e.g. status --format json]'
                echo 'First interactive start offers the desktop app (default) or browser and remembers your choice.'
                echo '--desktop installs the native app if needed; --browser opens the browser; --choose asks again.'
                echo '--no-open starts only the backend, without choosing or installing a desktop app.'
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

labcat_project_dir=
if [ -e "$labcat_dir/.labcat-project-directory" ] || [ -L "$labcat_dir/.labcat-project-directory" ]; then
    [ -f "$labcat_dir/.labcat-project-directory" ] && [ ! -L "$labcat_dir/.labcat-project-directory" ] || fail 'The installed deployment directory setting must be a regular file.'
    IFS= read -r labcat_project_dir < "$labcat_dir/.labcat-project-directory" || fail 'The installed deployment directory setting is invalid.'
    [ "$(wc -l < "$labcat_dir/.labcat-project-directory" | tr -d ' ')" = 1 ] || fail 'The installed deployment directory setting is invalid.'
    [ "$(cat "$labcat_dir/.labcat-project-directory")" = "$labcat_project_dir" ] || fail 'The installed deployment directory setting is invalid.'
    case "$labcat_project_dir" in /*) ;; *) fail 'The installed deployment directory must be absolute.' ;; esac
    [ -d "$labcat_project_dir" ] || fail 'The original deployment directory was moved. Reinstall the desktop app from its new location to preserve your local settings.'
fi

choose_mode() {
    labcat_mode_file="$labcat_dir/.labcat-launch-mode"
    if [ -e "$labcat_mode_file" ] || [ -L "$labcat_mode_file" ]; then
        [ -f "$labcat_mode_file" ] && [ ! -L "$labcat_mode_file" ] || fail 'The launch preference must be a regular file, not a directory or symbolic link.'
    fi
    if [ "$labcat_choose" = no ] && [ -z "$labcat_mode" ] && [ -f "$labcat_mode_file" ] && [ ! -L "$labcat_mode_file" ]; then
        labcat_saved_mode=$(cat "$labcat_mode_file")
        case "$labcat_saved_mode" in desktop|browser) labcat_mode=$labcat_saved_mode ;; esac
    fi
    if [ "$labcat_choose" = yes ] || [ -z "$labcat_mode" ]; then
        [ -t 0 ] || fail 'Choose how to open Labcat: run ./labcat.sh --desktop or ./labcat.sh --browser (or --no-open for only the backend).'
        printf '%s\n' 'How would you like to use Labcat?' '  1) Install/open the desktop app (default)' '  2) Open in your browser'
        printf 'Choose [1/2, Enter for desktop]: '
        IFS= read -r labcat_answer || fail 'No launch choice was supplied.'
        case "$labcat_answer" in ''|1) labcat_mode=desktop ;; 2) labcat_mode=browser ;; *) fail 'Choose 1 for desktop or 2 for browser, or pass --desktop/--browser.' ;; esac
    fi
}

save_mode() {
    # Literal data only; never source a settings file as executable shell code.
    if [ -L "$labcat_dir/.labcat-launch-mode" ] || [ -d "$labcat_dir/.labcat-launch-mode" ]; then
        fail 'The launch preference must be a regular file.'
    fi
    labcat_mode_tmp=$(mktemp "$labcat_dir/.labcat-launch-mode.XXXXXX") || fail 'Cannot save the launch preference in this installation.'
    printf '%s\n' "$labcat_mode" > "$labcat_mode_tmp"
    chmod 600 "$labcat_mode_tmp"
    mv -f "$labcat_mode_tmp" "$labcat_dir/.labcat-launch-mode"
}

prepare_desktop() {
    if [ -n "${LABCAT_DESKTOP_INSTALL_DIR:-}" ]; then
        case "$LABCAT_DESKTOP_INSTALL_DIR" in /*) ;; *) fail 'LABCAT_DESKTOP_INSTALL_DIR must be absolute.' ;; esac
    fi
    case "$(uname -s)" in
        Darwin) labcat_native="${LABCAT_DESKTOP_INSTALL_DIR:-$HOME/Applications}/Labcat.app" ;;
        Linux)
            [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ] || fail 'No desktop display was found. Use --browser from a graphical session or --no-open for a headless backend.'
            labcat_native="${LABCAT_DESKTOP_INSTALL_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/labcat}/desktop/labcat-desktop" ;;
        *) fail 'This desktop installer supports macOS and Linux. Use --browser or --no-open on this platform.' ;;
    esac
    if [ "$(uname -s)" = Darwin ]; then
        labcat_native_executable="$labcat_native/Contents/MacOS/labcat-desktop"
        labcat_installed_root="$labcat_native/Contents/Resources"
        labcat_installed_launcher="$labcat_native/Contents/Resources/launcher"
    else
        labcat_native_executable=$labcat_native
        labcat_installed_root=${labcat_native%/*}
        labcat_installed_launcher="$labcat_installed_root/launcher"
    fi
    labcat_reinstall=no
    [ -x "$labcat_native_executable" ] || labcat_reinstall=yes
    [ -f "$labcat_installed_root/.labcat-install-source" ] && [ ! -L "$labcat_installed_root/.labcat-install-source" ] && [ "$(cat "$labcat_installed_root/.labcat-install-source")" = "$labcat_dir" ] || labcat_reinstall=yes
    for labcat_resource in labcat.sh compose.yaml; do
        cmp -s "$labcat_dir/$labcat_resource" "$labcat_installed_launcher/$labcat_resource" || labcat_reinstall=yes
    done
    if [ -f "$labcat_dir/compose.local.yaml" ]; then
        cmp -s "$labcat_dir/compose.local.yaml" "$labcat_installed_launcher/compose.local.yaml" || labcat_reinstall=yes
    elif [ -e "$labcat_installed_launcher/compose.local.yaml" ]; then
        labcat_reinstall=yes
    fi
    labcat_expected_project=$labcat_project_dir
    if [ -z "$labcat_expected_project" ] && [ -f "$labcat_dir/compose.local.yaml" ]; then
        labcat_expected_project=$labcat_dir
    fi
    if [ -n "$labcat_expected_project" ]; then
        [ -f "$labcat_installed_launcher/.labcat-project-directory" ] && [ ! -L "$labcat_installed_launcher/.labcat-project-directory" ] && [ "$(cat "$labcat_installed_launcher/.labcat-project-directory")" = "$labcat_expected_project" ] || labcat_reinstall=yes
    elif [ -e "$labcat_installed_launcher/.labcat-project-directory" ]; then
        labcat_reinstall=yes
    fi
    if [ "$labcat_reinstall" = yes ]; then
        [ -f "$labcat_dir/scripts/install_desktop.sh" ] || fail 'The desktop installer is missing. Use a complete Labcat checkout/install bundle, or choose --browser.'
        sh "$labcat_dir/scripts/install_desktop.sh" || fail 'Desktop installation failed. Your previous application is unchanged. Resolve the reported prerequisites or explicitly use --browser.'
        [ -x "$labcat_native_executable" ] || fail 'Desktop installation did not create the native application.'
    fi
}

compose() {
    # Local deployment settings retain selected volumes and credential mounts
    # when the app is reopened. Keep this file beside the installed launcher.
    if [ -f "$labcat_dir/compose.local.yaml" ]; then
        set -- --file "$labcat_dir/compose.local.yaml" "$@"
    fi
    if [ -n "$labcat_project_dir" ]; then
        set -- --project-directory "$labcat_project_dir" "$@"
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
    if [ "$labcat_mode" = desktop ]; then
        case "$(uname -s)" in
            Darwin) open -n -a "$labcat_native" --args --url "$labcat_url" || fail 'The desktop app could not open. Reinstall it with sh scripts/install_desktop.sh, or choose --browser.' ;;
            Linux) nohup "$labcat_native" --url "$labcat_url" >/dev/null 2>&1 & ;;
        esac
        echo 'Opened the standalone Labcat application.'
        return
    fi
    case "$(uname -s)" in
        Darwin) open "$labcat_url" || fail "Open $labcat_url in your browser." ;;
        Linux)
            if [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ] && command -v xdg-open >/dev/null 2>&1; then
                nohup xdg-open "$labcat_url" >/dev/null 2>&1 &
            else
                echo "Open $labcat_url in your browser."
            fi ;;
        *) echo "Open $labcat_url in your browser." ;;
    esac
}

case "$labcat_action" in
    start)
        if [ "$labcat_open" = yes ]; then
            choose_mode
            if [ "$labcat_mode" = desktop ]; then prepare_desktop; fi
        fi
        echo 'Starting Labcat; waiting for the application to be ready...'
        if ! start_service; then
            fail 'Startup failed. Load the supplied image archive with docker load --input <archive.tar>, or inspect ./labcat.sh logs. No UI window was opened.'
        fi
        read_url
        echo 'Closing the window leaves the service running. Stop it with: ./labcat.sh stop'
        if [ "$labcat_open" = yes ]; then open_window; save_mode; fi
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
