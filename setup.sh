#!/usr/bin/env bash
# setup.sh — install everything kcgx needs, wire it up, and open the cockpit.
#
# Idempotent: running it twice is safe and ends in the same place. Every
# phase says what it is about to do before doing it.
#
# Test seams (all default to production behaviour when unset):
#   KCGX_SETUP_YES         non-empty skips the install prompt
#   KCGX_SETUP_NO_LAUNCH   non-empty stops before exec'ing the launcher
#   KCGX_SETUP_RELEASE_URL base URL for the adsb-tui release tarball

set -euo pipefail

REPO="$(cd -P "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

ADSB_VERSION="v0.2.1"
RELEASE_URL="${KCGX_SETUP_RELEASE_URL:-https://github.com/j4v3l/ADS-B_TUI/releases/download}"
PREFIX="$HOME/.local/bin"
ADSB_CONFIG="$HOME/.config/ads-b-tui/adsb-tui.toml"
MIN_COLS=100

say()  { printf '%s\n' "$*"; }
warn() { printf 'setup: %s\n' "$*" >&2; }
die()  { printf 'setup: %s\n' "$*" >&2; exit 1; }

have_command() { command -v "$1" >/dev/null 2>&1; }

# macos-arm64 / macos-x64, matching the upstream release asset names.
detect_arch() {
    case "$(uname -m)" in
        arm64|aarch64) printf 'macos-arm64' ;;
        x86_64)        printf 'macos-x64' ;;
        *)             printf 'unsupported' ;;
    esac
}

# tmux 3.1+ is required by bin/kcgx:69 for `split-window -l <cells>`.
tmux_new_enough() {
    local version
    have_command tmux || return 1
    version="$(tmux -V | grep -oE '[0-9]+\.[0-9]+' | head -1)"
    awk -v v="$version" 'BEGIN {
        split(v, p, ".");
        exit !(p[1] > 3 || (p[1] == 3 && p[2] >= 1))
    }'
}

row() { printf '  %-12s %s\n' "$1" "$2"; }

# Advisory only. Both describe the user's environment rather than anything
# setup installs, so neither changes the exit status.

check_pyenv() {
    local python_path
    python_path="$(command -v python 2>/dev/null || true)"
    case "$python_path" in
        */.pyenv/shims/*)
            say "  note: pyenv shims come before uv on your PATH, so bare"
            say "        \`python\` will not work inside this repo. That is"
            say "        expected -- every kcgx command uses \`uv run\`,"
            say "        which ignores pyenv entirely."
            ;;
    esac
}

check_width() {
    local cols=""
    if winsize="$(stty size 2>/dev/null </dev/tty)"; then
        cols="${winsize##* }"
    elif [ -n "${COLUMNS:-}" ]; then
        cols="$COLUMNS"
    fi
    case "$cols" in
        ''|*[!0-9]*) return 0 ;;
    esac
    if [ "$cols" -lt "$MIN_COLS" ]; then
        say "  note: this terminal is $cols columns; kcgx needs $MIN_COLS."
    fi
}

preflight() {
    ARCH="$(detect_arch)"
    say "kcgx setup"
    say ""
    say "Checking what you have:"
    have_command uv     && row uv "found" || row uv "missing"
    have_command ffmpeg && row ffmpeg "found" || row ffmpeg "missing"
    if have_command tmux; then
        if tmux_new_enough; then
            row tmux "found"
        else
            row tmux "too old (needs 3.1+)"
        fi
    else
        row tmux "missing"
    fi
    have_command curl     && row curl "found" || row curl "missing"
    have_command adsb-tui && row adsb-tui "found" || row adsb-tui "missing (optional)"
    check_pyenv
    check_width
    say ""
}

if [ "${1:-}" = "--check" ]; then
    preflight
    exit 0
fi

preflight
