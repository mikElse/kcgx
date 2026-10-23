#!/usr/bin/env bash
# setup.sh — install everything kcgx needs, prove it works, open the cockpit.
#
# Seven steps. Each announces itself, each asks before changing anything, and
# each is idempotent -- so the second run, the one you do when you think
# something went wrong, ends exactly where the first did.
#
# The contract is that reaching the end means the cockpit works: every
# dependency installed, and step 7 having actually started the server and
# asked it for the page and its WebSocket, rather than having checked that a
# file exists. A setup script that finishes and leaves you with a broken
# page has not finished.
#
# Phase E of the web cockpit (2026-10-22) took out tmux, adsb-tui and its
# config, and the terminal width check: the cockpit is a page in your
# browser now, and the radar is the server's own.
#
# Test seams (all default to production behaviour when unset):
#   KCGX_SETUP_YES         non-empty takes every prompt's default answer
#   KCGX_SETUP_NO_LAUNCH   non-empty stops before exec'ing the launcher
#   KCGX_SETUP_OS          override the detected operating system
#   KCGX_SETUP_PKG         override the detected package manager
#   KCGX_SETUP_SKIP_NET    non-empty skips the two reachability probes

set -euo pipefail

REPO="$(cd -P "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Set by resolve_platform, read by nearly every step. Declared here so the
# ordering is explicit rather than a happy accident of which step runs first.
OS=""        # macos | linux | unsupported
PKG=""       # brew | apt | dnf | pacman | none
SUDO=""      # "" when root or on brew, else "sudo"

PREFIX="$HOME/.local/bin"
# adsb.lol 403s a request that carries no User-Agent. Step 7's probe sends the
# one the server's radar sends (kcgx.radar.DEFAULT_UA): a check that proves a
# different request than the app sends proves nothing. The two are literals
# in two languages, and tests/test_setup.py fails the moment they disagree.
ADSB_UA="kcgx/0.1 (+https://github.com/mikElse/kcgx)"
STEPS=7

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
# Any processor will do. Setup used to key a release download on the machine
# (adsb-tui published macOS and x86_64 Linux binaries only), which made ARM
# Linux a stopping point; with nothing to download there is nothing to match.

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

# One place that settles all three, so `--verify` and a full run cannot
# disagree about what machine they are on.
resolve_platform() {
    OS="${KCGX_SETUP_OS:-$(detect_os)}"
    PKG="${KCGX_SETUP_PKG:-$(detect_pkg)}"
    detect_sudo
}

# Homebrew installs as the invoking user and refuses to run under sudo.
detect_sudo() {
    [ "$PKG" = "brew" ] && return 0
    [ "$(id -u)" = "0" ] && return 0
    if have_command sudo; then SUDO="sudo"; fi
    # Explicit: the `&&` form this replaced made a missing sudo the
    # function's own exit status, and under `set -e` an unguarded call
    # then killed the script after the banner and before step 1 -- no
    # message, exit 1. install_packages owns that case (it dies with
    # something to act on), and can only own it if we return here.
    return 0
}

# $1 = ffmpeg | portaudio. Empty output means "not a package here".
pkg_name() {
    case "$1" in
        ffmpeg) printf '%s' "$1" ;;
        portaudio)
            # Only Linux. The sounddevice wheel bundles its own PortAudio on
            # macOS, which is why this dependency stayed invisible for so
            # long: on Linux the same wheel ships no library at all and
            # `import sounddevice` dies with "PortAudio library not found"
            # before the server can play anything.
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
# fires on output long enough to still be flowing, which `ffmpeg -version`
# is.

# The install decision only. The truth is `import sounddevice` in step 7:
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
        curl)   curl --version 2>/dev/null | awk 'NR == 1 { v = $2 } END { print v }' ;;
    esac
}

# Everything still missing, as a package list for the detected manager.
missing_packages() {
    local needed=""
    have_command ffmpeg  || needed="$needed $(pkg_name ffmpeg)"
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

# What to do about whatever the table reported as missing. It belongs beside
# the finding rather than only in the steps that follow: `--check` exits
# straight after this, so for anyone reading the table first -- which is the
# point of --check -- a remedy printed three steps later is no remedy. A table
# naming tools and no way to get any of them restates the "which
# prerequisites do I need?" problem instead of answering it.
missing_advice() {
    local packages
    packages="$(missing_packages)"
    [ -z "$packages" ] && have_command uv && return 0

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
    say ""
    say "Or run ./setup.sh, which does all of it, asking before each step."
}

# -- step 1 -----------------------------------------------------------------

preflight() {
    resolve_platform
    step 1 "What you have"

    row "platform" "$OS $(uname -m)"
    row "packages" "$PKG"
    say ""
    have_command uv     && row uv     "found    $(version_of uv)"     || row uv     "missing"
    have_command ffmpeg && row ffmpeg "found    $(version_of ffmpeg)" || row ffmpeg "missing"
    have_command curl   && row curl   "found    $(version_of curl)"   || row curl   "missing"
    if [ "$OS" = "linux" ]; then
        portaudio_present && row portaudio "found" || row portaudio "missing"
    fi

    check_pyenv
    missing_advice
}

# -- step 2 -----------------------------------------------------------------

install_packages() {
    local packages cmd
    step 2 "System packages"

    packages="$(missing_packages)"
    if [ -z "$packages" ]; then
        say "ffmpeg and PortAudio are both present. Nothing to install."
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
            say "PortAudio is what the cockpit plays sound through. Without it"
            say "\`import sounddevice\` fails outright and nothing can be heard"
            say "-- on macOS the Python wheel carries its own copy, on Linux it"
            say "does not."
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
    say "  starlette    the cockpit's local web server"
    say "  uvicorn      what runs it"
    say "  websockets   the page's live connection"
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
        # through symlinks, and a copy would look for the project in
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
    say "Without it the cockpit still starts as $REPO/bin/kcgx, but"
    say "not as plain \`kcgx\` from any terminal."
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
        say "Not appended. Add it yourself to type plain \`kcgx\`."
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
    # This shell, so step 7's checks and the launch below see it too.
    PATH="$PREFIX:$PATH"
    say "Open a new terminal (or source $profile) for it to reach other shells."
}

# -- step 6 -----------------------------------------------------------------

# LiveATC fronts its listing with Cloudflare and refuses roughly three
# requests in four. kcgx handles that by caching the result for a week, so
# the start you actually do makes no request at all -- but the *first* start
# at an airport has no cache to read, tries eight times, and then opens the
# single configured feed. At the default airport that reads as "kcgx could
# only find KPDX tower", with no sign that eleven other feeds exist and
# nothing said about why.
#
# Filling the cache here is the fix, because here is where waiting is free.
# Nobody is looking at a page, so it can try twenty times.
#
# Not fatal: the feed list is a week-long cache, not a dependency, and
# LiveATC being unreachable at this moment is no reason to refuse to install
# the cockpit.
warm_feed_cache() {
    local icao
    step 6 "The LiveATC feed list"

    icao="$(uv run --project "$REPO" python -c '
from kcgx.state import current_icao
print(current_icao(known=lambda icao: True, warn=lambda line: None))
' 2>/dev/null || true)"
    if [ -z "$icao" ]; then
        warn "could not work out which airport to prefetch; skipping."
        return 0
    fi

    say "The cockpit opens every feed an airport publishes, which means asking"
    say "LiveATC for the list. That request is behind Cloudflare and is"
    say "refused about three times in four, so kcgx caches the answer for a"
    say "week -- but the first start at a new airport has nothing cached,"
    say "gives up after eight tries, and opens one feed instead of twelve."
    say ""
    say "Fetching it now avoids that: out here it can retry twenty times and"
    say "nobody is waiting. Takes a minute or two if it is being refused."
    say ""
    if ! confirm "Fetch the feed list for $icao now?" y; then
        say "Skipped. Run \`uv run --project '$REPO' kcgx-web --refresh-feeds\`"
        say "later, or just start kcgx and open FEEDS if it opens short."
        return 0
    fi

    uv run --project "$REPO" kcgx-web --refresh-feeds --icao "$icao" ||
        warn "could not cache the feed list; kcgx will try again when it starts."
}

# -- step 7 -----------------------------------------------------------------

VERIFY_FAILED=0
VERIFY_WARNED=0

ok()    { vrow "$1" "ok" "${2:-}"; }
bad()   { vrow "$1" "FAIL" "${2:-}"; VERIFY_FAILED=$((VERIFY_FAILED + 1)); }
meh()   { vrow "$1" "warn" "${2:-}"; VERIFY_WARNED=$((VERIFY_WARNED + 1)); }

# `reachable` only proves that something answered, and a 403 answers. Both
# providers refuse a request shape rather than going down, so the checks that
# matter send exactly what the app sends and insist on a 200. Reporting
# "adsb.lol reachable" over a radar stuck on ERR 403 is how this once went
# unnoticed for a fortnight.
serves() {  # $1=url $2=user-agent (optional)
    local code
    if [ -n "${2:-}" ]; then
        code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 8 \
            -A "$2" "$1" 2>/dev/null || true)"
    else
        code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 8 \
            "$1" 2>/dev/null || true)"
    fi
    [ "$code" = "200" ]
}

verify() {
    local version devices check
    step 7 "Checking it works"

    say "Running each moving part rather than checking that a file exists --"
    say "an install that reports success and then opens a broken page has"
    say "not succeeded."
    say ""

    version="$(version_of ffmpeg || true)"
    if [ -n "$version" ]; then
        ok "ffmpeg" "$version"
    else
        bad "ffmpeg" "not runnable; the cockpit decodes every feed with it"
    fi

    # The one check that proves step 2 and step 4 landed together: sounddevice
    # imports only if PortAudio is installed *and* the venv is synced.
    if uv run --project "$REPO" python -c 'import numpy, sounddevice, starlette, uvicorn, websockets' \
        >/dev/null 2>&1; then
        ok "python deps" "numpy, sounddevice, starlette, uvicorn, websockets"
    else
        bad "python deps" "import failed -- run: uv run --project '$REPO' python -c 'import sounddevice'"
    fi

    # Starts the real server, as the demo (no network, no audio, nothing
    # remembered), on a free port, and asks it for what a page asks for: its
    # health, the page, and the WebSocket's first frame; then stops it.
    # kcgx.selfcheck prints a row per check and a last line saying how it went.
    check="$(uv run --project "$REPO" python -m kcgx.selfcheck 2>&1 || true)"
    case "$check" in
        *"selfcheck ok"*)
            ok "server" "health, page and WebSocket answer"
            ;;
        *)
            bad "server" "would not serve the cockpit:"
            printf '%s\n' "$check" | sed -n '/FAIL/s/^/      /p'
            ;;
    esac

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
        meh "kcgx on PATH" "start it as $REPO/bin/kcgx until it is (step 5)"
    fi

    if [ -z "${KCGX_SETUP_SKIP_NET:-}" ]; then
        # /play/*.pls is the path audio actually comes from, and it is not
        # the one behind the Cloudflare challenge -- so it is the one worth
        # checking. The listing at /search/ refuses most requests even when
        # everything is working; failing the install over it would be noise.
        if serves "https://www.liveatc.net/play/kpdx_twr.pls"; then
            ok "liveatc.net" "streaming reachable"
        else
            meh "liveatc.net" "refused /play/; feeds will not play"
        fi
        if serves "https://api.adsb.lol/v2/point/45.6/-122.6/5" "$ADSB_UA"; then
            ok "adsb.lol" "serving aircraft"
        else
            meh "adsb.lol" "refused the request; the radar will stay empty"
        fi
    fi

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
    say "  --verify        run the step 7 checks against this machine, then exit"
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
warm_feed_cache
verify

say ""
say "Setup complete. Opening the cockpit in your browser..."

if [ -n "${KCGX_SETUP_NO_LAUNCH:-}" ]; then
    exit 0
fi

# By absolute path, not by name: a PATH the user has not reloaded yet must
# not stop the cockpit opening on this first run. bin/kcgx starts the server
# in the background and opens the page.
exec "$REPO/bin/kcgx"
