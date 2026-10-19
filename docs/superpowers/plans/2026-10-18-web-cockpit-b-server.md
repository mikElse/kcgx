# Web Cockpit Phase B: The Server

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Put the phase A `Cockpit` behind a local web server: HTTP for
one-off requests, one WebSocket for everything live, audio still playing on
this machine through the existing mixer. Ends with a `kcgx-web` command and
a bare debug page that can drive every control, so the whole server can be
used with real audio before phase C builds the real page.

**Architecture:** Four new modules, each testable without the next:

| Module | Job | Knows about |
|---|---|---|
| `kcgx.protocol` | the JSON shapes, both directions; a strict parser for what pages send | nothing but plain objects |
| `kcgx.hub` | the open pages, one bounded queue each; the message log | protocol |
| `kcgx.station` | the mixer, the current airport's `Cockpit`, changing airport, acting for pages, the ticks | protocol, hub, squelch |
| `kcgx.server` | Starlette routes, the WebSocket, the local-only guard, the tick loops, the `kcgx-web` command | all of the above |

Everything runs on the server's one event loop. Session threads reach it
only through `Station`'s `post` (`loop.call_soon_threadsafe`), and the two
slow fetches (an airport's feed list, the picker's list) run in a worker
thread and come back to the loop before touching anything. The `Cockpit`'s
single-threaded contract from phase A therefore holds unchanged.

**Tech Stack:** Python 3.14, Starlette 1.9, uvicorn 0.54 with the
`websockets-sansio` implementation, websockets 17.2; tests with pytest,
pytest-asyncio and httpx2 2.14 (Starlette's test client).

**Spec:** `docs/superpowers/specs/2026-10-18-web-cockpit-design.md`, sections
"Transport", "Threads", "Changing airport", "Security".

## Decisions this plan makes that the spec did not

Task 10 writes these back into the spec.

1. **The JSON shapes live in `kcgx.protocol`, not on `Cockpit`.** The spec
   gave `Cockpit` `snapshot()` and `levels()`. A wire format is the
   server's concern; keeping it out leaves `Cockpit` free of anything a page
   needs. `Cockpit` gains only `stop()`.
2. **Level and chatter frames are keyed by ident**, not given in stack
   order. The order can change between two frames, and a positional list
   would hand one frame's levels to the wrong rows for 40 ms. Thirty feeds
   keyed by ident at 25 Hz is about 15 KB/s on localhost.
3. **A `chatter` frame goes out with every resort tick** (5 s), carrying each
   feed's five-minute figure. The spec had no way for a page to see chatter
   change.
4. **The server ticks the resort**, as `SquelchApp`'s timer does today.
5. **`open_feed` takes only an ident from the picker's last list.** The
   label never comes from a page.
6. **`Mixer.clear_channels()`** is new: an airport change has to release the
   old airport's channels without reopening the audio device.
7. **`squelch.runtime`** is new: `load_feeds`, `build_sessions` and friends
   move out of `squelch.__main__`, which imports Textual, so the server can
   use them without it. `squelch.__main__` re-exports every name.
8. **httpx2, not httpx.** Starlette 1.9's test client imports `httpx2` first
   and warns that `httpx` is deprecated.
9. **uvicorn runs `ws="websockets-sansio"`.** 0.54 deprecates `websockets`.

## Global Constraints

- Work in the `feat/web-cockpit` worktree at `/Users/mikelse/kcgx_web`.
- Python `>=3.14`. **The only new runtime dependencies are Starlette,
  uvicorn and websockets**; the only new dev dependency is httpx2.
- **The web modules never import Textual.** Task 2 adds a test that
  enforces it for every module this plan creates.
- **Bind to `127.0.0.1` only.** No route, test or command may listen on
  anything else.
- **No test touches the network, ffmpeg or an audio device.** The server is
  tested through Starlette's `TestClient`; the station through fake sessions
  and a real `Mixer` that is never started.
- Run everything through uv from the repo root:
  `cd /Users/mikelse/kcgx_web && uv run --project . pytest -q`
- The suite is **766 tests** at the start of this plan, and **871** at the end.
- **Existing tests are not edited**, with two exceptions, both additive:
  `tests/test_mixer.py` and `tests/test_cockpit.py` gain new tests at the
  end, and `test_cockpit.py`'s `FakeSession` gains a `stop()` method.
  Check with `git diff main -- tests/` before each commit.
- **Revert-check every new test** as phase A did: clean tree, one break,
  run the named test, record the real output, restore, confirm clean.
  Purge `__pycache__` around every break and every restore.
- **No test may write to `~/.local/state/kcgx/` or `~/.cache/squelch/`.**
  The station takes `remember=` for exactly this; tests pass a list's
  `append`.
- The repo owner may have the terminal cockpit running from
  `/Users/mikelse/kcgx`. Running `kcgx-web` alongside it plays a second set
  of streams and counts against LiveATC's seven; stop one first.
- Commit after every task. End each message with:
  ```
  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  ```

---

## File Structure

**Create:**

| Path | Responsibility |
|---|---|
| `src/squelch/runtime.py` | feed loading and session building, moved from `__main__` |
| `src/kcgx/protocol.py` | the wire format |
| `src/kcgx/hub.py` | open pages and the message log |
| `src/kcgx/station.py` | the mixer, the cockpit, the airport |
| `src/kcgx/server.py` | the ASGI app and `kcgx-web` |
| `src/kcgx/web/debug.html` | a bare page that drives the server until phase C |
| `tests/test_web_imports.py` | no Textual in any web module |
| `tests/test_protocol.py`, `tests/test_hub.py`, `tests/test_station.py`, `tests/test_server.py` | one per module |
| `tests/station_fakes.py` | the fake listing, picker and sessions station and server tests share |

**Modify:** `pyproject.toml`, `uv.lock` (Task 1, Task 8), `src/squelch/__main__.py`
(Task 2), `src/squelch/mixer.py` and `tests/test_mixer.py` (Task 3),
`src/squelch/cockpit.py` and `tests/test_cockpit.py` (Task 4), the spec and
`docs/README.md` (Task 10).

## The protocol at the end of phase B

Server to page, every frame a JSON object with a `t`:

| `t` | Carries | When |
|---|---|---|
| `snapshot` | `protocol`, `airport`, `loading`, `feeds` (stack order), `volume`, `max_streams`, `audio_ok`, `log` | first frame on connect; after every airport change, once with `loading: true` and again with the feeds |
| `feed` | one feed view | its state, mute, solo, ambient or connection changed |
| `added` | one feed view | a feed opened from the picker |
| `order` | `idents`, the new stack order | any reorder |
| `levels` | `v`: ident to dBFS, one decimal | 25 Hz, only while a page is open; droppable |
| `chatter` | `v`: ident to five-minute fraction | every resort tick; droppable |
| `volume` | `value` | volume changed |
| `message` | `z` (Zulu, `1955Z`), `text` | a line added to the log |
| `error` | `text` | this page sent something the protocol does not have |

Page to server: `mute`, `solo`, `ambient`, `open_feed` (each with `ident`),
`volume` (with `value`, clamped to 0..1), `input` (the viewer touched the
stack). HTTP: `GET /`, `GET /api/health`, `GET /api/airports?q=`,
`POST /api/airport` (`{"icao": "KSEA"}`, answers 202), `GET
/api/feeds/available`, `POST /api/shutdown`.

---

### Task 1: Dependencies

- [ ] **Step 1:**
  ```
  uv add 'starlette>=1.9.0,<2' 'uvicorn>=0.54.0,<0.55' 'websockets>=17.2,<18'
  uv add --dev 'httpx2>=2.14.0,<3'
  ```
- [ ] **Step 2:** Confirm what resolved:
  ```
  uv run python -c "import starlette, uvicorn, websockets, httpx2; print(starlette.__version__, uvicorn.__version__, websockets.__version__, httpx2.__version__)"
  ```
  Expected `1.9.0 0.54.0 17.2 2.14.0`, or newer patch releases inside the
  ranges. A newer minor of uvicorn is outside its range on purpose: 0.x
  minors have broken things before, so it is a decision, not an upgrade.
- [ ] **Step 3:** Full suite → 766 passed. Commit `build: starlette, uvicorn and websockets for the web cockpit`
  (`pyproject.toml`, `uv.lock`).

---

### Task 2: `squelch.runtime`, and the no-Textual guard

Move, **byte for byte**, these out of `src/squelch/__main__.py` into a new
`src/squelch/runtime.py`: the constants `AUDIO_FAILED` and `FFMPEG_MISSING`,
and the functions `_no_feeds`, `load_feeds`, `picker_feeds`,
`preferred_index` and `build_sessions`, in that order, docstrings and
comments included. Nothing in them changes.

- [ ] **Step 1: The new module's head.** `src/squelch/runtime.py` starts:

```python
"""Loading an airport's feeds and building their sessions, with no UI.

Moved out of squelch.__main__ so the web server can use exactly what the
terminal app uses without importing Textual. squelch.__main__ re-exports
every name here, so nothing that imported them from there has to change.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from squelch.config import Config
from squelch.feeds import (
    CACHE_TTL_SECONDS,
    Feed,
    FeedError,
    cached_age_seconds,
    fetch_feeds,
    read_cached_feeds,
    write_cached_feeds,
)
from squelch.session import FeedSession, SessionEvents
```

then the moved constants and functions.

- [ ] **Step 2: `__main__` re-exports them.** In `src/squelch/__main__.py`,
delete the moved definitions; drop `CACHE_TTL_SECONDS`, `cached_age_seconds`
and `read_cached_feeds` from its `squelch.feeds` import (nothing left there
uses them); change `from squelch.session import FeedSession, SessionEvents`
to import `SessionEvents` alone; and add the re-export, so the block after
the `squelch.feeds` import reads:

```python
from squelch.mixer import Mixer
from squelch.radar_theme import RadarTheme
from squelch.session import SessionEvents

# Re-exported: these used to be defined here, and callers still import them
# from here.
from squelch.runtime import (  # noqa: F401
    AUDIO_FAILED,
    FFMPEG_MISSING,
    _no_feeds,
    build_sessions,
    load_feeds,
    picker_feeds,
    preferred_index,
)
```

`tests/test_main.py` imports `FFMPEG_MISSING`, `build_sessions`,
`load_feeds` and `picker_feeds` from `squelch.__main__`, and its
monkeypatches target `squelch.config` and `squelch.feeds`, so it needs no
change.

- [ ] **Step 3: The guard.** Create `tests/test_web_imports.py` with
`WEB_MODULES = ["squelch.runtime", "squelch.cockpit"]`. Each later task adds
its own module to the list; at the end of Task 8 the file reads:

```python
"""The web side must never need Textual: it ships without it in phase E."""

from __future__ import annotations

import subprocess
import sys

import pytest

WEB_MODULES = [
    "squelch.runtime",
    "squelch.cockpit",
    "kcgx.protocol",
    "kcgx.hub",
    "kcgx.station",
    "kcgx.server",
]


@pytest.mark.parametrize("module", WEB_MODULES)
def test_importing_it_does_not_import_textual(module):
    probe = f"import sys, {module}; sys.exit('textual' in sys.modules)"
    assert subprocess.run([sys.executable, "-c", probe]).returncode == 0, module
```

- [ ] **Step 4:** `pytest tests/test_web_imports.py tests/test_main.py -q` →
45 passed. Revert-check: add `import textual` at the top of `runtime.py`;
expect `test_importing_it_does_not_import_textual[squelch.runtime]` to fail.
- [ ] **Step 5:** Full suite → 768 passed. `git diff main -- tests/` shows
only the new file. Commit `refactor(squelch): feed loading and session building in squelch.runtime`.

---

### Task 3: `Mixer.clear_channels()`

An airport change releases the old airport's channels. The callback runs on
PortAudio's thread and walks the list twice per block, and it may not
allocate, so: rebind rather than clear in place, and read the list once per
block.

- [ ] **Step 1: Tests.** Append to `tests/test_mixer.py`:

```python
# -- changing airport ------------------------------------------------------


def test_cleared_channels_no_longer_reach_the_output():
    mixer = Mixer(ambient_enabled=False)
    channel = mixer.add_channel()
    channel.muted = False
    channel.buffer.write(frame(0.5))
    mixer.clear_channels()
    assert not render(mixer).any()


def test_a_channel_added_after_clearing_plays():
    mixer = Mixer(ambient_enabled=False)
    mixer.add_channel()
    mixer.clear_channels()
    channel = mixer.add_channel()
    channel.muted = False
    channel.buffer.write(frame(0.5))
    assert render(mixer).any()


def test_clearing_rebinds_the_list_rather_than_emptying_it():
    """The callback may hold the old list on another thread. Emptying it in
    place would change it under that iteration; rebinding leaves it whole."""
    mixer = Mixer()
    mixer.add_channel()
    before = mixer._channels
    mixer.clear_channels()
    assert len(before) == 1
    assert mixer._channels is not before


def test_render_reads_the_channel_list_once_per_block():
    """Both loops in render() must see the same list, or a clear between
    them would mismatch the ambient positions for a block."""

    class Probe(Mixer):
        reads = 0

        @property
        def _channels(self):
            Probe.reads += 1
            return self.__dict__["channels"]

        @_channels.setter
        def _channels(self, value):
            self.__dict__["channels"] = value

    mixer = Probe()
    mixer.add_channel()
    Probe.reads = 0
    render(mixer)
    assert Probe.reads == 1
```

- [ ] **Step 2:** Run them; expect `AttributeError: 'Mixer' object has no attribute 'clear_channels'` and `Probe.reads == 2`.
- [ ] **Step 3: Implement.** In `src/squelch/mixer.py`, after `add_channel`:

```python
    def clear_channels(self) -> None:
        """Drop every channel, as when the cockpit changes airport.

        Rebinds rather than clearing in place: the callback may be partway
        through the list on PortAudio's thread. render() reads the list once
        per block, so it finishes that block with the old channels and
        starts the next with none. The mixer itself, and its open output
        stream, carry on: changing airport never reopens the device.
        """
        self._channels = []
```

In `render()`, after zeroing `amb_r`, add

```python
        # Read once: clear_channels() rebinds the list from another thread,
        # and both loops below must see the same one.
        channels = self._channels
```

and change both `for channel in self._channels:` loops to
`for channel in channels:`. A local binding is not an allocation;
`test_render_creates_no_temporaries` must stay green.

- [ ] **Step 4: Revert-check.**

| Break | Expected failure |
|---|---|
| `self._channels = []` → `self._channels.clear()` | `test_clearing_rebinds_the_list_rather_than_emptying_it` |
| put `self._channels` back in the second loop | `test_render_reads_the_channel_list_once_per_block` |

- [ ] **Step 5:** Full suite → 772 passed. Commit `feat(squelch): Mixer.clear_channels for changing airport`.

---

### Task 4: `Cockpit.stop()`

- [ ] **Step 1: Tests.** In `tests/test_cockpit.py`, give `FakeSession` a
`stop()` after `toggle_ambient`:

```python
    def stop(self):
        self.connected = False
        self.stopped = True
```

and append:

```python
# -- stopping --------------------------------------------------------------


def test_stop_stops_every_session_and_says_nothing():
    cockpit, rec, _ = make(3)
    cockpit.stop()
    assert all(getattr(s, "stopped", False) for s in cockpit.sessions)
    assert rec.events == []


def test_one_session_that_will_not_stop_does_not_keep_the_others_running():
    cockpit, _, _ = make(3)
    stubborn = cockpit.sessions[0]

    def refuse():
        raise RuntimeError("will not stop")

    stubborn.stop = refuse
    cockpit.stop()
    assert all(getattr(s, "stopped", False) for s in cockpit.sessions[1:])
```

- [ ] **Step 2: Implement.** In `src/squelch/cockpit.py`, before the
"telling the owner" section:

```python
    def stop(self) -> None:
        """Stop every session: the airport is changing, or the server is
        shutting down. Nothing is announced, because the owner is about to
        discard this cockpit; one session that fails to stop does not keep
        the others running."""
        for session in self._sessions:
            try:
                session.stop()
            except Exception:
                pass
```

- [ ] **Step 3: Revert-check.** Replace the `try`/`except` with a bare
`session.stop()`; expect `test_one_session_that_will_not_stop_does_not_keep_the_others_running`.
- [ ] **Step 4:** Full suite → 774 passed. Commit `feat(squelch): Cockpit.stop`.

---

### Task 5: The protocol

**Files:** Create `src/kcgx/protocol.py`, `tests/test_protocol.py`; add
`"kcgx.protocol"` to `WEB_MODULES`.

- [ ] **Step 1: Tests.** Create `tests/test_protocol.py`:

```python
"""The shapes that cross the WebSocket, without a socket."""

from __future__ import annotations

import json

import pytest

from kcgx.airports import find, load_airports
from kcgx.protocol import (
    PROTOCOL,
    BadMessage,
    airport_view,
    chatter_frame,
    encode,
    feed_view,
    levels_frame,
    order_frame,
    parse_client,
    snapshot,
)
from squelch.feeds import Feed


class Session:
    def __init__(self, ident, label, **kwargs):
        self.feed = Feed(ident=ident, label=label)
        self.name = label
        self.state = "live"
        self.muted = True
        self.soloed = False
        self.ambient = False
        self.connected = True
        self.activity = 0.0
        self.level = -96.0
        self.__dict__.update(kwargs)


def two():
    return [
        Session("kpdx3_twr", "Tower (Both)", muted=False, activity=0.3412, level=-21.37),
        Session("kpdx3_gnd", "Ground", activity=0.07, level=-60.04),
    ]


# -- server to page --------------------------------------------------------


def test_a_feed_view_carries_everything_a_row_shows():
    view = feed_view(two()[0])
    assert view == {
        "ident": "kpdx3_twr",
        "label": "Tower (Both)",
        "name": "Tower (Both)",
        "state": "live",
        "muted": False,
        "soloed": False,
        "ambient": False,
        "connected": True,
        "chatter": 0.341,
    }


def test_an_airport_view_from_the_dataset():
    view = airport_view(find("KPDX", load_airports()), "KPDX")
    assert view["icao"] == "KPDX"
    assert "Portland" in view["name"]
    assert view["lat"] == pytest.approx(45.59, abs=0.01)


def test_an_unknown_airport_still_has_its_code():
    assert airport_view(None, "ZZZZ") == {
        "icao": "ZZZZ", "iata": "", "name": "", "where": "", "lat": None, "lon": None,
    }


def test_a_snapshot_has_the_feeds_in_stack_order_and_the_protocol_version():
    frame = snapshot(
        airport=None,
        icao="KPDX",
        loading=False,
        sessions=two(),
        volume=0.8,
        max_streams=7,
        audio_ok=True,
        log=[{"z": "1955Z", "text": "hello"}],
    )
    assert frame["t"] == "snapshot"
    assert frame["protocol"] == PROTOCOL
    assert [f["ident"] for f in frame["feeds"]] == ["kpdx3_twr", "kpdx3_gnd"]
    assert frame["volume"] == 0.8
    assert frame["log"] == [{"z": "1955Z", "text": "hello"}]


def test_levels_are_keyed_by_ident_and_rounded():
    assert levels_frame(two()) == {"t": "levels", "v": {"kpdx3_twr": -21.4, "kpdx3_gnd": -60.0}}


def test_chatter_is_keyed_by_ident():
    assert chatter_frame(two())["v"] == {"kpdx3_twr": 0.341, "kpdx3_gnd": 0.07}


def test_order_is_a_list_of_idents():
    assert order_frame(two()) == {"t": "order", "idents": ["kpdx3_twr", "kpdx3_gnd"]}


def test_encoding_is_compact_and_keeps_unicode():
    text = encode({"t": "message", "text": "LiveATC streams 7 feeds at once — 2 parked (‖)"})
    assert " " not in text.split('"text"')[0]
    assert "—" in text and "‖" in text
    assert json.loads(text)["t"] == "message"


# -- page to server --------------------------------------------------------


@pytest.mark.parametrize("kind", ["mute", "solo", "ambient", "open_feed"])
def test_ident_actions_parse(kind):
    assert parse_client(json.dumps({"t": kind, "ident": "kpdx3_twr"})) == {
        "t": kind, "ident": "kpdx3_twr",
    }


def test_input_parses():
    assert parse_client('{"t":"input"}') == {"t": "input"}


@pytest.mark.parametrize("value, expected", [(0.5, 0.5), (0, 0.0), (1, 1.0), (1.7, 1.0), (-0.2, 0.0)])
def test_volume_is_clamped_to_the_unit_range(value, expected):
    assert parse_client(json.dumps({"t": "volume", "value": value})) == {
        "t": "volume", "value": expected,
    }


@pytest.mark.parametrize(
    "text",
    [
        "not json",
        "[1, 2]",
        '{"t": "explode"}',
        '{"ident": "kpdx3_twr"}',
        '{"t": "mute"}',
        '{"t": "mute", "ident": 7}',
        '{"t": "mute", "ident": "KPDX3_TWR"}',
        '{"t": "mute", "ident": "kpdx twr"}',
        '{"t": "mute", "ident": "../etc"}',
        json.dumps({"t": "mute", "ident": "a" * 65}),
        '{"t": "volume"}',
        '{"t": "volume", "value": "loud"}',
        '{"t": "volume", "value": true}',
        '{"t": "volume", "value": NaN}',
        '{"t": "volume", "value": Infinity}',
    ],
)
def test_anything_else_is_refused(text):
    with pytest.raises(BadMessage):
        parse_client(text)
```

- [ ] **Step 2:** Run; expect `ModuleNotFoundError: No module named 'kcgx.protocol'`.
- [ ] **Step 3: Implement.** Create `src/kcgx/protocol.py`:

```python
"""What crosses the WebSocket, in both directions.

Pure functions from cockpit state to JSON-ready dicts, and a strict parser
for what a page may send. Kept apart from the server so every shape can be
tested without a socket, and so the page has one file to read to learn the
protocol.

Feeds are addressed by ident everywhere, including in the level and
chatter frames, which are keyed by ident rather than given in stack order:
the order can change between two frames, and a positional list would
attribute one frame's levels to the wrong rows.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Iterable
from typing import Any

PROTOCOL = 1

# LiveATC idents as parse_airport_page leaves them: lower case, digits and
# underscores. Anything else from a page is not an ident.
IDENT_RE = re.compile(r"[a-z0-9_]{1,64}")

IDENT_ACTIONS = ("mute", "solo", "ambient")


def encode(frame: dict) -> str:
    """Compact JSON, UTF-8 left as is (feed names carry em dashes)."""
    return json.dumps(frame, separators=(",", ":"), ensure_ascii=False)


# -- server to page ----------------------------------------------------------


def feed_view(session: Any) -> dict:
    return {
        "ident": session.feed.ident,
        "label": session.feed.label,
        "name": session.name,
        "state": session.state,
        "muted": bool(session.muted),
        "soloed": bool(getattr(session, "soloed", False)),
        "ambient": bool(getattr(session, "ambient", False)),
        "connected": bool(session.connected),
        "chatter": round(float(session.activity), 3),
    }


def airport_view(airport: Any, icao: str) -> dict:
    """The airport as the page shows it. `airport` is a kcgx.airports.Airport,
    or None for an ICAO the dataset does not know."""
    if airport is None:
        return {"icao": icao, "iata": "", "name": "", "where": "", "lat": None, "lon": None}
    return {
        "icao": airport.icao,
        "iata": airport.iata,
        "name": airport.name,
        "where": airport.where,
        "lat": airport.lat,
        "lon": airport.lon,
    }


def snapshot(
    *,
    airport: Any,
    icao: str,
    loading: bool,
    sessions: Iterable,
    volume: float,
    max_streams: int,
    audio_ok: bool,
    log: Iterable[dict],
) -> dict:
    """Everything a page needs to draw from nothing: sent on connect and
    after every airport change."""
    return {
        "t": "snapshot",
        "protocol": PROTOCOL,
        "airport": airport_view(airport, icao),
        "loading": bool(loading),
        "feeds": [feed_view(s) for s in sessions],
        "volume": round(float(volume), 2),
        "max_streams": int(max_streams),
        "audio_ok": bool(audio_ok),
        "log": list(log),
    }


def feed_frame(session: Any) -> dict:
    return {"t": "feed", "feed": feed_view(session)}


def added_frame(session: Any) -> dict:
    return {"t": "added", "feed": feed_view(session)}


def order_frame(sessions: Iterable) -> dict:
    return {"t": "order", "idents": [s.feed.ident for s in sessions]}


def levels_frame(sessions: Iterable) -> dict:
    return {"t": "levels", "v": {s.feed.ident: round(float(s.level), 1) for s in sessions}}


def chatter_frame(sessions: Iterable) -> dict:
    return {"t": "chatter", "v": {s.feed.ident: round(float(s.activity), 3) for s in sessions}}


def volume_frame(value: float) -> dict:
    return {"t": "volume", "value": round(float(value), 2)}


def message_frame(entry: dict) -> dict:
    return {"t": "message", **entry}


def error_frame(text: str) -> dict:
    return {"t": "error", "text": text}


# -- page to server ----------------------------------------------------------


class BadMessage(ValueError):
    """A page sent something this protocol does not have."""


def parse_client(text: str) -> dict:
    """Validate one message from a page, or raise BadMessage.

    Strict on purpose: every field is checked for type and shape, and
    anything unrecognised is refused rather than ignored, so a page bug
    shows up as an error frame instead of a control that silently does
    nothing.
    """
    try:
        data = json.loads(text)
    except ValueError:
        raise BadMessage("not JSON") from None
    if not isinstance(data, dict):
        raise BadMessage("not a JSON object")
    kind = data.get("t")
    if kind in IDENT_ACTIONS:
        return {"t": kind, "ident": _ident(data)}
    if kind == "open_feed":
        return {"t": "open_feed", "ident": _ident(data)}
    if kind == "volume":
        value = data.get("value")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise BadMessage("volume needs a number")
        if not math.isfinite(value):
            raise BadMessage("volume needs a finite number")
        return {"t": "volume", "value": min(1.0, max(0.0, float(value)))}
    if kind == "input":
        return {"t": "input"}
    raise BadMessage(f"unknown message type: {kind!r}")


def _ident(data: dict) -> str:
    value = data.get("ident")
    if not isinstance(value, str) or not IDENT_RE.fullmatch(value):
        raise BadMessage("bad feed ident")
    return value
```

- [ ] **Step 4: Revert-check.**

| Break | Expected failure |
|---|---|
| `IDENT_RE` → `re.compile(r".{1,64}")` | `test_anything_else_is_refused` (3 cases) |
| return `float(value)` unclamped | `test_volume_is_clamped_to_the_unit_range` (2 cases) |

- [ ] **Step 5:** Full suite → 808 passed. Commit `feat(kcgx): the web cockpit's wire protocol`.

---

### Task 6: The hub

**Files:** Create `src/kcgx/hub.py`, `tests/test_hub.py`; add `"kcgx.hub"`
to `WEB_MODULES`.

- [ ] **Step 1: Tests.** Create `tests/test_hub.py`:

```python
"""Fan-out to open pages: ordering, dropping, and giving up on a slow one."""

from __future__ import annotations

import asyncio
import json

from kcgx.hub import LOG_SIZE, Client, Hub, zulu


def sink(size=64):
    sent = []

    async def send(text):
        sent.append(json.loads(text))

    evictions = []
    client = Client(send, on_evict=lambda: evictions.append(True), size=size)
    return client, sent, evictions


def queued(client):
    out = []
    while not client.queue.empty():
        out.append(json.loads(client.queue.get_nowait()))
    return out


async def test_a_broadcast_reaches_every_page_in_order():
    hub = Hub()
    a, _, _ = sink()
    b, _, _ = sink()
    hub.add(a)
    hub.add(b)
    hub.broadcast({"t": "one"})
    hub.broadcast({"t": "two"})
    assert [f["t"] for f in queued(a)] == ["one", "two"]
    assert [f["t"] for f in queued(b)] == ["one", "two"]


async def test_the_pump_sends_what_was_queued():
    hub = Hub()
    client, sent, _ = sink()
    hub.add(client)
    hub.broadcast({"t": "one"})
    task = asyncio.create_task(client.pump())
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    task.cancel()
    assert sent == [{"t": "one"}]


async def test_a_send_that_fails_ends_the_pump_quietly():
    async def broken(text):
        raise ConnectionError("socket gone")

    client = Client(broken)
    client.offer("{}")
    await asyncio.wait_for(client.pump(), 1)  # returns rather than raising


async def test_a_full_page_skips_a_level_frame_and_stays():
    hub = Hub()
    client, _, evictions = sink(size=1)
    hub.add(client)
    hub.broadcast({"t": "feed"})
    hub.broadcast({"t": "levels"}, droppable=True)
    assert client in hub.clients
    assert evictions == []
    assert [f["t"] for f in queued(client)] == ["feed"]


async def test_a_full_page_is_dropped_rather_than_sent_a_gap():
    """A page that misses a feed or order frame is out of step for good;
    reconnecting gets it a snapshot, which is the only honest repair."""
    hub = Hub()
    client, _, evictions = sink(size=1)
    hub.add(client)
    hub.broadcast({"t": "feed"})
    hub.broadcast({"t": "order"})
    assert client not in hub.clients
    assert evictions == [True]


async def test_a_slow_page_does_not_hold_up_the_others():
    hub = Hub()
    slow, _, _ = sink(size=1)
    fast, _, _ = sink()
    hub.add(slow)
    hub.add(fast)
    for n in range(5):
        hub.broadcast({"t": "feed", "n": n})
    assert [f["n"] for f in queued(fast)] == [0, 1, 2, 3, 4]


async def test_an_evicted_page_is_sent_nothing_more():
    hub = Hub()
    client, _, _ = sink(size=1)
    hub.add(client)
    hub.broadcast({"t": "feed"})
    hub.broadcast({"t": "feed"})
    queued(client)
    hub.broadcast({"t": "feed"})
    assert queued(client) == []


async def test_a_removed_page_is_sent_nothing():
    hub = Hub()
    client, _, _ = sink()
    hub.add(client)
    hub.remove(client)
    hub.broadcast({"t": "feed"})
    assert queued(client) == []


async def test_a_note_is_logged_stamped_in_zulu_and_shown():
    hub = Hub(clock=lambda: 1792371300.0)  # 2026-10-19 00:55 UTC
    client, _, _ = sink()
    hub.add(client)
    entry = hub.note("TROUTDALE TOWER: reconnecting")
    assert entry == {"z": "0055Z", "text": "TROUTDALE TOWER: reconnecting"}
    assert list(hub.log) == [entry]
    assert queued(client) == [{"t": "message", **entry}]


async def test_the_log_is_capped():
    hub = Hub()
    for n in range(LOG_SIZE + 5):
        hub.note(str(n))
    assert len(hub.log) == LOG_SIZE
    assert hub.log[0]["text"] == "5"


def test_zulu_is_hours_and_minutes_utc():
    assert zulu(0) == "0000Z"
    assert zulu(19 * 3600 + 55 * 60) == "1955Z"
```

- [ ] **Step 2:** Run; expect `ModuleNotFoundError: No module named 'kcgx.hub'`.
- [ ] **Step 3: Implement.** Create `src/kcgx/hub.py`:

```python
"""Everyone watching, and what they are sent.

Each page gets its own bounded queue and its own sender task, so one slow
tab cannot hold up the others or the event loop. Level and chatter frames
are the only ones that may be dropped: when a page's queue is full the
frame is skipped, because the next one replaces it anyway. Anything else
that does not fit means the page has fallen hopelessly behind, and it is
disconnected. It reconnects and gets a fresh snapshot, which is cheaper and
more honest than a page quietly out of step with the server.

Everything here runs on the event loop.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from collections.abc import Awaitable, Callable

from kcgx.protocol import encode, message_frame

QUEUE_SIZE = 64

# Matches squelch's own message log, so a page and the terminal keep the
# same history.
LOG_SIZE = 200


def zulu(seconds: float) -> str:
    """`1955Z`: UTC as ATC says it on the air."""
    return time.strftime("%H%MZ", time.gmtime(seconds))


class Client:
    """One open page."""

    def __init__(
        self,
        send: Callable[[str], Awaitable[None]],
        *,
        on_evict: Callable[[], None] = lambda: None,
        size: int = QUEUE_SIZE,
    ) -> None:
        self._send = send
        self._on_evict = on_evict
        self.queue: asyncio.Queue[str] = asyncio.Queue(size)
        self.evicted = False

    def offer(self, text: str, *, droppable: bool = False) -> bool:
        """Queue `text`. False means this page has to go."""
        if self.evicted:
            return False
        try:
            self.queue.put_nowait(text)
        except asyncio.QueueFull:
            return droppable
        return True

    def evict(self) -> None:
        if not self.evicted:
            self.evicted = True
            self._on_evict()

    async def pump(self) -> None:
        """Send queued frames until cancelled or the socket fails.

        A failed send ends the pump quietly: the socket is gone, and the
        receive side of the connection will notice and clean up."""
        while True:
            text = await self.queue.get()
            try:
                await self._send(text)
            except Exception:
                return


class Hub:
    def __init__(self, *, clock: Callable[[], float] = time.time) -> None:
        self.clients: set[Client] = set()
        self.log: deque[dict] = deque(maxlen=LOG_SIZE)
        self._clock = clock

    def add(self, client: Client) -> None:
        self.clients.add(client)

    def remove(self, client: Client) -> None:
        self.clients.discard(client)

    def send(self, client: Client, frame: dict) -> None:
        if not client.offer(encode(frame)):
            self._evict(client)

    def broadcast(self, frame: dict, *, droppable: bool = False) -> None:
        if not self.clients:
            return
        text = encode(frame)
        for client in list(self.clients):
            if not client.offer(text, droppable=droppable):
                self._evict(client)

    def note(self, text: str) -> dict:
        """Add a line to the log, and show it to everyone."""
        entry = {"z": zulu(self._clock()), "text": text}
        self.log.append(entry)
        self.broadcast(message_frame(entry))
        return entry

    def _evict(self, client: Client) -> None:
        self.clients.discard(client)
        client.evict()
```

- [ ] **Step 4: Revert-check.**

| Break | Expected failure |
|---|---|
| in `offer`, `return droppable` → `return True` | `test_a_full_page_is_dropped_rather_than_sent_a_gap` |
| in `offer`, `return droppable` → `return False` | `test_a_full_page_skips_a_level_frame_and_stays` |

- [ ] **Step 5:** Full suite → 820 passed. Commit `feat(kcgx): the hub, one bounded queue per page`.

---

### Task 7: The station

**Files:** Create `src/kcgx/station.py`, `tests/station_fakes.py`,
`tests/test_station.py`; add `"kcgx.station"` to `WEB_MODULES`.

`tests/` is not a package, and pytest puts it on `sys.path`, so the shared
fakes are imported as `station_fakes`, not `tests.station_fakes`.

- [ ] **Step 1: The fakes.** Create `tests/station_fakes.py`:

```python
"""Fakes shared by test_station.py and test_server.py: a feed listing, a
picker list, and sessions that behave like FeedSession without ffmpeg."""

from __future__ import annotations

from kcgx.airports import load_airports
from squelch.feeds import Feed

AIRPORTS = load_airports()

LISTINGS = {
    "KPDX": [
        Feed("kpdx3_twr", "KPDX Tower (Both)"),
        Feed("kpdx3_gnd", "KPDX Ground"),
        Feed("kpdx3_atis", "KPDX ATIS"),
    ],
    "KSEA": [Feed("ksea_twr", "KSEA Tower"), Feed("ksea_gnd", "KSEA Ground")],
    "KORD": [Feed("kord_twr", "KORD Tower")],
}


class FakeSession:
    def __init__(self, feed, events, *, muted):
        self.feed = feed
        self.name = feed.label.split(" ", 1)[-1]
        self.events = events
        self.muted = muted
        self.state = "starting"
        self.ambient = False
        self.soloed = False
        self.activity = 0.0
        self.level = -96.0
        self.connected = False
        self.stopped = False

    def start(self):
        self.connected = True
        self.state = "live"

    def park(self):
        self.connected = False
        self.state = "parked"

    def stop(self):
        self.connected = False
        self.stopped = True

    def toggle_mute(self):
        self.muted = not self.muted
        return self.muted

    def toggle_ambient(self):
        self.ambient = not self.ambient
        return self.ambient


class Builder:
    """Stands in for squelch.runtime.build_sessions."""

    def __init__(self):
        self.built = []
        self.events = None

    def __call__(self, feeds, config, events, *, mixer=None):
        self.events = events
        out = []
        for feed in feeds:
            if mixer is not None:
                mixer.add_channel()
            out.append(FakeSession(feed, events, muted=feed.ident != config.feed))
        if out and all(s.muted for s in out):
            out[0].muted = False
        self.built.extend(out)
        return out


def listing(config, *, warn):
    return list(LISTINGS.get(config.icao, []))


def picker(config):
    return list(LISTINGS.get(config.icao, [])) + [Feed(f"{config.icao.lower()}_del", "Delivery")]
```

- [ ] **Step 2: Tests.** Create `tests/test_station.py`:

```python
"""The station: loading an airport, changing it, and acting for pages.

Fake sessions and a fake feed listing; a real Mixer that is never started,
so its channel list is the real one; the real airport dataset.
"""

from __future__ import annotations

import asyncio
import json
import threading

import pytest

from kcgx.hub import Client, Hub
from kcgx.station import Station, UnknownAirport
from squelch.config import Config
from squelch.mixer import Mixer
from squelch.runtime import AUDIO_FAILED
from station_fakes import AIRPORTS, LISTINGS, Builder, listing, picker

def make(loader=listing, *, mixer=None):
    loop = asyncio.get_running_loop()
    hub = Hub()
    builder = Builder()
    remembered = []
    station = Station(
        Config(icao="KPDX", feed="kpdx3_twr"),
        hub,
        post=lambda fn, *args: loop.call_soon_threadsafe(fn, *args),
        airports=AIRPORTS,
        mixer=mixer or Mixer(),
        feeds_loader=loader,
        sessions_builder=builder,
        picker_loader=picker,
        remember=remembered.append,
    )
    return station, hub, builder, remembered


def watch(hub):
    async def send(text):
        pass

    client = Client(send, size=1000)
    hub.add(client)
    return client


def frames(client, kind=None):
    out = []
    while not client.queue.empty():
        frame = json.loads(client.queue.get_nowait())
        if kind is None or frame["t"] == kind:
            out.append(frame)
    return out


def idents(station):
    return [s.feed.ident for s in station.cockpit.sessions]


# -- opening and changing airport ------------------------------------------


async def test_opening_loads_the_airport_and_starts_its_feeds():
    station, _, _, remembered = make()
    await station.open("KPDX")
    assert idents(station) == ["kpdx3_twr", "kpdx3_gnd", "kpdx3_atis"]
    assert all(s.connected for s in station.cockpit.sessions)
    assert station.loading is False
    assert remembered == [], "the first airport came from the state file"


async def test_pages_see_loading_then_the_feeds():
    station, hub, _, _ = make()
    page = watch(hub)
    await station.open("KPDX")
    snapshots = frames(page, "snapshot")
    assert [s["loading"] for s in snapshots] == [True, False]
    assert snapshots[0]["feeds"] == []
    assert [f["ident"] for f in snapshots[1]["feeds"]] == idents(station)
    assert snapshots[1]["airport"]["icao"] == "KPDX"


async def test_a_missing_audio_device_is_said_once_on_opening():
    mixer = Mixer()
    mixer.failed = True
    station, hub, _, _ = make(mixer=mixer)
    await station.open("KPDX")
    assert [e["text"] for e in hub.log].count(AUDIO_FAILED) == 1
    assert station.snapshot()["audio_ok"] is False


async def test_listing_warnings_reach_the_log_after_the_feeds():
    def warning_listing(config, *, warn):
        warn("could not refresh the feed list — using the cached list")
        return list(LISTINGS["KPDX"])

    station, hub, _, _ = make(warning_listing)
    page = watch(hub)
    await station.open("KPDX")
    kinds = [f["t"] for f in frames(page)]
    assert kinds.index("message") > max(i for i, k in enumerate(kinds) if k == "snapshot")
    assert "cached list" in hub.log[-1]["text"]


async def test_a_listing_that_raises_leaves_an_empty_stack_and_says_so():
    def broken(config, *, warn):
        raise OSError("network down")

    station, hub, _, _ = make(broken)
    await station.open("KPDX")
    assert idents(station) == []
    assert station.loading is False
    assert "network down" in hub.log[-1]["text"]


async def test_an_unknown_airport_is_refused_and_nothing_changes():
    station, _, _, remembered = make()
    await station.open("KPDX")
    before = station.cockpit
    with pytest.raises(UnknownAirport):
        await station.change_airport("ZZZZ")
    assert station.cockpit is before
    assert remembered == []


async def test_changing_airport_stops_the_old_feeds_and_remembers_the_new_one():
    mixer = Mixer()
    station, _, builder, remembered = make(mixer=mixer)
    await station.open("KPDX")
    old = station.cockpit.sessions
    await station.change_airport("ksea")
    assert all(s.stopped for s in old)
    assert idents(station) == ["ksea_twr", "ksea_gnd"]
    assert station.icao == "KSEA"
    assert remembered == ["KSEA"]
    assert len(mixer._channels) == 2, "the old airport's channels must go"


async def test_the_configured_feed_is_audible_only_at_its_own_airport():
    station, _, _, _ = make()
    await station.change_airport("KSEA")
    audible = [s.feed.ident for s in station.cockpit.sessions if not s.muted]
    assert audible == ["ksea_twr"], "falls back to the first feed, never kpdx3_twr"


async def test_a_second_change_while_the_first_is_loading_wins():
    gate = threading.Event()

    def slow_seattle(config, *, warn):
        if config.icao == "KSEA":
            gate.wait(5)
        return list(LISTINGS.get(config.icao, []))

    station, _, builder, _ = make(slow_seattle)
    await station.open("KPDX")
    seattle = asyncio.create_task(station.change_airport("KSEA"))
    await asyncio.sleep(0.05)
    await station.change_airport("KORD")
    gate.set()
    await seattle
    assert station.icao == "KORD"
    assert idents(station) == ["kord_twr"]
    assert not any(s.feed.ident.startswith("ksea") for s in builder.built)


# -- session events --------------------------------------------------------


async def test_a_session_event_from_its_own_thread_reaches_pages():
    station, hub, builder, _ = make()
    await station.open("KPDX")
    page = watch(hub)
    session = station.cockpit.sessions[1]
    session.state = "reconnecting"
    thread = threading.Thread(target=builder.events.on_state, args=(session, "reconnecting"))
    thread.start()
    thread.join()
    await asyncio.sleep(0.05)
    feeds = frames(page, "feed")
    assert feeds and feeds[-1]["feed"]["state"] == "reconnecting"


async def test_a_session_warning_is_logged_with_its_name():
    station, hub, builder, _ = make()
    await station.open("KPDX")
    session = station.cockpit.sessions[0]
    builder.events.on_warn(session, "could not resolve feed")
    await asyncio.sleep(0.05)
    assert hub.log[-1]["text"] == "Tower (Both): could not resolve feed"


async def test_events_from_the_previous_airport_are_ignored():
    station, hub, builder, _ = make()
    await station.open("KPDX")
    stale = station.cockpit.sessions[0]
    await station.change_airport("KSEA")
    page = watch(hub)
    builder.events.on_state(stale, "offline")
    builder.events.on_warn(stale, "gone")
    await asyncio.sleep(0.05)
    assert frames(page) == []


# -- acting for pages ------------------------------------------------------


async def test_mute_from_a_page_moves_the_stack_for_every_page():
    station, hub, _, _ = make()
    await station.open("KPDX")
    page = watch(hub)
    station.handle({"t": "mute", "ident": "kpdx3_atis"})
    sent = frames(page)
    assert [f["t"] for f in sent][-1] == "order"
    # Tower was already audible; ATIS joins it above the muted Ground.
    assert sent[-1]["idents"] == ["kpdx3_twr", "kpdx3_atis", "kpdx3_gnd"]
    assert any(f["t"] == "feed" and f["feed"]["ident"] == "kpdx3_atis" for f in sent)


async def test_solo_and_ambient_from_a_page():
    station, _, _, _ = make()
    await station.open("KPDX")
    station.handle({"t": "solo", "ident": "kpdx3_gnd"})
    assert [s.feed.ident for s in station.cockpit.sessions if not s.muted] == ["kpdx3_gnd"]
    station.handle({"t": "ambient", "ident": "kpdx3_gnd"})
    assert station.cockpit.session("kpdx3_gnd").ambient is True


async def test_volume_reaches_the_mixer_and_every_page():
    station, hub, _, _ = make()
    await station.open("KPDX")
    page = watch(hub)
    station.handle({"t": "volume", "value": 0.35})
    assert station.mixer.volume == pytest.approx(0.35)
    assert frames(page, "volume") == [{"t": "volume", "value": 0.35}]


async def test_input_from_a_page_holds_the_resort():
    station, _, _, _ = make()
    await station.open("KPDX")
    station.handle({"t": "input"})
    assert station.cockpit.resorter._last_input is not None


async def test_opening_a_feed_needs_the_picker_list_first():
    station, hub, _, _ = make()
    await station.open("KPDX")
    station.handle({"t": "open_feed", "ident": "kpdx_del"})
    assert "not in the feed list" in hub.log[-1]["text"]
    assert station.cockpit.session("kpdx_del") is None


async def test_a_feed_from_the_picker_opens_and_every_page_sees_it():
    station, hub, _, _ = make()
    await station.open("KPDX")
    listed = await station.available_feeds()
    assert {"ident": "kpdx_del", "label": "Delivery", "open": False} in listed
    assert {"ident": "kpdx3_twr", "label": "KPDX Tower (Both)", "open": True} in listed
    page = watch(hub)
    station.handle({"t": "open_feed", "ident": "kpdx_del"})
    assert station.cockpit.session("kpdx_del") is not None
    assert [f["feed"]["ident"] for f in frames(page, "added")] == ["kpdx_del"]


async def test_opening_a_feed_that_is_already_open_does_nothing():
    station, hub, _, _ = make()
    await station.open("KPDX")
    await station.available_feeds()
    before = len(hub.log)
    station.handle({"t": "open_feed", "ident": "kpdx3_twr"})
    assert len(station.cockpit.sessions) == 3
    assert len(hub.log) == before


# -- ticking ---------------------------------------------------------------


async def test_levels_go_out_only_when_someone_is_watching():
    station, hub, _, _ = make()
    await station.open("KPDX")
    station.tick_levels()
    page = watch(hub)
    station.cockpit.sessions[0].level = -12.34
    station.tick_levels()
    levels = frames(page, "levels")
    assert len(levels) == 1
    assert levels[0]["v"]["kpdx3_twr"] == -12.3


async def test_the_resort_tick_reorders_and_sends_chatter():
    station, hub, _, _ = make()
    await station.open("KPDX")
    page = watch(hub)
    station.cockpit.sessions[2].activity = 0.9
    for _ in range(3):
        station.tick_resort()
    assert idents(station)[1] == "kpdx3_atis"
    assert frames(page, "chatter")[-1]["v"]["kpdx3_atis"] == 0.9


# -- stopping --------------------------------------------------------------


async def test_stop_stops_every_feed_and_releases_the_mixer_channels():
    mixer = Mixer()
    station, _, _, _ = make(mixer=mixer)
    await station.open("KPDX")
    sessions = station.cockpit.sessions
    station.stop()
    assert all(s.stopped for s in sessions)
    assert mixer._channels == []
```

- [ ] **Step 3:** Run; expect `ModuleNotFoundError: No module named 'kcgx.station'`.
- [ ] **Step 4: Implement.** Create `src/kcgx/station.py`:

```python
"""One server's worth of squelch: the mixer, the current airport's cockpit,
and changing airport.

Everything here runs on the server's event loop. Session threads reach it
only through `post`, which hands a call to the loop, so the Cockpit's
single-threaded contract holds. The two slow things, fetching an airport's
feed list and the picker's list, run in a worker thread and come back to
the loop before they touch anything.

The mixer belongs to the server, not to an airport: it is opened once and
survives every airport change, so a change never reopens the audio device.
"""

from __future__ import annotations

import asyncio
import functools
from collections.abc import Callable
from dataclasses import replace
from typing import Any

from kcgx import protocol
from kcgx.airports import Airport, find
from kcgx.hub import Hub
from kcgx.state import write_airport
from squelch.cockpit import ADDED, FEED, MESSAGE, ORDER, Cockpit
from squelch.config import Config
from squelch.feeds import Feed
from squelch.runtime import AUDIO_FAILED, build_sessions, load_feeds, picker_feeds
from squelch.session import SessionEvents

Post = Callable[..., None]


class UnknownAirport(LookupError):
    """An ICAO the airport dataset does not have."""


class Station:
    def __init__(
        self,
        config: Config,
        hub: Hub,
        *,
        post: Post,
        airports: list[Airport],
        mixer: Any,
        feeds_loader: Callable[..., list[Feed]] = load_feeds,
        sessions_builder: Callable[..., list] = build_sessions,
        picker_loader: Callable[..., list[Feed]] = picker_feeds,
        remember: Callable[[str], None] = write_airport,
    ) -> None:
        self.config = config
        self.hub = hub
        self.mixer = mixer
        self._post = post
        self.airports = airports
        self._feeds_loader = feeds_loader
        self._sessions_builder = sessions_builder
        self._picker_loader = picker_loader
        self._remember = remember
        self._events = SessionEvents(
            on_state=lambda session, state: self._post(self._session_changed, session),
            on_warn=lambda session, message: self._post(
                self._session_warned, session, message
            ),
        )
        # Bumped by every airport change and by stop(); a load that finishes
        # under an older generation is thrown away.
        self._generation = 0
        self._picker: dict[str, Feed] = {}
        self.icao = config.icao
        self.airport: Airport | None = None
        self.loading = False
        self.cockpit = self._new_cockpit(config, [])

    # -- airports --------------------------------------------------------

    async def open(self, icao: str) -> None:
        """The first airport of the server's life. Not remembered: it came
        from the state file in the first place."""
        if getattr(self.mixer, "failed", False):
            self.hub.note(AUDIO_FAILED)
        await self.change_airport(icao, remember=False)

    def check_airport(self, icao: str) -> Airport:
        airport = find(icao.strip().upper(), self.airports)
        if airport is None:
            raise UnknownAirport(icao)
        return airport

    async def change_airport(self, icao: str, *, remember: bool = True) -> None:
        """Point the station at `icao`: stop the old feeds, fetch the new
        list off the loop, build and start the new feeds.

        Pages see a snapshot with `loading` set at once, then a full one when
        the feeds arrive. A second change while the first is still fetching
        wins; the first one's feeds are never built.
        """
        airport = self.check_airport(icao)
        self._generation += 1
        generation = self._generation
        if remember:
            self._remember(airport.icao)
        self._discard()
        config = replace(self.config, icao=airport.icao)
        self.icao, self.airport, self.loading = airport.icao, airport, True
        self._picker = {}
        self.cockpit = self._new_cockpit(config, [])
        self.hub.broadcast(self.snapshot())

        warnings: list[str] = []
        try:
            feeds = await self._in_thread(self._feeds_loader, config, warn=warnings.append)
        except Exception as exc:  # a dead listing must not take the server with it
            feeds = []
            warnings.append(f"{airport.icao} — could not load the feed list ({exc})")
        if generation != self._generation:
            return

        sessions = self._sessions_builder(feeds, config, self._events, mixer=self.mixer)
        self.cockpit = self._new_cockpit(config, sessions)
        self.loading = False
        self.hub.broadcast(self.snapshot())
        for message in warnings:
            self.hub.note(message)
        self.cockpit.start()

    async def available_feeds(self) -> list[dict]:
        """The feed picker's list. Refreshed on every ask, as the terminal
        picker is; what it returns is the only list `open_feed` will take
        an ident from."""
        config = self.cockpit.config
        try:
            feeds = await self._in_thread(self._picker_loader, config)
        except Exception:
            feeds = []
        if config is not self.cockpit.config:
            return []  # the airport changed while we were fetching
        self._picker = {feed.ident: feed for feed in feeds}
        return [
            {
                "ident": feed.ident,
                "label": feed.label,
                "open": self.cockpit.session(feed.ident) is not None,
            }
            for feed in feeds
        ]

    # -- what pages ask for ------------------------------------------------

    def handle(self, message: dict) -> None:
        """Act on one parsed message from a page (see protocol.parse_client)."""
        kind = message["t"]
        cockpit = self.cockpit
        if kind == "mute":
            cockpit.toggle_mute(message["ident"])
        elif kind == "solo":
            cockpit.toggle_solo(message["ident"])
        elif kind == "ambient":
            cockpit.toggle_ambient(message["ident"])
        elif kind == "volume":
            self.set_volume(message["value"])
        elif kind == "open_feed":
            self.open_feed(message["ident"])
        elif kind == "input":
            cockpit.note_input()

    def set_volume(self, value: float) -> None:
        self.mixer.volume = float(value)
        self.hub.broadcast(protocol.volume_frame(self.mixer.volume))

    def open_feed(self, ident: str) -> None:
        if self.cockpit.session(ident) is not None:
            return  # already open: the page selects it
        feed = self._picker.get(ident)
        if feed is None:
            self.hub.note(f"{ident} is not in the feed list; open the picker to refresh it")
            return
        self.cockpit.open_feed(feed)

    # -- ticking -----------------------------------------------------------

    def tick_levels(self) -> None:
        if self.hub.clients:
            self.hub.broadcast(protocol.levels_frame(self.cockpit.sessions), droppable=True)

    def tick_resort(self) -> None:
        self.cockpit.tick_resort()
        if self.hub.clients:
            self.hub.broadcast(protocol.chatter_frame(self.cockpit.sessions), droppable=True)

    # -- reading -----------------------------------------------------------

    def snapshot(self) -> dict:
        return protocol.snapshot(
            airport=self.airport,
            icao=self.icao,
            loading=self.loading,
            sessions=self.cockpit.sessions,
            volume=self.mixer.volume,
            max_streams=self.cockpit.max_streams,
            audio_ok=not getattr(self.mixer, "failed", False),
            log=self.hub.log,
        )

    # -- shutting down -----------------------------------------------------

    def stop(self) -> None:
        """Stop every feed. The mixer is the server's to close."""
        self._generation += 1
        self._discard()

    # -- internals ---------------------------------------------------------

    def _new_cockpit(self, config: Config, sessions: list) -> Cockpit:
        return Cockpit(
            config,
            sessions,
            feed_opener=self._build_one,
            on_change=self._on_change,
        )

    def _build_one(self, feed: Feed):
        config = replace(self.cockpit.config, feed=feed.ident)
        return self._sessions_builder([feed], config, self._events, mixer=self.mixer)[0]

    def _discard(self) -> None:
        self.cockpit.stop()
        self.mixer.clear_channels()

    def _on_change(self, kind: str, payload: Any) -> None:
        if kind == FEED:
            self.hub.broadcast(protocol.feed_frame(payload))
        elif kind == ORDER:
            self.hub.broadcast(protocol.order_frame(payload))
        elif kind == ADDED:
            self.hub.broadcast(protocol.added_frame(payload))
        elif kind == MESSAGE:
            self.hub.note(payload)

    def _current(self, session: Any) -> bool:
        """Whether `session` belongs to the cockpit on show. A session from
        the airport before can still report as its thread winds down."""
        return self.cockpit.session(session.feed.ident) is session

    def _session_changed(self, session: Any) -> None:
        if self._current(session):
            self.hub.broadcast(protocol.feed_frame(session))

    def _session_warned(self, session: Any, message: str) -> None:
        if self._current(session):
            self.hub.note(f"{session.name}: {message}")

    async def _in_thread(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, functools.partial(fn, *args, **kwargs))
```

- [ ] **Step 5: Revert-check.**

| Break | Expected failure |
|---|---|
| delete the `if generation != self._generation: return` after the fetch | `test_a_second_change_while_the_first_is_loading_wins` |
| `_current` returns `True` | `test_events_from_the_previous_airport_are_ignored` |
| delete `self._discard()` in `change_airport` | `test_changing_airport_stops_the_old_feeds_and_remembers_the_new_one` |
| `feed = self._picker.get(ident) or Feed(ident, ident)` | `test_opening_a_feed_needs_the_picker_list_first` |

- [ ] **Step 6:** Run `tests/test_station.py` three times; it uses a thread
and a real event loop, and must be green every time. Full suite → 843
passed. Commit `feat(kcgx): the station, owning the mixer, the cockpit and the airport`.

---

### Task 8: The server, the command and the debug page

**Files:** Create `src/kcgx/server.py`, `src/kcgx/web/debug.html`,
`tests/test_server.py`; add `"kcgx.server"` to `WEB_MODULES`; add the
console script to `pyproject.toml`.

- [ ] **Step 1: The script.** In `pyproject.toml`'s `[project.scripts]`,
after `kcgx-status`: `kcgx-web = "kcgx.server:main"`. Then `uv sync`.

- [ ] **Step 2: Tests.** Create `tests/test_server.py`:

```python
"""The server end to end, through Starlette's test client.

The station underneath is real; its feeds, listing and mixer are the same
fakes test_station.py uses, so nothing here touches the network, ffmpeg or
an audio device.
"""

from __future__ import annotations

import json

import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from kcgx.server import HOST, LocalOnly, create_app, main, parse_args
from kcgx.station import Station
from squelch.config import Config
from squelch.mixer import Mixer
from station_fakes import AIRPORTS, Builder, listing, picker

BASE = "http://127.0.0.1:8473"
# A full URL: the test client sends Host: testserver for a bare path.
WS = "ws://127.0.0.1:8473/ws"


def app(**kwargs):
    exits = []

    def factory(hub, post):
        return Station(
            Config(icao="KPDX", feed="kpdx3_twr"),
            hub,
            post=post,
            airports=AIRPORTS,
            mixer=Mixer(),
            feeds_loader=listing,
            sessions_builder=Builder(),
            picker_loader=picker,
            remember=lambda icao: None,
        )

    options = dict(level_hz=0, resort_seconds=0)
    options.update(kwargs)
    return create_app(
        station_factory=factory, initial_icao="KPDX", on_exit=lambda: exits.append(True), **options
    ), exits


def client(asgi, base=BASE):
    return TestClient(asgi, base_url=base)


def until(ws, predicate, limit=200):
    for _ in range(limit):
        frame = json.loads(ws.receive_text())
        if predicate(frame):
            return frame
    raise AssertionError("frame never arrived")


def loaded(frame):
    return frame["t"] == "snapshot" and not frame["loading"]


def ready(ws):
    """The snapshot with the feeds in it: the first frame, or a later one if
    the page connected while the airport was still loading."""
    first = json.loads(ws.receive_text())
    assert first["t"] == "snapshot", "the first frame must be a snapshot"
    return first if not first["loading"] else until(ws, loaded)


# -- answering local pages only ----------------------------------------------


def test_health_answers_once_up():
    asgi, _ = app()
    with client(asgi) as http:
        body = http.get("/api/health").json()
    assert body["ok"] is True
    assert body["icao"] == "KPDX"
    assert body["protocol"] == 1


@pytest.mark.parametrize("base", ["http://evil.example:8473", "http://192.168.1.20:8473"])
def test_a_request_naming_another_host_is_refused(base):
    asgi, _ = app()
    with client(asgi, base) as http:
        assert http.get("/api/health").status_code == 403


def test_localhost_is_this_machine_too():
    asgi, _ = app()
    with client(asgi, "http://localhost:8473") as http:
        assert http.get("/api/health").status_code == 200


def test_a_request_from_another_sites_page_is_refused():
    asgi, exits = app()
    with client(asgi) as http:
        response = http.post("/api/shutdown", headers={"origin": "http://evil.example"})
    assert response.status_code == 403
    assert exits == [], "a foreign page must not be able to shut the cockpit down"


def test_a_request_from_our_own_page_is_allowed():
    asgi, _ = app()
    with client(asgi) as http:
        assert http.get("/api/health", headers={"origin": BASE}).status_code == 200


def test_a_websocket_from_another_sites_page_is_refused():
    asgi, _ = app()
    with client(asgi) as http:
        with pytest.raises(WebSocketDisconnect):
            with http.websocket_connect(WS, headers={"origin": "http://evil.example"}) as ws:
                ws.receive_text()


def test_a_websocket_naming_another_host_is_refused():
    asgi, _ = app()
    with client(asgi) as http:
        with pytest.raises(WebSocketDisconnect):
            with http.websocket_connect("/ws") as ws:  # Host: testserver
                ws.receive_text()


def test_the_server_binds_to_this_machine_only():
    assert HOST == "127.0.0.1"


def test_the_guard_wraps_the_whole_app():
    asgi, _ = app()
    assert isinstance(asgi, LocalOnly)


# -- the WebSocket -------------------------------------------------------------


def test_the_first_frame_is_a_snapshot():
    asgi, _ = app()
    with client(asgi) as http, http.websocket_connect(WS) as ws:
        frame = ready(ws)
        assert [f["ident"] for f in frame["feeds"]] == ["kpdx3_twr", "kpdx3_gnd", "kpdx3_atis"]


def test_a_mute_from_one_page_reaches_another():
    asgi, _ = app()
    with client(asgi) as http, http.websocket_connect(WS) as a, http.websocket_connect(WS) as b:
        ready(a)
        ready(b)
        a.send_text(json.dumps({"t": "mute", "ident": "kpdx3_gnd"}))
        order = until(b, lambda f: f["t"] == "order")
        assert order["idents"] == ["kpdx3_twr", "kpdx3_gnd", "kpdx3_atis"]


def test_a_bad_message_gets_an_error_and_the_connection_stays():
    asgi, _ = app()
    with client(asgi) as http, http.websocket_connect(WS) as ws:
        ws.send_text("not json")
        error = until(ws, lambda f: f["t"] == "error")
        assert error["text"] == "not JSON"
        ws.send_text(json.dumps({"t": "volume", "value": 0.5}))
        assert until(ws, lambda f: f["t"] == "volume")["value"] == 0.5


def test_levels_stream_while_a_page_is_open():
    asgi, _ = app(level_hz=50)
    with client(asgi) as http, http.websocket_connect(WS) as ws:
        ready(ws)
        levels = until(ws, lambda f: f["t"] == "levels")
        assert set(levels["v"]) == {"kpdx3_twr", "kpdx3_gnd", "kpdx3_atis"}


# -- HTTP ----------------------------------------------------------------------


def test_the_debug_page_is_served():
    asgi, _ = app()
    with client(asgi) as http:
        response = http.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "/ws" in response.text


def test_airport_search_uses_the_dataset():
    asgi, _ = app()
    with client(asgi) as http:
        results = http.get("/api/airports", params={"q": "portland or"}).json()
    assert results[0]["icao"] == "KPDX"


def test_changing_airport_reaches_every_page():
    asgi, _ = app()
    with client(asgi) as http, http.websocket_connect(WS) as ws:
        ready(ws)
        assert http.post("/api/airport", json={"icao": "ksea"}).json() == {"icao": "KSEA"}
        frame = until(ws, lambda f: loaded(f) and f["airport"]["icao"] == "KSEA")
        assert [f["ident"] for f in frame["feeds"]] == ["ksea_twr", "ksea_gnd"]


def test_an_unknown_airport_is_a_404():
    asgi, _ = app()
    with client(asgi) as http:
        response = http.post("/api/airport", json={"icao": "ZZZZ"})
    assert response.status_code == 404


@pytest.mark.parametrize("body", [{}, {"icao": 7}, [1]])
def test_a_malformed_airport_request_is_a_400(body):
    asgi, _ = app()
    with client(asgi) as http:
        assert http.post("/api/airport", json=body).status_code == 400


def test_the_feed_picker_list_says_which_are_open():
    asgi, _ = app()
    with client(asgi) as http, http.websocket_connect(WS) as ws:
        ready(ws)
        listed = http.get("/api/feeds/available").json()
    assert {"ident": "kpdx_del", "label": "Delivery", "open": False} in listed


def test_shutdown_asks_the_server_to_exit():
    asgi, exits = app()
    with client(asgi) as http:
        assert http.post("/api/shutdown").status_code == 202
    assert exits == [True]


# -- the command ---------------------------------------------------------------


class FakeMixer:
    failed = False
    volume = 1.0

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.started = self.stopped = False

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def clear_channels(self):
        pass


def test_the_port_defaults_to_8473_and_follows_the_environment(monkeypatch):
    monkeypatch.delenv("KCGX_PORT", raising=False)
    assert parse_args([]).port == 8473
    monkeypatch.setenv("KCGX_PORT", "9000")
    assert parse_args([]).port == 9000


def test_no_ffmpeg_is_refused_before_anything_starts(capsys):
    assert main([], which=lambda name: None, serve=pytest.fail) == 2
    assert "ffmpeg" in capsys.readouterr().err


def test_an_unknown_airport_is_refused_before_anything_starts(capsys):
    code = main(["--icao", "ZZZZ"], which=lambda n: "/usr/bin/ffmpeg", serve=pytest.fail)
    assert code == 2
    assert "ZZZZ" in capsys.readouterr().err


def test_the_command_serves_and_closes_the_mixer_afterwards(monkeypatch, tmp_path):
    monkeypatch.setattr("squelch.config.DEFAULT_PATH", tmp_path / "missing.toml")
    served = {}
    mixers = []

    def factory(**kwargs):
        mixers.append(FakeMixer(**kwargs))
        return mixers[-1]

    def serve(asgi, port, on_server):
        served["port"] = port
        served["app"] = asgi

    code = main(
        ["--icao", "kpdx", "--port", "9100"],
        which=lambda n: "/usr/bin/ffmpeg",
        serve=serve,
        mixer_factory=factory,
        out=lambda line: None,
    )
    assert code == 0
    assert served["port"] == 9100
    assert isinstance(served["app"], LocalOnly)
    assert mixers[0].started and mixers[0].stopped
```

Two things about Starlette's test client these tests depend on, both found
the hard way. For a bare path, its WebSocket sends `Host: testserver`
whatever `base_url` says, so every WebSocket test uses the full `WS` URL;
`test_a_websocket_naming_another_host_is_refused` uses the bare path on
purpose. And it needs `httpx2` (Task 1).

- [ ] **Step 3:** Run; expect `ModuleNotFoundError: No module named 'kcgx.server'`.

- [ ] **Step 4: The debug page.** Create `src/kcgx/web/debug.html`. Plain
on purpose: it exists to drive the server until phase C replaces it, and
nothing in it is a design decision.

```html
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>kcgx debug</title>
<style>
  /* Deliberately plain: this page exists to drive the server until the
     real cockpit page (phase C) replaces it. */
  :root { color-scheme: dark; }
  body { margin: 0; padding: 16px; background: #000; color: #c4f0ff; font: 14px/1.4 ui-monospace, Menlo, monospace; }
  h1 { font-size: 16px; margin: 0 0 12px; }
  section { margin: 0 0 16px; }
  table { border-collapse: collapse; width: 100%; max-width: 900px; }
  td, th { padding: 4px 8px; border-bottom: 1px solid #1a2229; text-align: left; }
  td.num { text-align: right; font-variant-numeric: tabular-nums; }
  button { font: inherit; background: none; color: inherit; border: 1px solid #2f86ab; min-height: 32px; padding: 0 10px; cursor: pointer; }
  button[aria-pressed="true"] { border-color: #ff8fdc; color: #ff8fdc; }
  input { font: inherit; background: #000; color: inherit; border: 1px solid #2f86ab; padding: 4px; }
  #log { max-height: 200px; overflow: auto; white-space: pre-wrap; }
  #status { color: #7fa9be; }
</style>
</head>
<body>
<h1>kcgx debug <span id="status">connecting</span></h1>

<section aria-label="Airport">
  <div id="airport"></div>
  <form id="airport-form">
    <label>ICAO <input id="icao" size="6" autocomplete="off"></label>
    <button type="submit">Go</button>
  </form>
</section>

<section aria-label="Volume">
  <label>Volume <input id="volume" type="range" min="0" max="1" step="0.05"></label>
  <span id="volume-value"></span>
</section>

<section aria-label="Feeds">
  <table>
    <thead><tr><th>Feed</th><th>State</th><th class="num">Level dBFS</th><th class="num">Chatter</th><th>Controls</th></tr></thead>
    <tbody id="feeds"></tbody>
  </table>
  <p><button type="button" id="picker">Load feed list</button> <span id="available"></span></p>
</section>

<section aria-label="Log"><div id="log"></div></section>

<script>
"use strict";
const feeds = new Map();   // ident -> feed view
let order = [];
let socket = null;

function send(message) {
  if (socket && socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify(message));
}

function button(label, pressed, onClick) {
  const b = document.createElement("button");
  b.type = "button";
  b.textContent = label;
  b.setAttribute("aria-pressed", String(pressed));
  b.addEventListener("click", onClick);
  return b;
}

function render() {
  const body = document.getElementById("feeds");
  body.replaceChildren();
  for (const ident of order) {
    const f = feeds.get(ident);
    if (!f) continue;
    const row = document.createElement("tr");
    row.id = "feed-" + ident;
    const cells = [f.name + "  (" + ident + ")", f.state, "", Math.round(f.chatter * 100) + "%"];
    cells.forEach((text, i) => {
      const td = document.createElement("td");
      td.textContent = text;
      if (i >= 2) td.className = "num";
      if (i === 2) td.dataset.level = ident;
      row.append(td);
    });
    const controls = document.createElement("td");
    controls.append(
      button(f.muted ? "unmute" : "mute", !f.muted, () => send({t: "mute", ident})), " ",
      button("solo", f.soloed, () => send({t: "solo", ident})), " ",
      button("ambient", f.ambient, () => send({t: "ambient", ident})),
    );
    row.append(controls);
    body.append(row);
  }
}

function log(entry) {
  const el = document.getElementById("log");
  el.textContent += entry.z + "  " + entry.text + "\n";
  el.scrollTop = el.scrollHeight;
}

function receive(frame) {
  switch (frame.t) {
    case "snapshot": {
      feeds.clear();
      order = frame.feeds.map((f) => f.ident);
      frame.feeds.forEach((f) => feeds.set(f.ident, f));
      const a = frame.airport;
      document.getElementById("airport").textContent =
        a.icao + "  " + a.name + (frame.loading ? "  (loading feeds...)" : "") +
        (frame.audio_ok ? "" : "  NO AUDIO DEVICE");
      document.getElementById("volume").value = frame.volume;
      document.getElementById("volume-value").textContent = Math.round(frame.volume * 100) + "%";
      document.getElementById("log").textContent = "";
      frame.log.forEach(log);
      render();
      break;
    }
    case "feed": feeds.set(frame.feed.ident, frame.feed); render(); break;
    case "added": feeds.set(frame.feed.ident, frame.feed); order.push(frame.feed.ident); render(); break;
    case "order": order = frame.idents; render(); break;
    case "levels":
      for (const [ident, db] of Object.entries(frame.v)) {
        const td = document.querySelector('[data-level="' + ident + '"]');
        if (td) td.textContent = db.toFixed(1);
      }
      break;
    case "chatter":
      for (const [ident, value] of Object.entries(frame.v)) {
        const f = feeds.get(ident);
        if (f) f.chatter = value;
      }
      render();
      break;
    case "volume":
      document.getElementById("volume").value = frame.value;
      document.getElementById("volume-value").textContent = Math.round(frame.value * 100) + "%";
      break;
    case "message": log(frame); break;
    case "error": log({z: "PAGE", text: "error: " + frame.text}); break;
  }
}

function connect() {
  socket = new WebSocket("ws://" + location.host + "/ws");
  socket.addEventListener("open", () => { document.getElementById("status").textContent = "live"; });
  socket.addEventListener("message", (event) => receive(JSON.parse(event.data)));
  socket.addEventListener("close", () => {
    document.getElementById("status").textContent = "reconnecting";
    setTimeout(connect, 1000);
  });
}

document.getElementById("volume").addEventListener("input", (event) => {
  send({t: "volume", value: Number(event.target.value)});
});

document.getElementById("airport-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const icao = document.getElementById("icao").value.trim();
  const response = await fetch("/api/airport", {
    method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({icao}),
  });
  if (!response.ok) log({z: "PAGE", text: (await response.json()).error});
});

document.getElementById("picker").addEventListener("click", async () => {
  const list = await (await fetch("/api/feeds/available")).json();
  const holder = document.getElementById("available");
  holder.replaceChildren();
  list.filter((f) => !f.open).forEach((f) => {
    holder.append(button("open " + f.label, false, () => send({t: "open_feed", ident: f.ident})), " ");
  });
  if (!holder.childElementCount) holder.textContent = "every listed feed is open";
});

document.getElementById("feeds").addEventListener("pointerdown", () => send({t: "input"}));
connect();
</script>
</body>
</html>
```

- [ ] **Step 5: Implement.** Create `src/kcgx/server.py`:

```python
"""The local web server: HTTP for one-off things, one WebSocket for
everything live.

Binds to 127.0.0.1 and nowhere else, and answers only pages served from
itself (see LocalOnly). Audio plays on this machine through the mixer;
pages only ever receive state and levels.

    kcgx-web [--port 8473] [--icao KPDX]

Until phase C ships the real page, / serves a bare debug page that can
drive every control.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import os
import shutil
import sys
from collections.abc import Callable
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, PlainTextResponse
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocket, WebSocketDisconnect

from kcgx import protocol
from kcgx.airports import find, load_airports, search
from kcgx.hub import Client, Hub
from kcgx.state import current_icao
from kcgx.station import Station, UnknownAirport

HOST = "127.0.0.1"
DEFAULT_PORT = 8473
LEVEL_HZ = 25
RESORT_SECONDS = 5.0
WEB_DIR = Path(__file__).parent / "web"

StationFactory = Callable[[Hub, Callable[..., None]], Station]


# -- answering local pages only ----------------------------------------------


def _hostname(host: str) -> str:
    return host.rsplit(":", 1)[0] if ":" in host else host


class LocalOnly:
    """Refuse any request that did not come from a page this server served.

    A server on 127.0.0.1 is reachable by every page the browser opens, so
    two checks run on every HTTP request and WebSocket handshake:

    - Host must name this machine, which defeats DNS rebinding.
    - Origin, when there is one, must be this server itself, which stops
      another site's page muting your feeds or shutting the cockpit down.
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] in ("http", "websocket") and not self._allowed(scope):
            if scope["type"] == "http":
                response = PlainTextResponse("kcgx answers its own pages only", status_code=403)
                await response(scope, receive, send)
            else:
                await send({"type": "websocket.close", "code": 1008})
            return
        await self.app(scope, receive, send)

    @staticmethod
    def _allowed(scope) -> bool:
        headers = dict(scope.get("headers") or [])
        host = headers.get(b"host", b"").decode("latin-1")
        if _hostname(host) not in ("127.0.0.1", "localhost"):
            return False
        origin = headers.get(b"origin")
        return origin is None or origin.decode("latin-1") == f"http://{host}"


# -- the app -------------------------------------------------------------------


def create_app(
    *,
    station_factory: StationFactory,
    initial_icao: str,
    on_exit: Callable[[], None] = lambda: None,
    level_hz: float = LEVEL_HZ,
    resort_seconds: float = RESORT_SECONDS,
) -> Any:
    """The ASGI app. `station_factory(hub, post)` builds the Station once
    the event loop is running; `on_exit` is what POST /api/shutdown calls.
    A zero `level_hz` or `resort_seconds` turns that loop off (tests)."""

    @contextlib.asynccontextmanager
    async def lifespan(app):
        loop = asyncio.get_running_loop()

        def post(fn, *args):
            try:
                loop.call_soon_threadsafe(fn, *args)
            except RuntimeError:
                pass  # the loop has closed: shutting down, nobody to tell

        hub = Hub()
        station = station_factory(hub, post)
        app.state.hub, app.state.station = hub, station
        tasks = [asyncio.create_task(_guarded(hub, station.open(initial_icao)))]
        if level_hz:
            tasks.append(asyncio.create_task(_every(1 / level_hz, station.tick_levels)))
        if resort_seconds:
            tasks.append(asyncio.create_task(_every(resort_seconds, station.tick_resort)))
        try:
            yield
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            station.stop()

    async def page(request: Request):
        return FileResponse(WEB_DIR / "debug.html", media_type="text/html")

    async def health(request: Request):
        station = request.app.state.station
        return JSONResponse(
            {
                "ok": True,
                "version": _version(),
                "protocol": protocol.PROTOCOL,
                "icao": station.icao,
                "loading": station.loading,
            }
        )

    async def airports(request: Request):
        query = request.query_params.get("q", "")
        station = request.app.state.station
        return JSONResponse(
            [protocol.airport_view(a, a.icao) for a in search(query, station.airports)]
        )

    async def set_airport(request: Request):
        station = request.app.state.station
        try:
            body = await request.json()
            icao = body["icao"]
            if not isinstance(icao, str):
                raise TypeError
        except Exception:
            return JSONResponse({"error": "send {\"icao\": \"KPDX\"}"}, status_code=400)
        try:
            airport = station.check_airport(icao)
        except UnknownAirport:
            return JSONResponse({"error": f"no airport {icao!r}"}, status_code=404)
        # Not awaited: the listing fetch can take seconds of retries, and
        # every page hears about it over the WebSocket.
        asyncio.create_task(_guarded(station.hub, station.change_airport(airport.icao)))
        return JSONResponse({"icao": airport.icao}, status_code=202)

    async def available(request: Request):
        return JSONResponse(await request.app.state.station.available_feeds())

    async def shutdown(request: Request):
        on_exit()
        return JSONResponse({"ok": True}, status_code=202)

    async def live(websocket: WebSocket):
        hub, station = websocket.app.state.hub, websocket.app.state.station
        await websocket.accept()

        def evicted():
            asyncio.create_task(_close(websocket, 1013))

        client = Client(websocket.send_text, on_evict=evicted)
        # Queued before joining the hub, with no await between: the snapshot
        # is always the first frame, and nothing is broadcast in between.
        client.offer(protocol.encode(station.snapshot()))
        hub.add(client)
        pump = asyncio.create_task(client.pump())
        try:
            while True:
                text = await websocket.receive_text()
                try:
                    message = protocol.parse_client(text)
                except protocol.BadMessage as exc:
                    hub.send(client, protocol.error_frame(str(exc)))
                    continue
                station.handle(message)
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            hub.remove(client)
            pump.cancel()

    app = Starlette(
        routes=[
            Route("/", page),
            Route("/api/health", health),
            Route("/api/airports", airports),
            Route("/api/airport", set_airport, methods=["POST"]),
            Route("/api/feeds/available", available),
            Route("/api/shutdown", shutdown, methods=["POST"]),
            WebSocketRoute("/ws", live),
        ],
        lifespan=lifespan,
    )
    return LocalOnly(app)


async def _every(seconds: float, fn: Callable[[], None]) -> None:
    """Call `fn` every `seconds` until cancelled. A tick that raises is
    dropped, not fatal: one bad frame must not stop the meters for good."""
    while True:
        await asyncio.sleep(seconds)
        try:
            fn()
        except Exception:
            pass


async def _guarded(hub: Hub, work) -> None:
    try:
        await work
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        hub.note(f"{type(exc).__name__}: {exc}")


async def _close(websocket: WebSocket, code: int) -> None:
    try:
        await websocket.close(code=code)
    except Exception:
        pass


def _version() -> str:
    try:
        return version("squelch")
    except PackageNotFoundError:
        return "unknown"


# -- the command ---------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="kcgx-web", description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("KCGX_PORT", DEFAULT_PORT)),
        help=f"port on {HOST} (default {DEFAULT_PORT}, or $KCGX_PORT)",
    )
    parser.add_argument("--icao", help="start at this airport instead of the remembered one")
    return parser.parse_args(argv)


def _serve(app: Any, port: int, on_server: Callable[[Any], None]) -> None:
    import uvicorn

    server = uvicorn.Server(
        uvicorn.Config(app, host=HOST, port=port, log_level="warning", ws="websockets-sansio")
    )
    on_server(server)
    server.run()


def main(
    argv: list[str] | None = None,
    *,
    which: Callable[[str], str | None] = shutil.which,
    serve: Callable[..., None] = _serve,
    mixer_factory: Callable[..., Any] | None = None,
    out: Callable[[str], None] = print,
) -> int:
    from squelch.config import ConfigError, load_config
    from squelch.runtime import FFMPEG_MISSING

    args = parse_args(argv)
    if which("ffmpeg") is None:
        print(f"kcgx-web: {FFMPEG_MISSING}", file=sys.stderr)
        return 2
    try:
        config = load_config()
    except ConfigError as exc:
        print(f"kcgx-web: {exc}", file=sys.stderr)
        return 2

    known = load_airports()
    icao = (args.icao or current_icao(known=lambda i: find(i, known) is not None, warn=out)).upper()
    if find(icao, known) is None:
        print(f"kcgx-web: no airport {icao!r} in the dataset", file=sys.stderr)
        return 2

    if mixer_factory is None:
        from squelch.mixer import Mixer as mixer_factory
    mixer = mixer_factory(
        volume=config.master_volume,
        ambient_enabled=config.ambient_enabled,
        buffer_seconds=config.buffer_seconds,
    )
    mixer.start()

    holder: dict[str, Any] = {}
    app = create_app(
        station_factory=lambda hub, post: Station(
            config, hub, post=post, airports=known, mixer=mixer
        ),
        initial_icao=icao,
        on_exit=lambda: setattr(holder["server"], "should_exit", True),
    )
    out(f"kcgx: http://{HOST}:{args.port}/  ({icao})")
    try:
        serve(app, args.port, lambda server: holder.__setitem__("server", server))
    finally:
        mixer.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 6: Revert-check.**

| Break | Expected failure |
|---|---|
| `LocalOnly._allowed`'s last line → `return True` | `test_a_request_from_another_sites_page_is_refused` |
| delete the hostname check in `_allowed` | `test_a_request_naming_another_host_is_refused` (2 cases) and `test_a_websocket_naming_another_host_is_refused` |

- [ ] **Step 7:** Run `tests/test_server.py` three times; green every time.
Full suite → **871 passed**, with
`-W error::pytest.PytestUnraisableExceptionWarning` so a task that dies in
the background fails the run instead of printing a warning.
- [ ] **Step 8:** Commit `feat(kcgx): kcgx-web, the local server`.

---

### Task 9: By hand, on the Mac, with real audio

Stop the terminal cockpit first (`kcgx stop` in `/Users/mikelse/kcgx`), so
the two do not share LiveATC's seven streams.

- [ ] `uv run kcgx-web`. It prints `kcgx: http://127.0.0.1:8473/  (KPDX)`.
- [ ] Open that URL. The airport line fills in, feeds appear, levels move,
  and the tower is audible.
- [ ] Mute, unmute, solo, solo again (the mix comes back), ambient: each
  changes what you hear and moves the row as the terminal does.
- [ ] Open a second tab. Mute in one; the other follows within a frame.
- [ ] Close both tabs. **Audio keeps playing.** Reopen: the page comes back
  exactly as the server has it.
- [ ] Type `KSEA` and Go. The page says loading, Seattle's feeds arrive,
  Portland stops, and there is no click or gap from the audio device.
- [ ] Load feed list, open one that is not open: it appears, audible.
- [ ] Volume slider: the level you hear follows; a second tab's slider moves.
- [ ] `curl -s -X POST http://127.0.0.1:8473/api/shutdown`. The command exits 0.
- [ ] `curl -s -H 'Origin: http://evil.example' -X POST http://127.0.0.1:8473/api/shutdown` against a running server answers 403 and the server keeps running.

Anything that fails here is a bug in this phase, not in phase C.

---

### Task 10: Documentation

- [ ] **Step 1:** In the spec, write back the nine decisions at the top of this
  plan: "Transport" gets the protocol table above in place of its own;
  "The controller" drops `snapshot`, `levels` and `set_volume` from
  `Cockpit`'s methods (`stop` stays); "Threads" names `Station.post`;
  "Install changes" step 4 lists Starlette, uvicorn and websockets.
- [ ] **Step 2:** In `docs/README.md`, phase B links this plan and is marked built.
- [ ] **Step 3:** Commit `docs: phase B done`.

---

## Execution record

Built 2026-10-18 and 2026-10-19 on `feat/web-cockpit`, one commit per task,
from the dry-run files; full suite 871 passed on the branch. Task 9 on the
Mac, 2026-10-19: `kcgx-web` came up at KORD (the remembered airport), 30
feeds from the cached list, 7 streaming and 23 parked, and **the owner
confirmed the audio plays correctly through the server**. During the check
the debug page's controls became `[M]` `[S]` with ambient removed, and the
page is now served `no-cache` (commit b876b41). Task 10's spec write-back
is still to do.

## Self-Review Notes

- **Dry run, 2026-10-18.** Every file and snippet above was built in a
  scratch copy of the branch and run before this plan was written; the plan
  is generated from those files. Full suite **871 passed** in a Linux
  sandbox (its five PortAudio tests run against a stand-in `sounddevice`
  whose output never opens). Every revert-check listed was run and failed
  its named test. `kcgx-web` was started for real with uvicorn: health,
  the debug page, a WebSocket round trip (snapshot, volume, error frame),
  a foreign Origin refused at the handshake, a foreign Host refused over
  HTTP, and `/api/shutdown` exiting 0 within a second. Real audio and real
  LiveATC feeds were not possible there; Task 9 is where they get checked.
- **Two of my own expectations were wrong during the dry run, not the
  code.** A test assumed unmuting ATIS would put it first (tower was
  already audible, so it is second), and a timestamp assertion had the
  wrong hour. Both tests were corrected, and the corrected forms are what
  appear above.
- **Not in this phase, on purpose:** the radar poller (D), the real page
  (C), the launcher that backgrounds the server and opens a browser (E).
  `kcgx-web` runs in the foreground until E.
- **Test count:** 766 → 766 (T1) → 768 (T2) → 772 (T3) → 774 (T4) → 808 (T5)
  → 820 (T6) → 843 (T7) → 871 (T8).
