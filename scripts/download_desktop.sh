#!/bin/sh
# Download only the repository-pinned official native shell; never compile it.
set -eu
umask 077
labcat_root=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
fail() { echo "Labcat download: $*" >&2; exit 1; }
[ "$#" -eq 0 ] || fail 'Usage: sh scripts/download_desktop.sh'
case "$(uname -s):$(uname -m)" in
    Darwin:arm64|Darwin:aarch64) labcat_target=aarch64-apple-darwin; labcat_name=Labcat.app ;;
    Darwin:x86_64) labcat_target=x86_64-apple-darwin; labcat_name=Labcat.app ;;
    Linux:x86_64) labcat_target=x86_64-unknown-linux-gnu; labcat_name=labcat-desktop ;;
    *) fail 'No prebuilt native app is published for this platform. Use --browser or --desktop to build from source.' ;;
esac
labcat_manifest="$labcat_root/scripts/desktop-release.tsv"
[ -f "$labcat_manifest" ] && [ ! -L "$labcat_manifest" ] || fail 'The pinned native release manifest is missing.'
labcat_rows=$(awk -F '\t' -v target="$labcat_target" '$1 == target {print}' "$labcat_manifest")
[ "$(printf '%s\n' "$labcat_rows" | wc -l | tr -d ' ')" = 1 ] && [ -n "$labcat_rows" ] || fail 'This checkout has no unique native release for this platform. Use --browser or update the checkout.'
labcat_tab=$(printf '\t')
IFS="$labcat_tab" read -r labcat_match labcat_tag labcat_asset labcat_sha labcat_extra <<EOF
$labcat_rows
EOF
[ -z "$labcat_extra" ] && [ "$labcat_match" = "$labcat_target" ] || fail 'Invalid native release entry.'
case "$labcat_tag" in native-v[0-9]*) ;; *) fail 'Invalid native release tag.' ;; esac
case "$labcat_tag" in *[!A-Za-z0-9._-]*) fail 'Invalid native release tag.' ;; esac
[ "$labcat_asset" = "Labcat-$labcat_target.tar.gz" ] || fail 'Invalid native release filename.'
[ "${#labcat_sha}" -eq 64 ] || fail 'This native release has no pinned checksum yet.'
case "$labcat_sha" in *[!a-f0-9]*) fail 'Invalid native release checksum.' ;; esac
command -v curl >/dev/null 2>&1 || fail 'curl is required to download the native app.'
if command -v shasum >/dev/null 2>&1; then labcat_digest=shasum; elif command -v sha256sum >/dev/null 2>&1; then labcat_digest=sha256sum; else fail 'A SHA-256 tool (shasum or sha256sum) is required.'; fi
[ ! -L "$labcat_root/desktop-bin" ] || fail 'desktop-bin must not be a symbolic link.'
mkdir -p "$labcat_root/desktop-bin"
[ ! -e "$labcat_root/desktop-bin/$labcat_name" ] && [ ! -L "$labcat_root/desktop-bin/$labcat_name" ] || fail 'A native app already exists in desktop-bin. It has not been changed.'
labcat_stage=$(mktemp -d "$labcat_root/desktop-bin/.download.XXXXXX") || fail 'Cannot create a download directory.'
trap 'rm -rf "$labcat_stage"' 0
trap 'exit 1' HUP INT TERM
labcat_archive="$labcat_stage/$labcat_asset"
echo "Downloading the native Labcat app for $labcat_target..."
curl --fail --location --proto '=https' --proto-redir '=https' --connect-timeout 20 --max-time 300 --max-filesize 134217728 --output "$labcat_archive" "https://github.com/kewh5868/labcat/releases/download/$labcat_tag/$labcat_asset" || fail 'Native app download failed. Retry, or explicitly choose --browser. No build tools were run.'
[ "$(wc -c < "$labcat_archive" | tr -d ' ')" -le 134217728 ] || fail 'Native archive exceeds the size limit.'
if [ "$labcat_digest" = shasum ]; then labcat_actual=$(shasum -a 256 "$labcat_archive"); else labcat_actual=$(sha256sum "$labcat_archive"); fi
[ "${labcat_actual%% *}" = "$labcat_sha" ] || fail 'Native app checksum mismatch. Nothing was installed.'
# The checksum pins repository-reviewed bytes. Also constrain extraction paths/types.
tar -tzf "$labcat_archive" > "$labcat_stage/entries" || fail 'Invalid native archive.'
awk -v root="$labcat_name" '
    BEGIN { valid=1; count=0 }
    { count++; if ($0 != root && $0 != root "/" && index($0,root "/") != 1) valid=0;
      if ($0 ~ /(^|\/)\.\.?($|\/)/ || $0 ~ /[\\:]/) valid=0 }
    END { exit !(valid && count > 0 && count < 1000) }
' "$labcat_stage/entries" || fail 'Unsafe native archive path.'
tar -tvzf "$labcat_archive" > "$labcat_stage/types" || fail 'Invalid native archive.'
awk 'substr($0,1,1) != "-" && substr($0,1,1) != "d" {exit 1}' "$labcat_stage/types" || fail 'Native archive contains unsupported links or entries.'
mkdir "$labcat_stage/unpack"
tar -xzf "$labcat_archive" -C "$labcat_stage/unpack" || fail 'Cannot unpack the native app.'
if [ "$labcat_name" = Labcat.app ]; then labcat_binary="$labcat_stage/unpack/Labcat.app/Contents/MacOS/labcat-desktop"; else labcat_binary="$labcat_stage/unpack/labcat-desktop"; fi
[ -f "$labcat_binary" ] && [ ! -L "$labcat_binary" ] || fail 'Native executable is missing.'
chmod 755 "$labcat_binary"
[ ! -e "$labcat_root/desktop-bin/$labcat_name" ] && [ ! -L "$labcat_root/desktop-bin/$labcat_name" ] || fail 'Another install appeared during download. It has not been changed.'
mv "$labcat_stage/unpack/$labcat_name" "$labcat_root/desktop-bin/$labcat_name"
echo 'Native app download verified. No Node, Rust or compiler tools were used.'
