#!/usr/bin/env bash
# setup.sh — install everything kcgx needs, prove it works, open the cockpit.
#
# Nine steps. Each announces itself, each asks before changing anything, and
# each is idempotent -- so the second run, the one you do when you think
# something went wrong, ends exactly where the first did.
#
# The contract is that reaching the end means the cockpit works: every
# dependency installed, every config written, and step 9 having actually run
# each moving part rather than having checked that a file exists. A setup
# script that finishes and leaves you with a broken pane has not finished.
#
# Test seams (all default to production behaviour when unset):
#   KCGX_SETUP_YES         non-empty takes every prompt's default answer
#   KCGX_SETUP_NO_LAUNCH   non-empty stops before exec'ing the launcher
#   KCGX_SETUP_RELEASE_URL base URL for the adsb-tui release tarball
#   KCGX_SETUP_OS          override the detected operating system
#   KCGX_SETUP_PLATFORM    override the detected release asset name
#   KCGX_SETUP_PKG         override the detected package manager
#   KCGX_SETUP_SKIP_NET    non-empty skips the two reachability probes

set -euo pipefail

REPO="$(cd -P "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Set by detect_platform, read by nearly every step. Declared here so the
# ordering is explicit rather than a happy accident of which step runs first.
OS=""        # macos | linux | unsupported
PLATFORM=""  # macos-arm64 | macos-x64 | linux-x64 | unsupported
PKG=""       # brew | apt | dnf | pacman | none
SUDO=""      # "" when root or on brew, else "sudo"

ADSB_VERSION="v0.2.1"
RELEASE_URL="${KCGX_SETUP_RELEASE_URL:-https://github.com/j4v3l/ADS-B_TUI/releases/download}"
PREFIX="$HOME/.local/bin"
# adsb-tui resolves its config under XDG, and says so in its own --help:
# "default path is $XDG_CONFIG_HOME/ads-b-tui/adsb-tui.toml". Hardcoding
# ~/.config wrote a file it would never read on a machine that sets the
# variable -- setup reported success and the radar came up empty.
ADSB_CONFIG="${XDG_CONFIG_HOME:-$HOME/.config}/ads-b-tui/adsb-tui.toml"
MIN_COLS=100
STEPS=9

say()  { printf '%s\n' "$*"; }
warn() { printf 'setup: %s\n' "$*" >&2; }
die()  { printf 'setup: %s\n' "$*" >&2; exit 1; }

have_command() { command -v "$1" >/dev/null 2>&1; }

step() { say ""; say "── Step $1/$STEPS  $2"; say ""; }
row()  { printf '  %-12s %s\n' "$1" "$2"; }
vrow() { printf '  %-16s %-6s %s\n' "$1" "$2" "${3:-}"; }

# Every prompt reads from stdin rather than /dev/tty. setup.sh is always a
# file, so stdin is free -- and a /dev/tty read is untestable: under pytest
# there is no controlling terminal, so the read would fail open regardless of
# what the test typed, making the decline test pass for the wrong reason.
confirm() {  # $1=question $2=default(y|n); returns 0 to proceed
    local reply default="${2:-y}" hint
    if [ "$default" = "y" ]; then hint="[Y/n]"; else hint="[y/N]"; fi
    if [ -n "${KCGX_SETUP_YES:-}" ]; then
        say "$1 $hint $default"
        [ "$default" = "y" ]
        return
    fi
    printf '%s %s ' "$1" "$hint"
    read -r reply || reply=""
    [ -z "$reply" ] && reply="$default"
    case "$reply" in
        [yY]|[yY][eE][sS]) return 0 ;;
        *) return 1 ;;
    esac
}

# -- platform ---------------------------------------------------------------
#
# Keyed on uname -s AND uname -m, not on -m alone. Keyed on the machine only,
# an x86_64 Linux box resolved to `macos-x64`, downloaded a Mach-O binary that
# unpacked cleanly and tested executable, and was reported as installed. The
# first sign of trouble was an empty radar pane with no error anywhere.
detect_platform() {
    case "$(uname -s)-$(uname -m)" in
        Darwin-arm64|Darwin-aarch64) printf 'macos-arm64' ;;
        Darwin-x86_64)               printf 'macos-x64' ;;
        Linux-x86_64)                printf 'linux-x64' ;;
        *)                           printf 'unsupported' ;;
    esac
}

detect_os() {
    case "$(uname -s)" in
        Darwin) printf 'macos' ;;
        Linux)  printf 'linux' ;;
        *)      printf 'unsupported' ;;
    esac
}

detect_pkg() {
    have_command brew && { printf 'brew'; return; }
    if [ "$OS" = "linux" ]; then
        have_command apt-get && { printf 'apt'; return; }
        have_command dnf     && { printf 'dnf'; return; }
        have_command pacman  && { printf 'pacman'; return; }
    fi
    printf 'none'
}

# One place that settles all four, so `--verify` and a full run cannot
# disagree about what machine they are on.
resolve_platform() {
    OS="${KCGX_SETUP_OS:-$(detect_os)}"
    PLATFORM="${KCGX_SETUP_PLATFORM:-$(detect_platform)}"
    PKG="${KCGX_SETUP_PKG:-$(detect_pkg)}"
    detect_sudo
}

# Homebrew installs as the invoking user and refuses to run under sudo.
detect_sudo() {
    [ "$PKG" = "brew" ] && return 0
    [ "$(id -u)" = "0" ] && return 0
    have_command sudo && SUDO="sudo"
}

# $1 = ffmpeg | tmux | portaudio. Empty output means "not a package here".
pkg_name() {
    case "$1" in
        ffmpeg|tmux) printf '%s' "$1" ;;
        portaudio)
            # Only Linux. The sounddevice wheel bundles its own PortAudio on
            # macOS, which is why this dependency stayed invisible for so
            # long: on Linux the same wheel ships no library at all and
            # `import sounddevice` dies with "PortAudio library not found"
            # before squelch draws anything.
            case "$PKG" in
                apt)        printf 'libportaudio2' ;;
                dnf|pacman) printf 'portaudio' ;;
            esac
            ;;
    esac
}

pkg_install_cmd() {  # $* = packages
    case "$PKG" in
        brew)   printf 'brew install %s' "$*" ;;
        apt)    printf '%sapt-get install -y %s' "${SUDO:+$SUDO }" "$*" ;;
        dnf)    printf '%sdnf install -y %s' "${SUDO:+$SUDO }" "$*" ;;
        pacman) printf '%spacman -S --needed --noconfirm %s' "${SUDO:+$SUDO }" "$*" ;;
    esac
}

# -- what is present --------------------------------------------------------

# Every version probe below reads its input to the end, and none of them
# terminates a pipeline early. `set -o pipefail` is on, and a `| head -1` or a
# `| grep -q` sends SIGPIPE upstream the moment it has what it wants: the
# pipeline then reports 141 and the whole probe reads as a missing tool. It
# fires on output long enough to still be flowing, so `tmux -V` got away with
# it and `ffmpeg -version` did not.

# tmux 3.1+ is required by bin/kcgx for `split-window -l <cells>`.
# The regex, not $2: builds spell it "3.2a" and "next-3.4".
tmux_version() {
    tmux -V 2>/dev/null |
        awk 'match($0, /[0-9]+\.[0-9]+/) && !v { v = substr($0, RSTART, RLENGTH) }
             END { print v }'
}

tmux_new_enough() {
    local version
    have_command tmux || return 1
    version="$(tmux_version)"
    [ -n "$version" ] || return 1
    awk -v v="$version" 'BEGIN {
        split(v, p, ".");
        exit !(p[1] > 3 || (p[1] == 3 && p[2] >= 1))
    }'
}

# On PATH, or already sitting in the directory setup installs into. Both the
# preflight and step 6 ask this one question, so a second run cannot report
# "missing" and then "already installed" in the same breath -- which is
# exactly what happens when $PREFIX is not on PATH.
adsb_installed() { have_command adsb-tui || [ -x "$PREFIX/adsb-tui" ]; }

adsb_binary() {
    if have_command adsb-tui; then command -v adsb-tui; else printf '%s' "$PREFIX/adsb-tui"; fi
}

# The install decision only. The truth is `import sounddevice` in step 9:
# ldconfig can be absent or unreadable, and a false "missing" here costs one
# no-op package install, while a false "present" costs a silent audio failure.
portaudio_present() {
    local ldconfig
    [ "$OS" != "linux" ] && return 0
    ldconfig="$(command -v ldconfig || true)"
    [ -n "$ldconfig" ] || ldconfig="/sbin/ldconfig"
    [ -x "$ldconfig" ] || return 1
    # Not `grep -q`: it exits on the first match, and the SIGPIPE that sends
    # upstream fails the pipeline under pipefail -- reporting a PortAudio
    # that is plainly installed as missing.
    "$ldconfig" -p 2>/dev/null | grep 'libportaudio\.so' >/dev/null
}

version_of() {  # best-effort, for the table only
    case "$1" in
        uv)     uv --version 2>/dev/null | awk 'NR == 1 { v = $2 } END { print v }' ;;
        ffmpeg) ffmpeg -version 2>/dev/null | awk 'NR == 1 { v = $3 } END { print v }' ;;
        tmux)   tmux_version ;;
        curl)   curl --version 2>/dev/null | awk 'NR == 1 { v = $2 } END { print v }' ;;
    esac
}

# Everything still missing, as a package list for the detected manager.
missing_packages() {
    local needed=""
    have_command ffmpeg  || needed="$needed $(pkg_name ffmpeg)"
    tmux_new_enough      || needed="$needed $(pkg_name tmux)"
    portaudio_present    || needed="$needed $(pkg_name portaudio)"
    # shellcheck disable=SC2086
    set -- $needed
    printf '%s' "$*"
}

# -- advisory ---------------------------------------------------------------

check_pyenv() {
    local python_path
    python_path="$(command -v python 2>/dev/null || true)"
    case "$python_path" in
        */.pyenv/shims/*)
            say ""
            say "  note: pyenv shims come before uv on your PATH, so bare"
            say "        \`python\` will not work inside this repo. That is"
            say "        expected -- every kcgx command uses \`uv run\`,"
            say "        which ignores pyenv entirely."
            ;;
    esac
}

terminal_cols() {
    local winsize
    if winsize="$(stty size 2>/dev/null </dev/tty)"; then
        printf '%s' "${winsize##* }"
    elif [ -n "${COLUMNS:-}" ]; then
        printf '%s' "$COLUMNS"
    fi
}

check_width() {
    local cols
    cols="$(terminal_cols)"
    case "$cols" in ''|*[!0-9]*) return 0 ;; esac
    if [ "$cols" -lt "$MIN_COLS" ]; then
        say ""
        say "  note: this terminal is $cols columns; kcgx needs $MIN_COLS."
    fi
}

# What to do about whatever the table reported as missing. It belongs beside
# the finding rather than only in the steps that follow: `--check` exits
# straight after this, so for anyone reading the table first -- which is the
# point of --check -- a remedy printed three steps later is no remedy. A table
# naming five tools and no way to get any of them restates the "which
# prerequisites do I need?" problem instead of answering it.
missing_advice() {
    local packages
    packages="$(missing_packages)"
    [ -z "$packages" ] && have_command uv && adsb_installed && return 0

    say ""
    say "To install what is missing:"
    if [ -n "$packages" ]; then
        if [ "$PKG" = "none" ]; then
            say "  (no supported package manager found) $packages"
        else
            say "  $(pkg_install_cmd "$packages")"
        fi
    fi
    have_command uv ||
        say "  curl -LsSf https://astral.sh/uv/install.sh | INSTALLER_NO_MODIFY_PATH=1 sh"
    adsb_installed ||
        say "  ./setup.sh   fetches adsb-tui $ADSB_VERSION from its published release"
    say ""
    say "Or run ./setup.sh, which does all of it, asking before each step."
}

# -- step 1 -----------------------------------------------------------------

preflight() {
    resolve_platform
    step 1 "What you have"

    row "platform" "$PLATFORM"
    row "packages" "$PKG"
    say ""
    have_command uv     && row uv     "found    $(version_of uv)"     || row uv     "missing"
    have_command ffmpeg && row ffmpeg "found    $(version_of ffmpeg)" || row ffmpeg "missing"
    if have_command tmux; then
        if tmux_new_enough; then
            row tmux "found    $(version_of tmux)"
        else
            row tmux "too old  $(version_of tmux) (needs 3.1+)"
        fi
    else
        row tmux "missing"
    fi
    have_command curl && row curl "found    $(version_of curl)" || row curl "missing"
    if [ "$OS" = "linux" ]; then
        portaudio_present && row portaudio "found" || row portaudio "missing"
    fi
    adsb_installed && row adsb-tui "found" || row adsb-tui "missing"

    check_pyenv
    check_width
    missing_advice
}

# -- step 2 -----------------------------------------------------------------

install_packages() {
    local packages cmd
    step 2 "System packages"

    packages="$(missing_packages)"
    if [ -z "$packages" ]; then
        say "ffmpeg, tmux and PortAudio are all present. Nothing to install."
        return 0
    fi

    if [ "$PKG" = "none" ]; then
        if [ "$OS" = "macos" ]; then
            die "Homebrew is needed to install: $packages
Install it first, then run this again:
  /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\"
See https://brew.sh"
        fi
        die "no supported package manager found (looked for brew, apt-get, dnf, pacman).
Install these with whatever your system uses, then run this again:
  $packages"
    fi

    if [ "$PKG" != "brew" ] && [ "$(id -u)" != "0" ] && [ -z "$SUDO" ]; then
        die "these need root to install, and sudo is not available:
  $packages
Install them as root, then run this again."
    fi

    cmd="$(pkg_install_cmd "$packages")"
    say "Missing: $packages"
    say ""
    say "  $cmd"
    say ""
    case " $packages " in
        *" libportaudio2 "*|*" portaudio "*)
            say "PortAudio is what squelch plays sound through. Without it"
            say "\`import sounddevice\` fails outright and the audio pane cannot"
            say "start -- on macOS the Python wheel carries its own copy, on"
            say "Linux it does not."
            say ""
            ;;
    esac
    confirm "Run that now?" y || die "Nothing installed. Install them yourself and run this again."

    if [ "$PKG" = "apt" ]; then
        # A stale index is the usual reason apt cannot find a package that
        # plainly exists, and it is a confusing failure to hand somebody
        # three steps into an install. Non-fatal: the install itself may
        # still succeed against what is already cached.
        ${SUDO:+$SUDO }apt-get update || warn "apt-get update failed; trying the install anyway."
    fi
    # Word splitting is intended: $cmd is a whole command line.
    # shellcheck disable=SC2086
    if ! $cmd; then
        if [ "$PKG" = "dnf" ]; then
            warn "dnf could not install $packages.
Fedora ships no ffmpeg of its own -- it comes from RPM Fusion:
  sudo dnf install https://mirrors.rpmfusion.org/free/fedora/rpmfusion-free-release-\$(rpm -E %fedora).noarch.rpm"
        fi
        die "installing $packages failed; nothing else was changed."
    fi
}

# -- step 3 -----------------------------------------------------------------

install_uv() {
    step 3 "uv, and the Python it supplies"

    if have_command uv; then
        say "uv $(version_of uv) is already installed."
        return 0
    fi

    say "uv runs everything here, and supplies the Python 3.14 this project"
    say "needs -- there is no system Python involved and nothing to install"
    say "by hand afterwards."
    say ""
    say "  curl -LsSf https://astral.sh/uv/install.sh | INSTALLER_NO_MODIFY_PATH=1 sh"
    say ""
    say "INSTALLER_NO_MODIFY_PATH=1 stops that installer appending to your"
    say "~/.zshrc, ~/.bash_profile and ~/.profile behind your back. Step 5"
    say "asks about your PATH in the open instead."
    say ""
    confirm "Install uv now?" y || die "uv is required; there is no cockpit without it."

    have_command curl || die "curl is needed to fetch uv, and is not installed."
    # (Verified against the installer source: it reads UV_NO_MODIFY_PATH
    # first, then INSTALLER_NO_MODIFY_PATH.)
    curl -LsSf https://astral.sh/uv/install.sh | INSTALLER_NO_MODIFY_PATH=1 sh ||
        die "the uv installer failed; nothing else was changed."
    # The profile is untouched by design, so this process has to put the new
    # uv on its own PATH itself.
    PATH="$PREFIX:$PATH"
    have_command uv || die "uv installed but is still not on PATH; expected it in $PREFIX."
    say "Installed uv $(version_of uv)."
}

# -- step 4 -----------------------------------------------------------------

sync_project() {
    step 4 "Python dependencies"

    have_command uv || die "uv is missing, so there is nothing to sync with."

    say "uv sync downloads the Python 3.14 interpreter if you do not have it,"
    say "creates .venv/ in this repo, and installs the dependencies at the"
    say "versions pinned in uv.lock:"
    say ""
    say "  numpy        the mixer's sum and scale"
    say "  sounddevice  the output stream (PortAudio, from step 2)"
    say "  textual      both terminal UIs"
    say ""
    say "Nothing is installed outside this directory."
    say ""
    confirm "Run uv sync now?" y || die "The Python dependencies are required; stopping here."

    uv sync --project "$REPO" || die "uv sync failed; nothing was wired up."
}

# -- step 5 -----------------------------------------------------------------

# The line appended to a shell profile, and the marker that keeps a second
# run from appending it twice.
PATH_MARKER="# added by kcgx setup.sh"

profile_file() {
    case "$(basename "${SHELL:-/bin/sh}")" in
        zsh)  printf '%s/.zshrc' "$HOME" ;;
        bash) if [ "$OS" = "macos" ]; then printf '%s/.bash_profile' "$HOME"
              else printf '%s/.bashrc' "$HOME"; fi ;;
        fish) printf '%s/fish/config.fish' "${XDG_CONFIG_HOME:-$HOME/.config}" ;;
    esac
}

profile_line() {
    if [ "$(basename "${SHELL:-/bin/sh}")" = "fish" ]; then
        printf 'fish_add_path "%s"' "$PREFIX"
    else
        printf 'export PATH="%s:$PATH"' "$PREFIX"
    fi
}

path_has_prefix() {
    case ":$PATH:" in *":$PREFIX:"*) return 0 ;; *) return 1 ;; esac
}

link_launcher() {
    local target="$REPO/bin/kcgx" link="$PREFIX/kcgx" profile
    step 5 "The launcher on your PATH"

    mkdir -p "$PREFIX"

    if [ -L "$link" ]; then
        # Already ours? Nothing to do. Somebody else's? Never clobber it.
        #
        # A plain string compare against what we would write, deliberately:
        # resolving the link through `cd`/`pwd` inside a test is a command
        # substitution that can fail under `set -e`, and anything that does
        # not match exactly is treated as foreign. Conservative in the safe
        # direction -- the cost of a false "foreign" is one message, the cost
        # of a false "ours" is destroying somebody's launcher.
        if [ "$(readlink "$link")" = "$target" ]; then
            say "Launcher already linked: $link"
        else
            die "$link already exists and points somewhere else.
Remove it yourself if you want setup to manage it."
        fi
    elif [ -e "$link" ]; then
        die "$link already exists and is not a symlink.
Remove it yourself if you want setup to manage it."
    else
        # A symlink rather than a copy: bin/kcgx resolves its own repo root
        # through symlinks, and a copy would look for kcgx.tmux.conf in
        # ~/.local/.
        ln -s "$target" "$link"
        say "Linked $link -> $target"
    fi

    if path_has_prefix; then
        say "$PREFIX is already on your PATH."
        return 0
    fi

    profile="$(profile_file)"
    say ""
    say "$PREFIX is NOT on your PATH."
    say ""
    say "This is not only about typing \`kcgx\`. Ctrl-b a -- the airport"
    say "picker -- is bound to \`display-popup -E \"kcgx go\"\`, which resolves"
    say "kcgx by name through the tmux server's own environment. Without it"
    say "the cockpit opens fine and the picker silently does nothing, which"
    say "is the least debuggable way for this to be broken."
    say ""
    say "  $(profile_line)"
    say ""

    if [ -z "$profile" ]; then
        warn "your shell (${SHELL:-unknown}) has no profile setup.sh knows how to
edit. Add the line above to it yourself."
        return 0
    fi

    say "That line can go in $profile."
    if ! confirm "Append it to $profile?" y; then
        say ""
        say "Not appended. Add it yourself, or the picker will not work."
        return 0
    fi

    if [ -f "$profile" ] && grep -qF "$PATH_MARKER" "$profile"; then
        say "$profile already carries it; leaving it alone."
        return 0
    fi
    if [ -f "$profile" ]; then
        cp "$profile" "$profile.kcgx-backup" ||
            die "could not back up $profile; refusing to edit it."
        say "Backed up $profile -> $profile.kcgx-backup"
    fi
    mkdir -p "$(dirname "$profile")"
    printf '\n%s\n%s\n' "$PATH_MARKER" "$(profile_line)" >> "$profile"
    say "Appended to $profile."
    # This shell, so step 9's checks and the launch below see it too.
    PATH="$PREFIX:$PATH"
    say ""
    say "Already-running tmux servers captured their environment when they"
    say "started, so restart them (kcgx stop) before Ctrl-b a will find it."
}

# -- step 6 -----------------------------------------------------------------

install_adsb() {
    step 6 "adsb-tui, the radar pane"

    if adsb_installed; then
        say "adsb-tui is already installed: $(adsb_binary)"
        return 0
    fi

    if [ "$PLATFORM" = "unsupported" ]; then
        die "adsb-tui publishes no release for $(uname -s) $(uname -m).
Published: macos-arm64, macos-x64, linux-x64.
The cockpit needs it. You can build it yourself from
https://github.com/j4v3l/ADS-B_TUI (it is Rust; expect ~4 GB of toolchain
for a 3 MB binary), put the result in $PREFIX, and run this again."
    fi

    say "The radar pane is adsb-tui, from another repository:"
    say ""
    say "  https://github.com/j4v3l/ADS-B_TUI  $ADSB_VERSION  ($PLATFORM)"
    say ""
    say "  Licence: ADS-B TUI Non-Commercial License -- NOT OSI-approved."
    say "  This downloads the published release into $PREFIX."
    say "  Nothing is built from source and cargo is never invoked."
    say ""
    confirm "Download adsb-tui now?" y ||
        die "adsb-tui is required for the cockpit; stopping here."

    have_command curl || die "curl is needed to fetch adsb-tui, and is not installed."
    mkdir -p "$PREFIX"
    curl -fL --progress-bar "$RELEASE_URL/$ADSB_VERSION/adsb-tui-$PLATFORM.tar.gz" \
        | tar xzf - -C "$PREFIX" ||
        die "could not download adsb-tui from
  $RELEASE_URL/$ADSB_VERSION/adsb-tui-$PLATFORM.tar.gz
Check your connection and run this again."
    chmod +x "$PREFIX/adsb-tui" 2>/dev/null || true

    # A tar that unpacked something other than the binary exits 0 just like a
    # good one, so "the download worked" is not the same claim as "adsb-tui is
    # installed". Only make the one that is true.
    [ -x "$PREFIX/adsb-tui" ] ||
        die "the adsb-tui archive held no usable binary at $PREFIX/adsb-tui."
    say "Installed $PREFIX/adsb-tui"
}

# -- step 7 -----------------------------------------------------------------

# adsb-tui defaults to http://adsb.local/data/aircraft.json -- a receiver on
# your own network. Without one the radar is empty, so point it at a public
# aggregator. 2 s because both free providers rate-limit near 1 req/s and
# api.adsb.lol returned 429 at that rate where api.airplanes.live did not.
write_adsb_config() {
    step 7 "Where the radar gets its aircraft"

    if [ -e "$ADSB_CONFIG" ]; then
        say "$ADSB_CONFIG already exists; leaving it alone."
        return 0
    fi

    say "adsb-tui looks for a receiver on your own network by default"
    say "(http://adsb.local/data/aircraft.json). Without one the radar stays"
    say "empty, so setup can point it at a public aggregator instead -- no"
    say "API key, no receiver hardware:"
    say ""
    say "  url_template = \"https://api.airplanes.live/v2/point/{lat}/{lon}/{range_nm}\""
    say "  refresh_secs = 2"
    say ""
    say "kcgx fills in {lat}/{lon} per launch from the airport you pick."
    say ""
    if ! confirm "Write $ADSB_CONFIG?" y; then
        say "Not written. The radar pane will be empty until you configure it."
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

# -- step 8 -----------------------------------------------------------------

# LiveATC fronts its listing with Cloudflare and refuses roughly three
# requests in four. squelch handles that by caching the result for a week,
# so the launch you actually do makes no request at all -- but the *first*
# launch at an airport has no cache to read, tries eight times, and then
# opens the single configured feed. At the default airport that reads as
# "squelch could only find KPDX tower", with no sign that eleven other feeds
# exist and nothing said about why.
#
# Filling the cache here is the fix, because here is where waiting is free.
# Nobody is looking at a UI, so it can try twenty times.
#
# Not fatal: the feed list is a week-long cache, not a dependency, and
# LiveATC being unreachable at this moment is no reason to refuse to install
# an airport radar and a launcher.
warm_feed_cache() {
    local icao
    step 8 "The LiveATC feed list"

    icao="$(uv run --project "$REPO" python -c '
from squelch.config import load_config
print(load_config().icao)
' 2>/dev/null || true)"
    if [ -z "$icao" ]; then
        warn "could not work out which airport to prefetch; skipping."
        return 0
    fi

    say "squelch opens every feed an airport publishes, which means asking"
    say "LiveATC for the list. That request is behind Cloudflare and is"
    say "refused about three times in four, so squelch caches the answer for"
    say "a week -- but the first launch at a new airport has nothing cached,"
    say "gives up after eight tries, and opens one feed instead of twelve."
    say ""
    say "Fetching it now avoids that: out here it can retry twenty times and"
    say "nobody is waiting. Takes a minute or two if it is being refused."
    say ""
    if ! confirm "Fetch the feed list for $icao now?" y; then
        say "Skipped. Run \`uv run --project '$REPO' squelch --refresh-feeds\`"
        say "later, or just start squelch and press f if it opens short."
        return 0
    fi

    uv run --project "$REPO" squelch --refresh-feeds ||
        warn "could not cache the feed list; squelch will try again on launch."
}

# -- step 9 -----------------------------------------------------------------

VERIFY_FAILED=0
VERIFY_WARNED=0

ok()    { vrow "$1" "ok" "${2:-}"; }
bad()   { vrow "$1" "FAIL" "${2:-}"; VERIFY_FAILED=$((VERIFY_FAILED + 1)); }
meh()   { vrow "$1" "warn" "${2:-}"; VERIFY_WARNED=$((VERIFY_WARNED + 1)); }

# Any HTTP response at all proves the host is reachable. LiveATC fronts its
# listing with Cloudflare and refuses roughly three requests in four, so
# demanding a 200 here would report a working install as broken.
reachable() {  # $1=url
    local code
    code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 8 "$1" 2>/dev/null || true)"
    [ -n "$code" ] && [ "$code" != "000" ]
}

verify() {
    local version devices cols
    step 9 "Checking it works"

    say "Running each moving part rather than checking that a file exists --"
    say "an install that reports success and then opens a broken pane has"
    say "not succeeded."
    say ""

    version="$(version_of ffmpeg || true)"
    if [ -n "$version" ]; then
        ok "ffmpeg" "$version"
    else
        bad "ffmpeg" "not runnable; squelch decodes every feed with it"
    fi

    if tmux_new_enough; then
        ok "tmux" "$(tmux_version)"
    else
        bad "tmux" "missing or older than 3.1; the cockpit is built with it"
    fi

    # Runs the binary. This is the check that catches an archive for the
    # wrong platform: a Mach-O binary on Linux is present, executable, and
    # cannot run, and every file-based test says it is fine.
    if "$(adsb_binary)" --help >/dev/null 2>&1; then
        ok "adsb-tui" "$(adsb_binary)"
    else
        bad "adsb-tui" "missing, or will not run on this machine"
    fi

    if [ -e "$ADSB_CONFIG" ]; then
        ok "radar config" "$ADSB_CONFIG"
    else
        meh "radar config" "absent; the radar will have nowhere to read from"
    fi

    # The one check that proves step 2 and step 4 landed together: sounddevice
    # imports only if PortAudio is installed *and* the venv is synced.
    if uv run --project "$REPO" python -c 'import numpy, sounddevice, textual' \
        >/dev/null 2>&1; then
        ok "python deps" "numpy, sounddevice, textual"
    else
        bad "python deps" "import failed -- run: uv run --project '$REPO' python -c 'import sounddevice'"
    fi

    if uv run --project "$REPO" squelch --help >/dev/null 2>&1; then
        ok "squelch" "starts"
    else
        bad "squelch" "will not start"
    fi

    # A machine with PortAudio but no output device is a real state (headless
    # boxes, containers, an unplugged dock) and not one setup can fix, so it
    # warns rather than blocking a cockpit whose radar and meters still work.
    devices="$(uv run --project "$REPO" python -c '
import sounddevice
print(sum(1 for d in sounddevice.query_devices() if d["max_output_channels"] > 0))
' 2>/dev/null || true)"
    case "$devices" in
        ''|0)   meh "audio output" "no output device; meters will run, nothing will be audible" ;;
        *)      ok  "audio output" "$devices device(s)" ;;
    esac

    if have_command kcgx; then
        ok "kcgx on PATH" "$(command -v kcgx)"
    else
        meh "kcgx on PATH" "the Ctrl-b a picker will do nothing (step 5)"
    fi

    if [ -z "${KCGX_SETUP_SKIP_NET:-}" ]; then
        if reachable "https://www.liveatc.net/"; then
            ok "liveatc.net" "reachable"
        else
            meh "liveatc.net" "unreachable; feeds will not load"
        fi
        if reachable "https://api.airplanes.live/v2/point/45.6/-122.6/5"; then
            ok "airplanes.live" "reachable"
        else
            meh "airplanes.live" "unreachable; the radar will stay empty"
        fi
    fi

    cols="$(terminal_cols)"
    case "$cols" in
        ''|*[!0-9]*) ;;
        *)
            if [ "$cols" -lt "$MIN_COLS" ]; then
                meh "terminal width" "$cols columns; kcgx refuses below $MIN_COLS"
            else
                ok "terminal width" "$cols columns"
            fi
            ;;
    esac

    say ""
    if [ "$VERIFY_FAILED" -gt 0 ]; then
        die "$VERIFY_FAILED check(s) failed. Fix those and run this again --
opening the cockpit now would only show you the same failure with fewer
words."
    fi
    if [ "$VERIFY_WARNED" -gt 0 ]; then
        say "$VERIFY_WARNED warning(s) above. Nothing there stops the cockpit"
        say "opening, but the parts named will not work until you deal with"
        say "them."
    else
        say "Everything checks out."
    fi
}

# -- entry ------------------------------------------------------------------

usage() {
    say "Usage: ./setup.sh [--check | --verify | --yes | --help]"
    say ""
    say "  (no arguments)  install everything kcgx needs and open the cockpit,"
    say "                  asking before each step that changes anything"
    say "  --check         print what you have and what is missing, then exit"
    say "  --verify        run the step 9 checks against this machine, then exit"
    say "  --yes           take every prompt's default (including appending to"
    say "                  your shell profile); for unattended installs"
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
    --yes)     KCGX_SETUP_YES=1 ;;
    --check)   preflight; say ""; exit 0 ;;
    --verify)  resolve_platform; verify; exit 0 ;;
    --help|-h) usage; exit 0 ;;
    *)
        warn "unknown argument: $1"
        usage >&2
        exit 2
        ;;
esac

say "kcgx setup"
say ""
say "$STEPS steps. Each one asks before it changes anything, and running this"
say "again is safe -- every step is idempotent."

preflight
install_packages
install_uv
sync_project
link_launcher
install_adsb
write_adsb_config
warm_feed_cache
verify

say ""
say "Setup complete. Opening the cockpit..."

if [ -n "${KCGX_SETUP_NO_LAUNCH:-}" ]; then
    exit 0
fi

# By absolute path, not by name: a PATH the user has not reloaded yet must
# not stop the cockpit opening on this first run.
exec "$REPO/bin/kcgx"
