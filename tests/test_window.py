"""KCGX.app: the cockpit's own window on macOS (macos/).

Two halves. The first drives `macos/build.sh` with a fake `swiftc` and a
fake `codesign`, so it runs anywhere and compiles nothing. The second builds
the real app, on a Mac with the command line tools, and asks its binary
what it would show for a `kcgx://` link; elsewhere it skips.

Nothing here opens a window, registers the app with the system, starts a
server or writes outside the test's own folder: the app is only ever built
into it, and `--check` answers and exits before the app starts.
"""

from __future__ import annotations

import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
BUILD = REPO / "macos" / "build.sh"
TEMPLATE = REPO / "macos" / "Info.plist.in"

# Everything build.sh itself runs, beside swiftc and codesign.
TOOLS = ("bash", "env", "dirname", "basename", "mkdir", "rm", "mv", "sed", "grep", "uname")

# Writes the "binary" where -o says, and records how it was asked.
FAKE_SWIFTC = """#!/bin/sh
printf '%s\\n' "$*" >> "$CALLS/swiftc"
while [ $# -gt 0 ]; do
    if [ "$1" = "-o" ]; then printf 'compiled\\n' > "$2"; fi
    shift
done
"""
FAKE_CODESIGN = """#!/bin/sh
printf '%s\\n' "$*" >> "$CALLS/codesign"
"""
FAILS = """#!/bin/sh
echo "error: no such module 'Cocoa'" >&2
exit 1
"""


def tools(tmp_path, **scripts) -> Path:
    """A folder to be the whole PATH: the real tools build.sh runs, and
    `scripts` (name to shell source) for the fakes. Anything not named is
    absent, which is how "no swiftc" is said."""
    folder = tmp_path / "bin"
    folder.mkdir()
    for tool in TOOLS:
        (folder / tool).symlink_to(shutil.which(tool))
    for name, source in scripts.items():
        (folder / name).write_text(source)
        (folder / name).chmod(0o755)
    return folder


def build(tmp_path, *arguments, path, home=None, cwd=None):
    calls = tmp_path / "calls"
    calls.mkdir(exist_ok=True)
    env = {"PATH": str(path), "HOME": str(home or tmp_path / "home"), "CALLS": str(calls)}
    return subprocess.run(
        [shutil.which("bash"), str(BUILD), *arguments], env=env, cwd=cwd or tmp_path,
        capture_output=True, text=True, timeout=60,
    )


def said(tmp_path, tool) -> list[str]:
    return (tmp_path / "calls" / tool).read_text().splitlines()


def plist(app: Path) -> dict:
    return plistlib.loads((app / "Contents" / "Info.plist").read_bytes())


# -- the bundle's metadata -------------------------------------------------------


def test_the_bundle_is_kcgx_and_answers_the_kcgx_scheme():
    info = plistlib.loads(TEMPLATE.read_bytes())
    assert info["CFBundleIdentifier"] == "com.kcgx.cockpit"
    assert info["CFBundleName"] == "KCGX"
    assert info["CFBundleExecutable"] == "KCGX"
    assert info["CFBundlePackageType"] == "APPL"
    assert [kind["CFBundleURLSchemes"] for kind in info["CFBundleURLTypes"]] == [["kcgx"]]


def test_the_bundle_may_load_plain_http_from_this_machine_and_nowhere_else():
    info = plistlib.loads(TEMPLATE.read_bytes())
    assert info["NSAppTransportSecurity"] == {"NSAllowsLocalNetworking": True}


def test_the_repo_and_the_path_are_left_for_the_build_to_fill():
    info = plistlib.loads(TEMPLATE.read_bytes())
    assert (info["KCGXRepo"], info["KCGXPath"]) == ("@REPO@", "@PATH@")


# -- build.sh, with nothing compiled ---------------------------------------------


def test_build_assembles_a_signed_bundle_at_the_destination(tmp_path):
    app = tmp_path / "out" / "KCGX.app"
    path = tools(tmp_path, swiftc=FAKE_SWIFTC, codesign=FAKE_CODESIGN)
    result = build(tmp_path, str(app), path=path)
    assert result.returncode == 0, result.stderr
    assert (app / "Contents" / "MacOS" / "KCGX").read_text() == "compiled\n"
    assert plist(app)["CFBundleIdentifier"] == "com.kcgx.cockpit"
    assert sorted(p.name for p in app.parent.iterdir()) == ["KCGX.app"]  # nothing left beside it

    [compiled] = said(tmp_path, "swiftc")
    assert str(REPO / "macos" / "KCGXWindow.swift") in compiled
    assert "-framework Cocoa" in compiled and "-framework WebKit" in compiled and "-O" in compiled.split()
    [signed] = said(tmp_path, "codesign")
    assert signed.startswith("--force --sign - ") and signed.endswith("KCGX.app")


def test_build_writes_where_the_repo_is_and_the_path_it_was_built_with(tmp_path):
    app = tmp_path / "KCGX.app"
    path = tools(tmp_path, swiftc=FAKE_SWIFTC, codesign=FAKE_CODESIGN)
    assert build(tmp_path, str(app), path=path).returncode == 0
    assert plist(app)["KCGXRepo"] == str(REPO)
    assert plist(app)["KCGXPath"] == str(path)


def test_a_path_with_awkward_characters_reaches_the_bundle_whole(tmp_path):
    # Characters that mean something to sed, to XML, or to both.
    app = tmp_path / "KCGX.app"
    awkward = f"{tools(tmp_path, swiftc=FAKE_SWIFTC, codesign=FAKE_CODESIGN)}:/opt/R&D|x/<bin>:/a\\b/@PATH@"
    assert build(tmp_path, str(app), path=awkward).returncode == 0
    assert plist(app)["KCGXPath"] == awkward
    assert plist(app)["KCGXRepo"] == str(REPO)


def test_build_goes_to_applications_in_the_home_folder_unless_told(tmp_path):
    home = tmp_path / "somebody"
    path = tools(tmp_path, swiftc=FAKE_SWIFTC, codesign=FAKE_CODESIGN)
    result = build(tmp_path, path=path, home=home)
    assert result.returncode == 0, result.stderr
    assert (home / "Applications" / "KCGX.app" / "Contents" / "MacOS" / "KCGX").exists()


def test_a_rebuild_replaces_the_whole_bundle(tmp_path):
    app = tmp_path / "KCGX.app"
    path = tools(tmp_path, swiftc=FAKE_SWIFTC, codesign=FAKE_CODESIGN)
    assert build(tmp_path, str(app), path=path).returncode == 0
    stale = app / "Contents" / "Resources" / "old.txt"
    stale.parent.mkdir()
    stale.write_text("from the build before")
    result = build(tmp_path, str(app), path=path)
    assert result.returncode == 0, result.stderr
    assert not stale.exists()
    assert (app / "Contents" / "MacOS" / "KCGX").exists()
    assert len(said(tmp_path, "swiftc")) == 2


def test_a_destination_written_as_a_folder_is_the_app_all_the_same(tmp_path):
    app = tmp_path / "out" / "KCGX.app"
    path = tools(tmp_path, swiftc=FAKE_SWIFTC, codesign=FAKE_CODESIGN)
    for _ in range(2):  # a first build, and one over it
        result = build(tmp_path, f"{app}/", path=path)
        assert result.returncode == 0, result.stderr
    assert (app / "Contents" / "MacOS" / "KCGX").exists()
    assert sorted(p.name for p in app.parent.iterdir()) == ["KCGX.app"]


def earlier(app: Path, identifier: str = "com.kcgx.cockpit") -> Path:
    """A bundle at `app` from a build before, with `identifier` in its
    Info.plist; returns its binary."""
    binary = app / "Contents" / "MacOS" / "KCGX"
    binary.parent.mkdir(parents=True)
    binary.write_text("the build before")
    (app / "Contents" / "Info.plist").write_bytes(plistlib.dumps({"CFBundleIdentifier": identifier}))
    return binary


def test_a_build_that_fails_says_so_and_leaves_the_app_that_was_there(tmp_path):
    app = tmp_path / "out" / "KCGX.app"
    binary = earlier(app)
    result = build(tmp_path, str(app), path=tools(tmp_path, swiftc=FAILS, codesign=FAKE_CODESIGN))
    assert result.returncode != 0
    assert "no such module" in result.stderr
    assert binary.read_text() == "the build before"
    assert sorted(p.name for p in app.parent.iterdir()) == ["KCGX.app"]  # and nothing half built


def kept(folder: Path) -> list[str]:
    return sorted(str(p.relative_to(folder)) for p in folder.rglob("*") if p.is_file())


@pytest.mark.parametrize("written", ["Applications", "Applications/", "Applications//", "Documents/", "."])
def test_a_folder_given_as_the_destination_is_refused_and_left_alone(tmp_path, written):
    # The destination is the app itself. `build.sh ~/Applications` is an easy
    # slip, and build.sh replaces whatever is at its destination.
    home = tmp_path / "home"
    (home / "Applications" / "Other.app" / "Contents").mkdir(parents=True)
    (home / "Applications" / "Other.app" / "Contents" / "Info.plist").write_text("another app")
    (home / "Documents").mkdir()
    (home / "Documents" / "thesis.txt").write_text("years of work")
    before = kept(home)
    path = tools(tmp_path, swiftc=FAKE_SWIFTC, codesign=FAKE_CODESIGN)
    # Not joined by pathlib, which would tidy the trailing slash away.
    result = build(tmp_path, written if written == "." else f"{home}/{written}", path=path, home=home, cwd=home)
    assert result.returncode != 0
    assert ".app" in result.stderr and "built" not in result.stdout
    assert kept(home) == before
    assert sorted(p.name for p in home.iterdir()) == ["Applications", "Documents"]  # nothing half built
    assert not (tmp_path / "calls" / "swiftc").exists()  # nothing was compiled


def test_an_app_that_is_not_this_one_is_refused_and_left_alone(tmp_path):
    # Somebody else's KCGX.app, or anything else that happens to be there.
    path = tools(tmp_path, swiftc=FAKE_SWIFTC, codesign=FAKE_CODESIGN)
    another = tmp_path / "another" / "KCGX.app"
    binary = earlier(another, "com.example.kcgx")
    folder = tmp_path / "folder" / "KCGX.app"
    folder.mkdir(parents=True)
    (folder / "notes.txt").write_text("not an app at all")
    file = tmp_path / "file" / "KCGX.app"
    file.parent.mkdir()
    file.write_text("a file by that name")
    for destination in (another, folder, file):
        result = build(tmp_path, str(destination), path=path)
        assert result.returncode != 0, destination
        assert "com.kcgx.cockpit" in result.stderr and "built" not in result.stdout
        assert sorted(p.name for p in destination.parent.iterdir()) == ["KCGX.app"]
    assert binary.read_text() == "the build before"
    assert plist(another)["CFBundleIdentifier"] == "com.example.kcgx"
    assert (folder / "notes.txt").read_text() == "not an app at all"
    assert file.read_text() == "a file by that name"
    assert not (tmp_path / "calls" / "swiftc").exists()


def test_the_real_template_marks_a_bundle_as_one_a_rebuild_may_replace():
    # build.sh knows its own bundles by this line of their Info.plist.
    assert "<string>com.kcgx.cockpit</string>" in TEMPLATE.read_text()


def test_a_bundle_that_cannot_be_signed_is_not_put_in_place(tmp_path):
    app = tmp_path / "out" / "KCGX.app"
    result = build(tmp_path, str(app), path=tools(tmp_path, swiftc=FAKE_SWIFTC, codesign=FAILS))
    assert result.returncode != 0
    assert "no such module" in result.stderr  # codesign's own words, which a good build keeps quiet
    assert list(app.parent.iterdir()) == []


def test_without_swiftc_build_says_what_is_missing_and_makes_nothing(tmp_path):
    app = tmp_path / "out" / "KCGX.app"
    result = build(tmp_path, str(app), path=tools(tmp_path, codesign=FAKE_CODESIGN))
    assert result.returncode != 0
    assert "swiftc" in result.stderr and "xcode-select --install" in result.stderr
    assert not app.exists() and not app.parent.exists()


# -- the real app ----------------------------------------------------------------


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    """KCGX.app as build.sh really makes it, in the tests' own folder."""
    if sys.platform != "darwin" or not shutil.which("swiftc") or not shutil.which("codesign"):
        pytest.skip("KCGX.app is built with swiftc and codesign, on a Mac")
    destination = tmp_path_factory.mktemp("window") / "KCGX.app"
    result = subprocess.run(
        [shutil.which("bash"), str(BUILD), str(destination)], capture_output=True, text=True, timeout=300,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "warning:" not in result.stdout + result.stderr, result.stdout + result.stderr
    return destination


def check(app, link):
    """What the app would show for `link`: the page, or None if it refuses."""
    result = subprocess.run(
        [str(app / "Contents" / "MacOS" / "KCGX"), "--check", link], capture_output=True, text=True, timeout=30,
    )
    if result.returncode == 0:
        return result.stdout.strip()
    assert result.stdout == "" and result.stderr.strip() == "refused"
    return None


def test_the_real_bundle_is_signed_and_whole(app):
    assert subprocess.run(["codesign", "--verify", "--strict", str(app)], capture_output=True).returncode == 0
    info = plist(app)
    assert info["KCGXRepo"] == str(REPO)
    assert (app / "Contents" / "MacOS" / info["CFBundleExecutable"]).is_file()


@pytest.mark.parametrize("link, page", [
    ("kcgx://show?port=8473", "http://127.0.0.1:8473/"),
    ("kcgx://show?port=8473&fragment=airport", "http://127.0.0.1:8473/#airport"),
    ("kcgx://show?port=8473&fragment=airport%3Dseattle", "http://127.0.0.1:8473/#airport=seattle"),
    # `kcgx go new york`: the page's own fragment is airport=new%20york.
    ("kcgx://show?port=8473&fragment=airport%3Dnew%2520york", "http://127.0.0.1:8473/#airport=new%20york"),
    ("kcgx://show?fragment=airport&port=1024", "http://127.0.0.1:1024/#airport"),
    ("kcgx://show?port=65535", "http://127.0.0.1:65535/"),
    ("KCGX://SHOW?port=8473", "http://127.0.0.1:8473/"),
])
def test_a_link_shows_a_port_on_this_machine_and_a_fragment(app, link, page):
    assert check(app, link) == page


@pytest.mark.parametrize("page", [
    "http://127.0.0.1:8473/",
    "http://127.0.0.1:50123/#airport",
    "http://127.0.0.1:8473/#airport=seattle",
    "http://127.0.0.1:8473/#airport=new%20york",
    "http://127.0.0.1:8473/#airport=st/x",
    "http://127.0.0.1:8473/#airport=a%26b%23c",
    "http://127.0.0.1:8473/#airport=caf%C3%A9",
])
def test_the_launcher_and_the_window_agree_on_a_link(app, page):
    """Both ends of the one contract: the link `kcgx` hands to `open` for a
    page (kcgx.launcher.window_opener, with `open` itself collected and not
    run) is read by the real app as that page, to the letter."""
    from kcgx import launcher

    ran = []
    launcher.window_opener(app, run=lambda command, **_: ran.append(command) or subprocess.CompletedProcess(command, 0))(page)
    [[*opening, link]] = ran
    assert opening == ["open", "-a", str(app)]
    assert check(app, link) == page


@pytest.mark.parametrize("link, fragment", [
    ("kcgx://show?port=8473&fragment=a%20b", "a%20b"),
    ("kcgx://show?port=8473&fragment=%22%3E%3Cscript%3E", "%22%3E%3Cscript%3E"),
    ("kcgx://show?port=8473&fragment=x%23y%23z", "x%23y%23z"),
    ("kcgx://show?port=8473&fragment=100%25", "100%25"),
    ("kcgx://show?port=8473&fragment=%2F%2Fevil.example%2F%3Fa%3Db", "//evil.example/?a=b"),
    ("kcgx://show?port=8473&fragment=caf%C3%A9", "caf%C3%A9"),
    # An escape that is no character is handed on as it came; the page copes
    # (test_a_link_with_a_query_that_cannot_be_decoded_still_opens_the_search).
    ("kcgx://show?port=8473&fragment=airport%3D%25E9", "airport=%E9"),
])
def test_whatever_the_fragment_holds_it_stays_a_fragment(app, link, fragment):
    assert check(app, link) == f"http://127.0.0.1:8473/#{fragment}"


@pytest.mark.parametrize("link", [
    "kcgx://show",                                        # no port
    "kcgx://show?fragment=airport",
    "kcgx://show?port=",
    "kcgx://show?port=80",                                # not from 1024 to 65535
    "kcgx://show?port=1023",
    "kcgx://show?port=65536",
    "kcgx://show?port=0",
    "kcgx://show?port=-8473",                             # not a whole number, plainly written
    "kcgx://show?port=%2B8473",
    "kcgx://show?port=8473.0",
    "kcgx://show?port=%208473",
    "kcgx://show?port=0x2119",
    "kcgx://show?port=8473%40evil.example",
    "kcgx://show?port=8473&port=8474",                    # said twice
    "kcgx://show?port=8473&fragment=a&fragment=b",
    "kcgx://show?port=8473&host=evil.example",            # anything else at all
    "kcgx://show?port=8473&url=http%3A%2F%2Fevil.example",
    "kcgx://show?port=8473&fragment",
    "kcgx://show?port=8473#airport",
    "kcgx://show/elsewhere?port=8473",
    "kcgx://show:99?port=8473",
    "kcgx://show@evil.example?port=8473",
    "kcgx://evil.example?port=8473",
    "kcgx://open?port=8473",
    "kcgx:show?port=8473",
    pytest.param("kcgx://show?port=8473&fragment=" + "a" * 600, id="a fragment longer than any airport search"),
    "http://127.0.0.1:8473/",                             # not ours
    "https://evil.example/?port=8473",
    "file:///etc/passwd",
    "",
])
def test_a_link_that_asks_for_anything_else_is_refused(app, link):
    assert check(app, link) is None
