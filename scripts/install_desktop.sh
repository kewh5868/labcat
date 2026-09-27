#!/bin/sh
# Install the native UI for this local Docker deployment, without administrator access.
set -eu
umask 077
PATH="$PATH:$HOME/.cargo/bin:/usr/local/bin:/opt/homebrew/bin"
export PATH
labcat_source=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
fail() { echo "Labcat desktop: $*" >&2; exit 1; }
case "${1:-}" in
    '') ;;
    -h|--help)
        echo 'Usage: sh scripts/install_desktop.sh'
        echo 'Installs Labcat for the current user. Uses desktop-bin when supplied; otherwise builds with Node/npm, Rust/Cargo and native OS development tools.'
        echo 'No system dependencies are installed automatically. Start Docker before opening Labcat.'
        exit 0 ;;
    *) fail 'Unknown argument. Run --help for installation usage.' ;;
esac
[ "$#" -le 1 ] || fail 'Unexpected installer arguments.'
case "$HOME" in /*) ;; *) fail 'HOME must be an absolute path.' ;; esac
case "$labcat_source$HOME${XDG_DATA_HOME:-}${LABCAT_DESKTOP_INSTALL_DIR:-}" in *'
'*) fail 'Installation paths cannot contain newlines.' ;; esac
for labcat_required in labcat.sh compose.yaml; do
    [ -f "$labcat_source/$labcat_required" ] && [ ! -L "$labcat_source/$labcat_required" ] || fail "Missing regular deployment file: $labcat_required"
done
if [ -e "$labcat_source/compose.local.yaml" ] || [ -L "$labcat_source/compose.local.yaml" ]; then
    [ -f "$labcat_source/compose.local.yaml" ] && [ ! -L "$labcat_source/compose.local.yaml" ] || fail 'compose.local.yaml must be a regular file, not a symbolic link.'
fi
labcat_deployment=$labcat_source
labcat_has_deployment=no
if [ -e "$labcat_source/.labcat-project-directory" ] || [ -L "$labcat_source/.labcat-project-directory" ]; then
    labcat_has_deployment=yes
    [ -f "$labcat_source/.labcat-project-directory" ] && [ ! -L "$labcat_source/.labcat-project-directory" ] || fail 'The existing deployment directory setting must be a regular file.'
    IFS= read -r labcat_deployment < "$labcat_source/.labcat-project-directory" || fail 'The existing deployment directory setting is invalid.'
    [ "$(wc -l < "$labcat_source/.labcat-project-directory" | tr -d ' ')" = 1 ] && [ "$(cat "$labcat_source/.labcat-project-directory")" = "$labcat_deployment" ] || fail 'The existing deployment directory setting is invalid.'
    case "$labcat_deployment" in /*) ;; *) fail 'The existing deployment directory must be absolute.' ;; esac
    [ -d "$labcat_deployment" ] || fail 'The original deployment directory was moved. Restore it or update the local deployment before installing.'
fi
labcat_platform=$(uname -s)
case "$labcat_platform" in
    Darwin)
        labcat_parent="${LABCAT_DESKTOP_INSTALL_DIR:-$HOME/Applications}"
        labcat_destination="$labcat_parent/Labcat.app"
        labcat_prebuilt="$labcat_source/desktop-bin/Labcat.app"
        labcat_built="$labcat_source/desktop/target/release/bundle/macos/Labcat.app"
        command -v codesign >/dev/null 2>&1 || fail 'macOS code signing tools are required to verify the installed app.'
        ;;
    Linux)
        labcat_data="${XDG_DATA_HOME:-$HOME/.local/share}"
        case "$labcat_data" in /*) ;; *) fail 'XDG_DATA_HOME must be absolute.' ;; esac
        labcat_parent="${LABCAT_DESKTOP_INSTALL_DIR:-$labcat_data/labcat}"
        labcat_destination="$labcat_parent/desktop"
        labcat_prebuilt="$labcat_source/desktop-bin/labcat-desktop"
        labcat_built="$labcat_source/desktop/target/release/labcat-desktop"
        ;;
    *) fail 'Native installation is supported on macOS and Linux; use labcat.ps1 on Windows or --browser.' ;;
esac
case "$labcat_parent" in /*) ;; *) fail 'LABCAT_DESKTOP_INSTALL_DIR must be absolute.' ;; esac
[ ! -L "$labcat_parent" ] && [ ! -L "$labcat_destination" ] || fail 'The install destination must not be a symbolic link.'
# Never replace an unrelated directory or application with the same name.
if [ -e "$labcat_destination" ]; then
    [ -d "$labcat_destination" ] || fail 'The installation destination is not a Labcat application directory.'
    if [ "$labcat_platform" = Darwin ]; then
        labcat_identity=$( /usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$labcat_destination/Contents/Info.plist" 2>/dev/null) || labcat_identity=
        [ "$labcat_identity" = org.labcat.desktop ] || [ "$(cat "$labcat_destination/Contents/Resources/.labcat-managed-install" 2>/dev/null || true)" = labcat-desktop-v1 ] || fail 'The destination is not a recognized Labcat app; choose an empty LABCAT_DESKTOP_INSTALL_DIR.'
    else
        [ "$(cat "$labcat_destination/.labcat-managed-install" 2>/dev/null || true)" = labcat-desktop-v1 ] || fail 'The destination is not a managed Labcat installation; choose an empty LABCAT_DESKTOP_INSTALL_DIR.'
    fi
fi
labcat_native=$labcat_prebuilt
if [ "$labcat_platform" = Darwin ]; then
    labcat_executable="$labcat_native/Contents/MacOS/labcat-desktop"
else
    labcat_executable=$labcat_native
fi
if [ ! -x "$labcat_executable" ]; then
    [ -z "${CARGO_BUILD_TARGET:-}${CARGO_TARGET_DIR:-}" ] || fail 'Unset CARGO_BUILD_TARGET and CARGO_TARGET_DIR for this native source installation, so the installed build matches this machine.'
    for labcat_tool in node npm cargo rustc; do
        command -v "$labcat_tool" >/dev/null 2>&1 || fail "A source installation requires $labcat_tool. Install the documented desktop prerequisites, or explicitly start with ./labcat.sh --browser."
    done
    for labcat_required in desktop/package-lock.json desktop/Cargo.lock desktop/tauri.conf.json; do
        [ -f "$labcat_source/$labcat_required" ] || fail 'This bundle has no native app or complete desktop sources. Use a matching native bundle or --browser.'
    done
    case "$labcat_platform" in
        Darwin)
            command -v xcode-select >/dev/null 2>&1 && xcode-select -p >/dev/null 2>&1 || fail 'Install the Xcode Command Line Tools with xcode-select --install, then retry.' ;;
        Linux)
            command -v cc >/dev/null 2>&1 && command -v pkg-config >/dev/null 2>&1 || fail 'A source installation needs a C compiler and pkg-config. See the Linux desktop prerequisites.'
            pkg-config --exists webkit2gtk-4.1 gtk+-3.0 librsvg-2.0 libsoup-3.0 || fail 'Install the WebKitGTK 4.1, GTK 3, librsvg and libsoup 3 development packages listed in the desktop installation guide.' ;;
    esac
    echo 'Building the native Labcat app with the checked-in dependency locks...'
    npm ci --prefix "$labcat_source/desktop" --ignore-scripts || fail 'Installing locked desktop build dependencies failed; the existing application was not changed.'
    if [ "$labcat_platform" = Darwin ]; then
        npm run build --prefix "$labcat_source/desktop" -- --bundles app -- --locked || fail 'Native build failed; the existing application was not changed.'
    else
        npm run build --prefix "$labcat_source/desktop" -- --no-bundle -- --locked || fail 'Native build failed; the existing application was not changed.'
    fi
    labcat_native=$labcat_built
fi
[ ! -L "$labcat_native" ] || fail 'The native app source must not be a symbolic link.'
mkdir -p "$labcat_parent"
labcat_stage=$(mktemp -d "$labcat_parent/.labcat-install.XXXXXX") || fail 'Cannot create a staged installation.'
labcat_backup=
cleanup() {
    if [ -n "$labcat_backup" ] && [ -e "$labcat_backup" ] ; then
        rm -rf "$labcat_destination"
        if ! mv "$labcat_backup" "$labcat_destination"; then
            echo "Labcat desktop: Could not restore the previous app. It is preserved at: $labcat_backup" >&2
            return
        fi
    fi
    rm -rf "$labcat_stage"
}
trap cleanup 0
trap 'exit 1' HUP INT TERM
if [ "$labcat_platform" = Darwin ]; then
    [ -x "$labcat_native/Contents/MacOS/labcat-desktop" ] && [ ! -L "$labcat_native/Contents/MacOS/labcat-desktop" ] || fail 'The built app has no valid native executable.'
    cp -R "$labcat_native" "$labcat_stage/Labcat.app"
    labcat_ready="$labcat_stage/Labcat.app"
    labcat_metadata="$labcat_ready/Contents/Resources"
    labcat_launcher="$labcat_metadata/launcher"
    [ ! -L "$labcat_ready/Contents" ] && [ ! -L "$labcat_ready/Contents/Resources" ] || fail 'Native app resource directories must not be symbolic links.'
else
    [ -x "$labcat_native" ] || fail 'The build produced no executable native app.'
    labcat_ready="$labcat_stage/desktop"
    mkdir "$labcat_ready"
    cp "$labcat_native" "$labcat_ready/labcat-desktop"
    chmod 755 "$labcat_ready/labcat-desktop"
    labcat_metadata=$labcat_ready
    labcat_launcher="$labcat_ready/launcher"
    if [ -f "$labcat_source/desktop/icons/128x128.png" ]; then
        cp "$labcat_source/desktop/icons/128x128.png" "$labcat_ready/labcat.png"
    fi
fi
printf '%s\n' labcat-desktop-v1 > "$labcat_metadata/.labcat-managed-install"
printf '%s\n' "$labcat_source" > "$labcat_metadata/.labcat-install-source"
# Refresh only the fixed launcher resources, never copy secrets or the source tree.
rm -rf "$labcat_launcher"
mkdir -p "$labcat_launcher"
cp "$labcat_source/labcat.sh" "$labcat_launcher/labcat.sh"
cp "$labcat_source/compose.yaml" "$labcat_launcher/compose.yaml"
if [ -f "$labcat_source/compose.local.yaml" ]; then
    cp "$labcat_source/compose.local.yaml" "$labcat_launcher/compose.local.yaml"
fi
if [ -f "$labcat_source/compose.local.yaml" ] || [ "$labcat_has_deployment" = yes ]; then
    printf '%s\n' "$labcat_deployment" > "$labcat_launcher/.labcat-project-directory"
fi
chmod 700 "$labcat_launcher/labcat.sh"
if [ "$labcat_platform" = Darwin ]; then
    codesign --force --deep --sign - "$labcat_ready" || fail 'Local signing failed; the existing application was not changed.'
    codesign --verify --deep --strict "$labcat_ready" || fail 'Installed app signature verification failed; the existing application was not changed.'
fi
if [ -e "$labcat_destination" ]; then
    labcat_backup="$labcat_stage/previous"
    mv "$labcat_destination" "$labcat_backup"
fi
mv "$labcat_ready" "$labcat_destination"
if [ "$labcat_platform" = Linux ]; then
    labcat_entries="${LABCAT_DESKTOP_INSTALL_DIR:-$labcat_data}/applications"
    [ ! -L "$labcat_entries" ] && [ ! -L "$labcat_entries/labcat.desktop" ] || fail 'The desktop entry destination must not be a symbolic link.'
    mkdir -p "$labcat_entries"
    # Desktop Entry Exec quoting is not shell quoting. Escape reserved characters
    # and percent field codes so paths with spaces or punctuation remain literal.
    labcat_exec=$(printf '%s' "$labcat_destination/labcat-desktop" | sed 's/\\/\\\\\\\\/g; s/"/\\\\"/g; s/`/\\\\`/g; s/\$/\\\\$/g; s/%/%%/g')
    labcat_entry=$(mktemp "$labcat_entries/.labcat.XXXXXX")
    {
        printf '%s\n' '[Desktop Entry]' 'Type=Application' 'Name=Labcat' 'Comment=Curious. Clever. Research Companion.'
        printf 'Exec="%s"\n' "$labcat_exec"
        if [ -f "$labcat_destination/labcat.png" ]; then printf 'Icon=%s\n' "$labcat_destination/labcat.png"; fi
        printf '%s\n' 'Terminal=false' 'Categories=Education;Science;'
    } > "$labcat_entry"
    chmod 644 "$labcat_entry"
    mv "$labcat_entry" "$labcat_entries/labcat.desktop"
fi
labcat_backup=
echo "Installed Labcat: $labcat_destination"
echo 'Open Labcat from your applications menu, or run ./labcat.sh --desktop. Docker must be running.'
