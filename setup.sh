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

# Set by preflight, read by install_adsb. Declared here so the ordering is
# explicit rather than a happy accident of which phase runs first.
ARCH=""

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

# On PATH, or already sitting in the directory setup installs into. Both
# preflight and install_adsb ask this one question, so a second run cannot
# report "missing (optional)" and then "already installed" in the same
# breath -- which is exactly what happens when $PREFIX is not on PATH.
adsb_installed() { have_command adsb-tui || [ -x "$PREFIX/adsb-tui" ]; }

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
    local cols="" winsize=""
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

# What to do about whatever the table reported as missing.
#
# It belongs here rather than only in dependency_gate: `--check` exits
# straight after preflight, so for anyone who reads the table first -- which
# is the point of --check -- the gate's remedies are three phases and one
# commitment away. A table naming four tools and no way to get any of them is
# the "which prerequisites do I need?" problem restated, not solved.
#
# adsb-tui is listed too, with setup.sh itself as the fix. Left out, the one
# optional dependency is also the only one the table offers no answer for.
missing_advice() {
    local formulae
    formulae="$(missing_formulae)"
    [ -z "$formulae" ] && have_command uv && adsb_installed && return 0

    say ""
    say "To install what is missing:"
    [ -n "$formulae" ] && say "  brew install$formulae"
    have_command uv ||
        say "  curl -LsSf https://astral.sh/uv/install.sh | INSTALLER_NO_MODIFY_PATH=1 sh"
    adsb_installed ||
        say "  ./setup.sh   fetches adsb-tui; optional, the cockpit runs without it"
    say ""
    say "Or run ./setup.sh, which does all of it behind one prompt."
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
    adsb_installed && row adsb-tui "found" || row adsb-tui "missing (optional)"
    check_pyenv
    check_width
    missing_advice
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
        # INSTALLER_NO_MODIFY_PATH=1 is load-bearing, not noise: without it
        # astral's installer appends `. "$HOME/.local/bin/env"` to ~/.zshrc,
        # ~/.bash_profile AND ~/.profile. Nothing in kcgx may edit a shell
        # profile -- link_launcher prints the export line and explicitly
        # leaves applying it to the user, and delegating the same edit to
        # somebody else's installer three phases earlier would make that
        # promise a lie. (Verified against the installer source: it reads
        # UV_NO_MODIFY_PATH first, then INSTALLER_NO_MODIFY_PATH.)
        curl -LsSf https://astral.sh/uv/install.sh | INSTALLER_NO_MODIFY_PATH=1 sh
        # ...which is also why this line exists: the profile is untouched,
        # so this process has to put the new uv on its own PATH itself.
        PATH="$HOME/.local/bin:$PATH"
    fi
}

# The dependencies without which there is no cockpit, re-checked rather
# than trusted from phase 1: the prompt may have been declined, or
# Homebrew may have failed.
#
# `uv-only` narrows it to uv, so phase 3 can stop before `uv sync` reports
# a sync failure for a machine where uv was never installed at all. The
# unnarrowed call is the spec's launch gate, immediately before the
# hand-off. Everything between the two still runs: the wiring phases are
# worth doing even when the cockpit cannot open yet.
dependency_gate() {
    local blocked="" formulae="" remedy=""

    have_command uv || blocked="uv"
    if [ "${1:-all}" != "uv-only" ]; then
        have_command ffmpeg || { blocked="$blocked ffmpeg"; formulae="$formulae ffmpeg"; }
        tmux_new_enough     || { blocked="$blocked tmux(3.1+)"; formulae="$formulae tmux"; }
    fi
    blocked="${blocked# }"
    [ -z "$blocked" ] && return 0

    # tmux(3.1+) is how the missing list reads, not how brew takes it.
    if [ -n "$formulae" ]; then
        remedy="$remedy
  brew install$formulae"
    fi
    if ! have_command uv; then
        remedy="$remedy
  curl -LsSf https://astral.sh/uv/install.sh | INSTALLER_NO_MODIFY_PATH=1 sh"
    fi

    say ""
    die "still missing: $blocked
The cockpit cannot open without these. Install them and run this again:$remedy"
}

sync_project() {
    # A missing uv is not a sync failure -- it is the reason there can be
    # no sync. Route it through the same gate as every other fatal
    # dependency so the user gets the install line, not a message about
    # dependency resolution.
    dependency_gate uv-only
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

install_adsb() {
    if adsb_installed; then
        say "adsb-tui already installed."
        return 0
    fi
    if [ "$ARCH" = "unsupported" ]; then
        warn "no adsb-tui release for $(uname -m); the radar pane will be empty."
        return 0
    fi

    say ""
    say "Installing adsb-tui $ADSB_VERSION (the radar pane)."
    say "  From https://github.com/j4v3l/ADS-B_TUI"
    say "  Licence: ADS-B TUI Non-Commercial License -- not OSI-approved."
    say "  Downloading the published release; nothing is built from source."
    say ""

    # Non-fatal by design: a cockpit with working audio beats no cockpit.
    if curl -fL "$RELEASE_URL/$ADSB_VERSION/adsb-tui-$ARCH.tar.gz" \
        | tar xzf - -C "$PREFIX" 2>/dev/null; then
        chmod +x "$PREFIX/adsb-tui" 2>/dev/null || true
        # A tar that unpacked something other than the binary exits 0 just
        # like a good one, so "the download worked" is not the same claim
        # as "adsb-tui is installed". Only make the one that is true.
        if [ -x "$PREFIX/adsb-tui" ]; then
            say "Installed $PREFIX/adsb-tui"
            return 0
        fi
        warn "the adsb-tui archive held no usable binary; the radar pane will be empty."
    else
        warn "could not download adsb-tui; the radar pane will be empty."
    fi
    warn "Everything else still works. Re-run setup.sh to try again."
}

# adsb-tui defaults to http://adsb.local/data/aircraft.json -- a receiver on
# your own network. Without one the radar is empty, so point it at a public
# aggregator. 2 s because both free providers rate-limit near 1 req/s and
# api.adsb.lol returned 429 at that rate where api.airplanes.live did not.
write_adsb_config() {
    if [ -e "$ADSB_CONFIG" ]; then
        say "adsb-tui config already exists; leaving it alone."
        return 0
    fi
    mkdir -p "$(dirname "$ADSB_CONFIG")"
    cat > "$ADSB_CONFIG" <<'TOML'
# Written by kcgx setup.sh. Safe to edit -- setup never overwrites it.
#
# Live aircraft with no receiver hardware and no API key. kcgx fills in
# {lat}/{lon} per launch from the airport you pick, so this file does not
# pin a fixed location of its own.
url_template = "https://api.airplanes.live/v2/point/{lat}/{lon}/{range_nm}"
refresh_secs = 2
TOML
    say "Wrote $ADSB_CONFIG"
}

usage() {
    say "Usage: ./setup.sh [--check | --help]"
    say ""
    say "  (no arguments)  install everything kcgx needs and open the cockpit"
    say "  --check         print the dependency table and exit, changing nothing"
    say "  --help, -h      this message"
}

# An unrecognised argument used to fall through to the full install and an
# exec into the cockpit -- so a typo, or a flag this script does not have,
# silently did the most consequential thing it can do.
if [ "$#" -gt 1 ]; then
    warn "unexpected argument: $2"
    usage >&2
    exit 2
fi

case "${1:-}" in
    "") ;;
    --check)   preflight; exit 0 ;;
    --help|-h) usage; exit 0 ;;
    *)
        warn "unknown argument: $1"
        usage >&2
        exit 2
        ;;
esac

preflight
install_prerequisites
sync_project
link_launcher
install_adsb
write_adsb_config

# The launch gate. Launching into a failure the script already knows
# about would be worse than stopping here with the command that fixes it.
dependency_gate

say ""
say "Setup complete. Opening the cockpit..."

if [ -n "${KCGX_SETUP_NO_LAUNCH:-}" ]; then
    exit 0
fi

# By absolute path, not by name: a PATH the user has not reloaded yet must
# not stop the cockpit opening on this first run.
exec "$REPO/bin/kcgx"
