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

# Homebrew formulae still needed, space separated. tmux counts as missing
# when it is present but older than 3.1 -- upgrading is the same command.
missing_formulae() {
    local needed=""
    have_command ffmpeg || needed="$needed ffmpeg"
    tmux_new_enough || needed="$needed tmux"
    printf '%s' "${needed# }"
}

install_prerequisites() {
    local needed reply
    needed="$(missing_formulae)"

    if [ -z "$needed" ] && have_command uv; then
        return 0
    fi

    say "Setup wants to install:"
    [ -n "$needed" ] && say "  via Homebrew:  $needed"
    have_command uv || say "  via astral.sh: uv"
    say ""

    if [ -z "${KCGX_SETUP_YES:-}" ]; then
        printf 'Proceed? [y/N] '
        # From stdin, not /dev/tty. setup.sh is always a file, so stdin is
        # free -- and a /dev/tty read is untestable: under pytest there is
        # no controlling terminal, so it would fail open and "decline"
        # regardless of what the test typed, making the decline test pass
        # for the wrong reason.
        read -r reply || reply=""
        case "$reply" in
            [yY]|[yY][eE][sS]) ;;
            *) say "Nothing installed."; return 0 ;;
        esac
    fi

    if [ -n "$needed" ]; then
        have_command brew || die \
"Homebrew is needed to install:$needed
Install it first, then run this again:
  /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\"
See https://brew.sh"
        # Word splitting is intended: $needed is a list of formulae.
        # shellcheck disable=SC2086
        brew install $needed
    fi

    if ! have_command uv; then
        curl -LsSf https://astral.sh/uv/install.sh | sh
        PATH="$HOME/.local/bin:$PATH"
    fi
}

sync_project() {
    say "Installing Python dependencies (uv provides Python 3.14 itself)..."
    uv sync --project "$REPO" || die "uv sync failed; nothing was wired up."
}

link_launcher() {
    local target="$REPO/bin/kcgx" link="$PREFIX/kcgx"
    mkdir -p "$PREFIX"

    if [ -L "$link" ]; then
        # Already ours? Nothing to do. Somebody else's? Never clobber it.
        #
        # A plain string compare against what we would write, deliberately:
        # resolving the link through `cd`/`pwd` inside a test is a command
        # substitution that can fail under `set -e`, and anything that does
        # not match exactly is treated as foreign. Conservative in the safe
        # direction -- the cost of a false "foreign" is one message, the
        # cost of a false "ours" is destroying somebody's launcher.
        if [ "$(readlink "$link")" = "$target" ]; then
            say "Launcher already linked."
        else
            die "$link already exists and points somewhere else.
Remove it yourself if you want setup to manage it."
        fi
    elif [ -e "$link" ]; then
        die "$link already exists and is not a symlink.
Remove it yourself if you want setup to manage it."
    else
        ln -s "$target" "$link"
        say "Linked $link -> $target"
    fi

    case ":$PATH:" in
        *":$PREFIX:"*) ;;
        *)
            say ""
            say "WARNING: $PREFIX is not on your PATH."
            say "  Add this to your shell profile:"
            say "      export PATH=\"\$HOME/.local/bin:\$PATH\""
            say ""
            say "  This is not just about typing \`kcgx\`. Ctrl-b a (the"
            say "  airport picker) is bound to \`display-popup -E \"kcgx go\"\`,"
            say "  which resolves kcgx by name through the tmux server's own"
            say "  environment -- so without this the cockpit opens fine and"
            say "  the picker silently does nothing."
            say ""
            say "  A running tmux server captured its environment when it"
            say "  started, so restart it (kcgx stop) after changing PATH."
            say ""
            ;;
    esac
}

if [ "${1:-}" = "--check" ]; then
    preflight
    exit 0
fi

preflight
install_prerequisites
sync_project
link_launcher
