#!/usr/bin/env bash
# Build KCGX.app, the cockpit's own window (macOS).
#
#   macos/build.sh [destination]     default: ~/Applications/KCGX.app
#
# The destination is the app itself, not the folder to put it in, and
# whatever is there is replaced. So it must be named something.app, and
# anything already there must be a KCGX.app this script built: a folder
# given by mistake (~/Applications), or somebody else's app, is refused
# before anything is made or removed.
#
# One Swift file, compiled by swiftc from the Xcode command line tools, put
# in a bundle with its Info.plist and signed ad hoc. It is never notarised:
# it is built on the machine that runs it, so it carries no quarantine flag.
#
# The bundle is put together beside the destination and moved into place
# only once it is whole and signed. A build that fails leaves the app that
# was there, and a rebuild never writes into an app that is running.

set -euo pipefail

REPO="$(cd -P "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP="${1:-$HOME/Applications/KCGX.app}"
IDENTIFIER=com.kcgx.cockpit  # CFBundleIdentifier in Info.plist.in

while [ "${APP%/}" != "$APP" ]; do APP="${APP%/}"; done  # KCGX.app/ is KCGX.app
case "$APP" in
    *?.app) ;;
    *)
        printf 'kcgx: %s is not the path of an app, so nothing was built. The destination is the app itself, as in ~/Applications/KCGX.app\n' \
            "${1:-$APP}" >&2
        exit 2
        ;;
esac
if [ -e "$APP" ] || [ -L "$APP" ]; then
    if ! grep -qF "<string>$IDENTIFIER</string>" "$APP/Contents/Info.plist" 2>/dev/null; then
        printf 'kcgx: %s is there already and is not a KCGX.app built by this script (its Info.plist does not say %s), so it was left alone and nothing was built. Move it away, or build somewhere else.\n' \
            "$APP" "$IDENTIFIER" >&2
        exit 2
    fi
fi

for tool in swiftc codesign; do
    if ! command -v "$tool" >/dev/null 2>&1; then
        printf 'kcgx: %s not found, so KCGX.app was not built. It comes with the Xcode command line tools: xcode-select --install\n' "$tool" >&2
        exit 1
    fi
done

# For the right hand side of a sed s|||, inside an XML <string>: first what
# XML reads as markup, then what sed reads as its own.
fill() {
    printf '%s' "$1" | sed -e 's/&/\&amp;/g' -e 's/</\&lt;/g' -e 's/>/\&gt;/g' -e 's/[\\|&]/\\&/g'
}

STAGE="$(dirname "$APP")/.kcgx-building.$$"
NEW="$STAGE/$(basename "$APP")"
trap 'rm -rf "$STAGE"' EXIT
mkdir -p "$NEW/Contents/MacOS"

# Built for macOS 12 and later, whatever this Mac runs. The source guards
# the one newer call it makes with #available, and built for this Mac alone
# the compiler would warn that the guard is not needed.
swiftc -O -target "$(uname -m)-apple-macos12.0" -framework Cocoa -framework WebKit \
    "$REPO/macos/KCGXWindow.swift" -o "$NEW/Contents/MacOS/KCGX"
sed -e "s|@REPO@|$(fill "$REPO")|" -e "s|@PATH@|$(fill "$PATH")|" \
    "$REPO/macos/Info.plist.in" > "$NEW/Contents/Info.plist"
# The linker has already signed the binary, and codesign says so every
# time it replaces that signature: its words are shown only if it fails.
if ! signing="$(codesign --force --sign - "$NEW" 2>&1)"; then
    printf '%s\n' "$signing" >&2
    exit 1
fi

rm -rf "$APP"
mv "$NEW" "$APP"
printf 'kcgx: built %s\n' "$APP"
