# Web Cockpit Phase A: Extract the Controller

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the cockpit's rules (stream slots, mute, solo, ambient, the
activity resort, opening a feed) out of `SquelchApp` into a UI free
`squelch.cockpit.Cockpit`, and make the terminal squelch drive it, with no
visible change in behaviour.

**Architecture:** `Cockpit` owns the stack order, the `Solo` recording, the
`Resorter` and the stream limit, and is addressed by feed ident. It tells its
owner what changed through one callback, `on_change(kind, payload)`, with four
kinds: `feed`, `order`, `added`, `message`. `SquelchApp` builds a `Cockpit` in
its constructor, forwards keys and clicks to it, and turns its events into
widget work (refresh a row, move rows, mount a row, log a message). Selection
stays in the app: it is per viewer, and phase B will have several viewers.

**Tech Stack:** Python 3.14, Textual 8.2.8, pytest (`asyncio_mode = "auto"`),
uv / `uv_build`.

**Spec:** `docs/superpowers/specs/2026-10-18-web-cockpit-design.md`, section
"The controller: the one real refactor".

## Global Constraints

- Python `>=3.14`. **No new runtime dependencies.** Phase B adds Starlette
  and uvicorn; this phase adds nothing.
- **`squelch/cockpit.py` must never import Textual, Rich, or anything from
  `squelch.app`, `squelch.rows`, `squelch.config_view` or `squelch.themes`.**
  Task 1 adds a test that enforces it.
- **Cockpit is single threaded by contract.** Every call comes from one
  thread: Textual's event loop now, the server's asyncio loop in phase B.
  Session threads never call into it.
- Run everything through uv from the repo root:
  `cd /Users/mikelse/kcgx && uv run --project . pytest -q`
- The suite is **732 tests** at the start of this plan and must stay green.
  On a machine without PortAudio, the five `tests/test_main.py` tests that
  build a real `Mixer` fail with `OSError: PortAudio library not found`;
  that is the environment, not the change. Run the suite on the Mac.
- **The existing tests are the gate and are not edited.** Not one line of
  `tests/test_app.py`, `tests/test_feed_picker.py`, `tests/test_config_view.py`
  or `tests/test_main.py` changes in this plan. Task 6 checks
  `git diff --stat main -- tests/` lists only `tests/test_cockpit.py`.
  They test the terminal app end to end, which is exactly what must not
  change; they retire with the terminal UI in phase E, and
  `tests/test_cockpit.py` stays.
- **Revert-check every new test**: `git diff` clean before each break, ONE
  break at a time, run the single named test, record the actual output,
  restore with `git checkout --`, confirm `git diff` empty. Never document a
  transcript you have not literally just observed.
- **Purge bytecode around every break and every restore:**
  `find . -name __pycache__ -not -path './.venv/*' -exec rm -rf {} +`
  A same size edit inside the same second leaves a stale `.pyc` valid.
- **No test may write to `~/.local/state/kcgx/` or `~/.cache/squelch/`.**
- The repo owner may have a live cockpit running. Nothing in this plan needs
  tmux; do not start one.
- The repo owner commits from a parallel session. Scope every `git add` to
  files you changed; leave untracked files alone.
- Commit after every task. End each message with:
  ```
  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  ```

---

## File Structure

**Create:**

| Path | Responsibility |
|---|---|
| `src/squelch/cockpit.py` | `Cockpit` and the four event kinds |
| `tests/test_cockpit.py` | the cockpit's rules, no Textual |

**Modify:**

| Path | Change |
|---|---|
| `src/squelch/app.py` | drive `Cockpit`; keep selection, rendering, timers, overlays |
| `docs/superpowers/specs/2026-10-18-web-cockpit-design.md` | phase A gate wording (Task 7) |
| `docs/README.md` | phase A status (Task 7) |

**Not modified:** `src/squelch/__main__.py`. Its `finally` reads
`app._sessions`, which stays (as a property) and keeps meaning "every session,
including any opened after startup".

## Interfaces at the end of phase A

```python
# src/squelch/cockpit.py
FEED = "feed"        # payload: the session whose state, mute, solo or ambient changed
ORDER = "order"      # payload: list of sessions, the new stack order
ADDED = "added"      # payload: the session just appended (not yet started)
MESSAGE = "message"  # payload: str, a warning for the log

class Cockpit:
    def __init__(self, config, sessions, *, feed_opener=None,
                 on_change=None, clock=time.monotonic) -> None
    config: Config
    feed_opener: Callable[[Feed], session] | None
    on_change: Callable[[str, object], None]
    max_streams: int            # config.max_streams, at least 1
    solo: Solo
    resorter: Resorter
    sessions -> list            # property; a copy, in stack order
    def session(self, ident: str) -> session | None
    def audible_count(self) -> int
    def start(self) -> None
    def reconcile_streams(self) -> None
    def toggle_mute(self, ident: str) -> bool     # False if unknown or refused
    def toggle_solo(self, ident: str) -> bool
    def toggle_ambient(self, ident: str) -> bool
    def ranked(self) -> list
    def tick_resort(self) -> None
    def note_input(self) -> None
    def open_feed(self, feed: Feed) -> session | None
```

`snapshot()`, `levels()`, `set_volume()` and `stop()` from the spec are
phase B: nothing in the terminal app needs them, and they are best designed
against the server that consumes them.

---

### Task 0: Branch and commit the design

- [x] **Step 1:** Branch `feat/web-cockpit` from `main` (5dcf0c7), checked out as a
  worktree at `/Users/mikelse/kcgx_web` so the terminal cockpit in
  `/Users/mikelse/kcgx` keeps running on `main` meanwhile.
- [ ] **Step 2:** Commit the spec, `docs/README.md` and this plan:
  ```
  git add docs/superpowers/specs/2026-10-18-web-cockpit-design.md \
          docs/superpowers/plans/2026-10-18-web-cockpit-a-controller.md \
          docs/README.md
  git commit -m "docs: web cockpit spec and phase A plan"
  ```
- [ ] **Step 3:** **Do not commit `war_games_examples/`.** They are stills from
  a 1983 film and the repository is public. Add the folder to `.gitignore`
  in the same commit, so it stays local reference without being
  redistributed:
  ```
  printf '\n# Reference stills for the web cockpit spec; not ours to publish.\nwar_games_examples/\n' >> .gitignore
  git add .gitignore && git commit --amend --no-edit
  ```

---

### Task 1: The cockpit's shape

Construction, lookup by ident, the event callback, and the guard that keeps
Textual out.

**Files:** Create `src/squelch/cockpit.py`, `tests/test_cockpit.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_cockpit.py`:

```python
"""The cockpit's rules, with no UI anywhere near them.

Everything here used to be reachable only through a running Textual app.
These tests drive the same rules directly, which is what the browser front
end will do in phase B. The terminal app's own tests (tests/test_app.py)
still cover the same behaviour end to end; this file is what remains when
the terminal UI is retired.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from squelch.activity import QUIET_SECONDS, SETTLE_ROUNDS
from squelch.cockpit import ADDED, FEED, MESSAGE, ORDER, Cockpit
from squelch.config import Config
from squelch.feeds import Feed


class FakeSession:
    def __init__(self, ident, label, *, muted=True, state="live"):
        self.feed = Feed(ident=ident, label=label)
        self.name = label.replace("KPDX ", "")
        self.muted = muted
        self.state = state
        self.ambient = False
        self.soloed = False
        self.activity = 0.0
        self.connected = True
        self.starts = 0

    def start(self):
        self.connected = True
        self.state = "live"
        self.starts += 1

    def park(self):
        self.connected = False
        self.state = "parked"

    def toggle_mute(self):
        self.muted = not self.muted
        return self.muted

    def toggle_ambient(self):
        self.ambient = not self.ambient
        return self.ambient


NAMES = [
    ("kpdx3_twr", "KPDX Tower (Both)"),
    ("kpdx3_gnd", "KPDX Ground"),
    ("kpdx_app_124350", "KPDX Approach (Final) #1"),
    ("kpdx3_atis", "KPDX ATIS"),
    ("kpdx3_del", "KPDX Clearance Delivery"),
]


def stack(n, *, audible=(0,), connected=True):
    out = []
    for i in range(n):
        ident, label = NAMES[i % len(NAMES)]
        if i >= len(NAMES):
            ident, label = f"{ident}_{i}", f"{label} #{i}"
        session = FakeSession(ident, label, muted=i not in audible)
        if not connected:
            session.connected = False
            session.state = "starting"
        out.append(session)
    return out


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class Recorder:
    def __init__(self):
        self.events = []

    def __call__(self, kind, payload):
        self.events.append((kind, payload))

    def of(self, kind):
        return [payload for k, payload in self.events if k == kind]

    @property
    def messages(self):
        return self.of(MESSAGE)


def make(n=3, *, limit=7, audible=(0,), connected=True, opener=None):
    rec, clock = Recorder(), Clock()
    cockpit = Cockpit(
        Config(icao="KPDX", feed="kpdx3_twr", max_streams=limit),
        stack(n, audible=audible, connected=connected),
        feed_opener=opener,
        on_change=rec,
        clock=clock,
    )
    return cockpit, rec, clock


def ident(cockpit, index):
    return cockpit.sessions[index].feed.ident


# -- shape -----------------------------------------------------------------


def test_importing_the_cockpit_does_not_import_textual():
    """The point of the module. A stray import would make the browser
    server pay for Textual, and would be the first step back to rules that
    only a terminal app can reach."""
    probe = "import sys, squelch.cockpit; sys.exit('textual' in sys.modules)"
    result = subprocess.run([sys.executable, "-c", probe])
    assert result.returncode == 0, "squelch.cockpit pulled in textual"


def test_sessions_keep_the_order_given():
    cockpit, _, _ = make(3)
    assert [s.feed.ident for s in cockpit.sessions] == [
        "kpdx3_twr", "kpdx3_gnd", "kpdx_app_124350",
    ]


def test_sessions_is_a_copy():
    cockpit, _, _ = make(3)
    cockpit.sessions.reverse()
    assert ident(cockpit, 0) == "kpdx3_twr"


def test_a_feed_is_found_by_ident_and_an_unknown_one_is_none():
    cockpit, _, _ = make(3)
    assert cockpit.session("kpdx3_gnd") is cockpit.sessions[1]
    assert cockpit.session("nope") is None


def test_duplicate_idents_are_refused():
    """Every action is addressed by ident. Two feeds sharing one would make
    a mute ambiguous; parse_airport_page already de-duplicates, so this can
    only be a programming error, and it should be loud."""
    twins = [FakeSession("a", "A"), FakeSession("a", "A again")]
    with pytest.raises(ValueError, match="a"):
        Cockpit(Config(), twins)


def test_a_stream_limit_of_zero_is_treated_as_one():
    """Zero would park everything, including the feed you are listening to,
    and look exactly like a dead network."""
    cockpit, _, _ = make(2, limit=0)
    assert cockpit.max_streams == 1


def test_every_session_starts_unsoloed():
    sessions = stack(2)
    sessions[0].soloed = True
    Cockpit(Config(), sessions)
    assert not any(s.soloed for s in sessions)
```

- [ ] **Step 2: Run them and watch them fail**

`uv run --project . pytest tests/test_cockpit.py -q`
Expected: collection error, `ModuleNotFoundError: No module named 'squelch.cockpit'`.

- [ ] **Step 3: Write the module**

Create `src/squelch/cockpit.py`:

```python
"""The cockpit's behaviour, with no UI in it.

Which feeds hold one of LiveATC's streams, what solo restores, when the
stack may reorder, what opening a feed does. All of it used to live inside
SquelchApp, where only a running Textual app could reach it. The browser
front end needs exactly the same rules, so they live here and both front
ends drive them.

Feeds are addressed by ident, never by position or by id(session): a
browser cannot hold a Python object id, and a position is exactly what
reordering changes.

Single threaded by contract. Every call comes from one thread: Textual's
event loop today, the server's asyncio loop later. Session threads never
call in; their state changes still reach the UI through SessionEvents.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from typing import Any

from squelch import slots
from squelch.activity import Resorter, rank
from squelch.config import Config
from squelch.feeds import Feed
from squelch.solo import Solo

FEED = "feed"
ORDER = "order"
ADDED = "added"
MESSAGE = "message"

Listener = Callable[[str, Any], None]


def _ignore(kind: str, payload: Any) -> None:
    pass


class Cockpit:
    """Feeds, mix and ordering for one airport."""

    def __init__(
        self,
        config: Config,
        sessions: Sequence,
        *,
        feed_opener: Callable[[Feed], Any] | None = None,
        on_change: Listener | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._sessions = list(sessions)
        idents = [s.feed.ident for s in self._sessions]
        duplicates = sorted({i for i in idents if idents.count(i) > 1})
        if duplicates:
            raise ValueError(f"duplicate feed idents: {', '.join(duplicates)}")
        self.config = config
        self.feed_opener = feed_opener
        self.on_change: Listener = on_change or _ignore
        # At least one: a limit of zero would park everything, including the
        # feed you are listening to, and look exactly like a dead network.
        self.max_streams = max(1, config.max_streams)
        self.solo = Solo()
        self.resorter = Resorter(clock=clock)
        for session in self._sessions:
            session.soloed = False

    # -- reading -------------------------------------------------------

    @property
    def sessions(self) -> list:
        """Every session, in stack order. A copy: reorder through the
        cockpit, never by editing this."""
        return list(self._sessions)

    def session(self, ident: str):
        for session in self._sessions:
            if session.feed.ident == ident:
                return session
        return None

    # -- telling the owner ---------------------------------------------

    def _emit(self, kind: str, payload: Any) -> None:
        self.on_change(kind, payload)

    def warn(self, message: str) -> None:
        self._emit(MESSAGE, message)
```

- [ ] **Step 4: Run them and watch them pass**

`uv run --project . pytest tests/test_cockpit.py -q` → `7 passed`.

- [ ] **Step 5: Revert-check**

| Break | Expected failure |
|---|---|
| add `import textual` at the top of `cockpit.py` | `test_importing_the_cockpit_does_not_import_textual` |
| delete the `if duplicates: raise` lines | `test_duplicate_idents_are_refused` |
| `max(1, config.max_streams)` → `config.max_streams` | `test_a_stream_limit_of_zero_is_treated_as_one` |

- [ ] **Step 6: Full suite, then commit**

`uv run --project . pytest -q` → 739 passed.
`git add src/squelch/cockpit.py tests/test_cockpit.py && git commit -m "feat(squelch): Cockpit shell, addressed by feed ident"`

---

### Task 2: Stream slots

`start`, `reconcile_streams`, the parked notice, and the audible limit.
Moved from `SquelchApp.start_streams`, `reconcile_streams`, `_audible_count`
and `_refuse_over_limit`, with one difference: parking and starting now
announce themselves as `feed` events, so the owner redraws the row. The app
used to call `set_state` by hand because the session's own event marshals
with `call_from_thread`, which refuses to run on the UI thread.

**Files:** Modify `src/squelch/cockpit.py`, `tests/test_cockpit.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_cockpit.py`:

```python
# -- stream slots ----------------------------------------------------------


def test_start_connects_no_more_than_the_limit_and_parks_the_rest():
    cockpit, rec, _ = make(5, limit=3, connected=False)
    cockpit.start()
    connected = [s for s in cockpit.sessions if s.connected]
    parked = [s for s in cockpit.sessions if s.state == "parked"]
    assert len(connected) == 3
    assert len(parked) == 2
    assert not any(s.starts for s in parked), "a parked feed was started"
    assert cockpit.session("kpdx3_twr").connected, "the audible feed must play"
    assert any("2 parked" in m for m in rec.messages), rec.messages


def test_no_parking_notice_when_everything_fits():
    cockpit, rec, _ = make(3, limit=7, connected=False)
    cockpit.start()
    assert all(s.connected for s in cockpit.sessions)
    assert not any("parked" in m for m in rec.messages)


def test_parking_and_starting_are_announced_per_feed():
    """The owner has no other way to learn a row changed: park() runs on
    the caller's thread, where the session's own event cannot be
    delivered."""
    cockpit, rec, _ = make(5, limit=3, connected=False)
    cockpit.start()
    announced = rec.of(FEED)
    assert set(map(id, announced)) == set(map(id, cockpit.sessions))


def test_unmuting_a_parked_feed_takes_the_quietest_muted_slot():
    cockpit, _, _ = make(5, limit=3, connected=False)
    cockpit.start()
    held = [s for s in cockpit.sessions if s.connected and s.muted]
    held[0].activity, held[1].activity = 0.5, 0.0
    quietest = held[1]
    target = next(s for s in cockpit.sessions if not s.connected)
    assert cockpit.toggle_mute(target.feed.ident) is True
    assert target.muted is False
    assert target.connected, "an unmuted feed must hold a stream"
    assert not quietest.connected, "the quietest muted feed should yield"
    assert sum(s.connected for s in cockpit.sessions) == 3


def test_unmuting_past_the_limit_is_refused_and_explained():
    cockpit, rec, _ = make(4, limit=2, audible=(0, 1), connected=False)
    cockpit.start()
    target = next(s for s in cockpit.sessions if s.muted)
    assert cockpit.toggle_mute(target.feed.ident) is False
    assert target.muted is True
    assert cockpit.audible_count() == 2
    assert any(
        "2 feeds already audible" in m and target.name in m
        for m in rec.messages
    ), rec.messages


def test_muting_is_never_refused_at_the_limit():
    cockpit, _, _ = make(4, limit=2, audible=(0, 1), connected=False)
    cockpit.start()
    target = next(s for s in cockpit.sessions if not s.muted)
    assert cockpit.toggle_mute(target.feed.ident) is True
    assert target.muted is True


def test_an_unknown_ident_changes_nothing_and_says_nothing():
    cockpit, rec, _ = make(3)
    assert cockpit.toggle_mute("nope") is False
    assert rec.events == []
```

- [ ] **Step 2: Run them and watch them fail**

`uv run --project . pytest tests/test_cockpit.py -q`
Expected: 7 new failures with `AttributeError: 'Cockpit' object has no attribute 'start'`
(and `toggle_mute`, `audible_count`).

- [ ] **Step 3: Implement**

Add to `Cockpit` in `src/squelch/cockpit.py`. `toggle_mute` appears here in
its final form; Task 3 adds the solo and ordering helpers it calls, so add
those two stubs now and fill them in there:

```python
    # -- stream slots --------------------------------------------------

    def audible_count(self) -> int:
        return sum(1 for s in self._sessions if not s.muted)

    def start(self) -> None:
        """Connect the feeds that get a slot, and say why the rest wait.

        An airport can publish four times as many feeds as LiveATC will
        stream to one address.
        """
        self.reconcile_streams()
        parked = sum(1 for s in self._sessions if not s.connected)
        if parked:
            self.warn(
                f"LiveATC streams {self.max_streams} feeds at once — "
                f"{parked} parked (‖). Unmute one to bring it in; "
                f"the quietest muted feed gives up its place."
            )

    def reconcile_streams(self) -> None:
        """Park and connect feeds until the slots match slots.plan().

        Parking first, so the stream count never goes over the limit even
        for the moment between the two: that moment is a connection LiveATC
        resets.
        """
        wanted = {
            id(s)
            for s in slots.plan(
                self._sessions,
                self.max_streams,
                audible_of=lambda s: not s.muted,
                connected_of=lambda s: s.connected,
                activity_of=lambda s: s.activity,
            )
        }
        for session in self._sessions:
            # Also parks a feed never started, so it says "parked" rather
            # than sitting on "starting" for a start that is not coming.
            if id(session) not in wanted and (
                session.connected or session.state != "parked"
            ):
                session.park()
                self._emit(FEED, session)
        for session in self._sessions:
            if not session.connected and id(session) in wanted:
                session.start()
                self._emit(FEED, session)

    def _refuse_over_limit(self, session) -> bool:
        """Warn and return True if unmuting `session` would need a slot
        that only another audible feed could give up."""
        if not session.muted or self.audible_count() < self.max_streams:
            return False
        self.warn(
            f"{self.max_streams} feeds already audible — LiveATC's limit. "
            f"Mute one to hear {session.name}."
        )
        return True

    # -- the mix -------------------------------------------------------

    def toggle_mute(self, ident: str) -> bool:
        session = self.session(ident)
        if session is None:
            return False
        if self.solo.active:
            # A mute by hand is a new intent, so the mix solo recorded is no
            # longer the one to come back to.
            self.solo.cancel()
            self._mark_solo()
        if self._refuse_over_limit(session):
            return False
        session.toggle_mute()
        self.reconcile_streams()
        self._emit(FEED, session)
        self._reorder_now()
        return True

    def _mark_solo(self) -> None:          # Task 3
        pass

    def _reorder_now(self) -> None:        # Task 3
        pass
```

**Keep the message text byte for byte**, em dashes included:
`tests/test_app.py` asserts on `"2 parked"`, `"Mute one"` and `"muted"`, and
it is not edited in this plan.

- [ ] **Step 4:** `uv run --project . pytest tests/test_cockpit.py -q` → `14 passed`.

- [ ] **Step 5: Revert-check**

| Break | Expected failure |
|---|---|
| delete `self._emit(FEED, session)` after `session.park()` | `test_parking_and_starting_are_announced_per_feed` |
| `if parked:` → `if parked > 2:` | `test_start_connects_no_more_than_the_limit_and_parks_the_rest` |
| in `_refuse_over_limit`, `return True` → `return False` | `test_unmuting_past_the_limit_is_refused_and_explained` |
| drop `not session.muted or` from `_refuse_over_limit` | `test_muting_is_never_refused_at_the_limit` |

- [ ] **Step 6:** Full suite → 746 passed. Commit
`feat(squelch): stream slots and the audible limit in Cockpit`.

---

### Task 3: Mute, solo, ambient and the immediate reorder

**Files:** Modify `src/squelch/cockpit.py`, `tests/test_cockpit.py`

- [ ] **Step 1: Write the failing tests**

Append:

```python
# -- the mix ---------------------------------------------------------------


def mutes(cockpit):
    return [s.muted for s in cockpit.sessions]


def by(cockpit, idents):
    return [cockpit.session(i) for i in idents]


def test_unmuting_lifts_a_feed_to_the_top_at_once():
    cockpit, rec, _ = make(3, audible=())
    target = ident(cockpit, 2)
    cockpit.toggle_mute(target)
    assert rec.of(ORDER), "an unmute must reorder without waiting to settle"
    assert rec.of(ORDER)[-1][0].feed.ident == target
    assert ident(cockpit, 0) == target


def test_muting_drops_it_back_in_on_activity():
    cockpit, _, _ = make(3, audible=(0,))
    s0, s1, s2 = cockpit.sessions
    s0.activity, s1.activity, s2.activity = 0.5, 0.9, 0.1
    cockpit.toggle_mute(s0.feed.ident)
    assert cockpit.sessions == [s1, s0, s2]


def test_the_feed_event_comes_before_the_order_event():
    """The owner redraws the row, then moves it. The other way round, a
    row would be moved to its new place still drawn in its old shape."""
    cockpit, rec, _ = make(3, audible=())
    cockpit.toggle_mute(ident(cockpit, 1))
    kinds = [k for k, _ in rec.events]
    assert kinds.index(FEED) < kinds.index(ORDER)


def test_an_immediate_reorder_is_not_proposed_again():
    cockpit, rec, _ = make(3, audible=(0,))
    cockpit.sessions[1].activity = 0.9
    cockpit.toggle_mute(ident(cockpit, 0))
    after = cockpit.sessions
    for _ in range(SETTLE_ROUNDS + 1):
        cockpit.tick_resort()
    assert len(rec.of(ORDER)) == 1, "the applied order was proposed again"
    assert cockpit.sessions == after


def test_solo_mutes_every_other_feed():
    cockpit, _, _ = make(3, audible=(0,))
    target = ident(cockpit, 1)
    assert cockpit.toggle_solo(target) is True
    assert [s.muted for s in cockpit.sessions if s.feed.ident != target] == [True, True]
    assert cockpit.session(target).muted is False


def test_solo_restores_the_prior_mix_including_other_unmuted_feeds():
    cockpit, _, _ = make(3, audible=(0, 1))
    before = {s.feed.ident: s.muted for s in cockpit.sessions}
    target = "kpdx_app_124350"
    cockpit.toggle_solo(target)
    cockpit.toggle_solo(target)
    assert {s.feed.ident: s.muted for s in cockpit.sessions} == before


def test_moving_the_solo_then_disengaging_returns_to_the_pre_solo_mix():
    cockpit, _, _ = make(4, audible=(0,))
    before = {s.feed.ident: s.muted for s in cockpit.sessions}
    cockpit.toggle_solo("kpdx3_gnd")
    cockpit.toggle_solo("kpdx3_atis")
    cockpit.toggle_solo("kpdx3_atis")
    assert {s.feed.ident: s.muted for s in cockpit.sessions} == before


def test_muting_by_hand_during_solo_cancels_it():
    cockpit, _, _ = make(3, audible=(0,))
    cockpit.toggle_solo("kpdx3_gnd")
    assert cockpit.solo.active is True
    cockpit.toggle_mute("kpdx3_twr")
    assert cockpit.solo.active is False, "a manual mute is a new intent"
    assert not any(s.soloed for s in cockpit.sessions)


def test_only_the_soloed_feed_is_marked():
    cockpit, _, _ = make(3, audible=(0,))
    cockpit.toggle_solo("kpdx3_gnd")
    assert [s.feed.ident for s in cockpit.sessions if s.soloed] == ["kpdx3_gnd"]


def test_solo_puts_the_soloed_feed_on_top():
    cockpit, _, _ = make(3, audible=(0,))
    cockpit.toggle_solo("kpdx_app_124350")
    assert ident(cockpit, 0) == "kpdx_app_124350"


def test_soloing_a_parked_feed_connects_it():
    cockpit, _, _ = make(5, limit=3, connected=False)
    cockpit.start()
    target = next(s for s in cockpit.sessions if not s.connected)
    cockpit.toggle_solo(target.feed.ident)
    assert target.connected
    assert sum(s.connected for s in cockpit.sessions) == 3


def test_ambient_toggles_only_its_feed_and_leaves_mute_alone():
    cockpit, rec, _ = make(3, audible=(0,))
    before = mutes(cockpit)
    assert cockpit.toggle_ambient("kpdx3_gnd") is True
    assert [s.ambient for s in cockpit.sessions] == [False, True, False]
    assert mutes(cockpit) == before
    assert rec.of(FEED) == [cockpit.session("kpdx3_gnd")]
```

- [ ] **Step 2:** Run; expect `AttributeError` for `toggle_solo`,
`toggle_ambient`, `tick_resort`, and order assertions failing against the
Task 2 stubs.

- [ ] **Step 3: Implement**

Replace the two stubs and add the rest:

```python
    def toggle_solo(self, ident: str) -> bool:
        session = self.session(ident)
        if session is None:
            return False
        if self.solo.is_soloed(ident):
            restored = self.solo.disengage()
            if restored is not None:
                self._apply_mix(restored)
        else:
            states = {s.feed.ident: s.muted for s in self._sessions}
            self._apply_mix(self.solo.engage(ident, states))
        # Solo can move audibility to a parked feed, and returning from it
        # can move it back to several. The restored mix fit the limit when
        # it was recorded, because every unmute along the way was checked.
        self.reconcile_streams()
        self._mark_solo()
        for s in self._sessions:
            self._emit(FEED, s)
        self._reorder_now()
        return True

    def toggle_ambient(self, ident: str) -> bool:
        session = self.session(ident)
        if session is None:
            return False
        session.toggle_ambient()
        self._emit(FEED, session)
        return True

    def _apply_mix(self, states: dict) -> None:
        for s in self._sessions:
            if s.feed.ident in states:
                s.muted = states[s.feed.ident]

    def _mark_solo(self) -> None:
        for s in self._sessions:
            s.soloed = self.solo.is_soloed(s.feed.ident)

    # -- ordering ------------------------------------------------------

    def ranked(self) -> list:
        """Audible feeds on top, each group ordered by activity."""
        return rank(
            self._sessions,
            lambda s: s.activity,
            audible_of=lambda s: not s.muted,
        )

    def _apply_order(self, order: Sequence) -> None:
        self._sessions = list(order)
        self._emit(ORDER, self.sessions)

    def _reorder_now(self) -> None:
        """Apply the ranking at once, skipping the settle delay.

        The debounce exists so activity drifting underneath you cannot move a
        row between deciding to click it and clicking it. A mute change is
        not that: the move is the direct result of the key you just pressed.
        The Resorter is told, so it does not spend three rounds proposing
        the order already applied.
        """
        order = self.ranked()
        self._apply_order(order)
        self.resorter.adopt(order)

    def tick_resort(self) -> None:         # Task 4
        pass
```

- [ ] **Step 4:** `pytest tests/test_cockpit.py -q` → `26 passed`.

- [ ] **Step 5: Revert-check**

| Break | Expected failure |
|---|---|
| delete `self.solo.cancel()` in `toggle_mute` | `test_muting_by_hand_during_solo_cancels_it` |
| delete `self.resorter.adopt(order)` | stays green until Task 4 makes `tick_resort` real; **run this break again at the end of Task 4** and expect `test_an_immediate_reorder_is_not_proposed_again` |
| swap `self._emit(FEED, session)` and `self._reorder_now()` in `toggle_mute` | `test_the_feed_event_comes_before_the_order_event` |
| delete `self.reconcile_streams()` in `toggle_solo` | `test_soloing_a_parked_feed_connects_it` |

- [ ] **Step 6:** Full suite → 758 passed. Commit
`feat(squelch): mute, solo and ambient in Cockpit`.

---

### Task 4: The settled resort

**Files:** Modify `src/squelch/cockpit.py`, `tests/test_cockpit.py`

- [ ] **Step 1: Write the failing tests**

```python
# -- resorting ---------------------------------------------------------------


def test_the_stack_reorders_busiest_first_once_settled():
    cockpit, rec, _ = make(3, audible=())
    s0, s1, s2 = cockpit.sessions
    s0.activity, s1.activity, s2.activity = 0.1, 0.9, 0.5
    for _ in range(SETTLE_ROUNDS):
        cockpit.tick_resort()
    assert cockpit.sessions == [s1, s2, s0]
    assert rec.of(ORDER)[-1] == [s1, s2, s0]


def test_one_tick_is_not_enough_to_reorder():
    cockpit, rec, _ = make(3, audible=())
    original = cockpit.sessions
    cockpit.sessions[1].activity = 0.9
    cockpit.tick_resort()
    assert cockpit.sessions == original
    assert rec.of(ORDER) == []


def test_input_holds_a_settled_resort_until_the_hand_comes_off():
    cockpit, rec, clock = make(3, audible=())
    original = cockpit.sessions
    original[1].activity = 0.9
    for _ in range(SETTLE_ROUNDS - 1):
        cockpit.tick_resort()
    cockpit.note_input()
    cockpit.tick_resort()
    assert cockpit.sessions == original, "the stack must not move under a hand"
    clock.now += QUIET_SECONDS + 0.1
    cockpit.tick_resort()
    assert ident(cockpit, 0) == original[1].feed.ident
```

- [ ] **Step 2:** Run; expect the first and third to fail against the stub.

- [ ] **Step 3: Implement**

```python
    def tick_resort(self) -> None:
        """Called every few seconds by the owner. Applies a new order only
        once it has held for SETTLE_ROUNDS and nobody has touched the stack
        for QUIET_SECONDS."""
        order = self.resorter.propose(self.ranked())
        if order is not None:
            self._apply_order(order)

    def note_input(self) -> None:
        """The viewer touched the stack: a key, a click, a hover."""
        self.resorter.note_input()
```

- [ ] **Step 4:** `pytest tests/test_cockpit.py -q` → `29 passed`.

- [ ] **Step 5: Revert-check**

| Break | Expected failure |
|---|---|
| make `note_input` a bare `pass` | `test_input_holds_a_settled_resort_until_the_hand_comes_off` |
| replace the body of `tick_resort` with `self._apply_order(self.ranked())` | `test_one_tick_is_not_enough_to_reorder` |
| (from Task 3) delete `self.resorter.adopt(order)` | `test_an_immediate_reorder_is_not_proposed_again` |

- [ ] **Step 6:** Full suite → 761 passed. Commit
`feat(squelch): settled resort in Cockpit`.

---

### Task 5: Opening a feed

**Files:** Modify `src/squelch/cockpit.py`, `tests/test_cockpit.py`

- [ ] **Step 1: Write the failing tests**

```python
# -- opening a feed ----------------------------------------------------------


ATIS = Feed(ident="kpdx3_atis", label="KPDX ATIS")


def late_session(muted=False):
    session = FakeSession("kpdx3_atis", "KPDX ATIS", muted=muted)
    session.connected = False
    session.state = "starting"
    return session


def test_without_an_opener_it_says_so_rather_than_pretending():
    cockpit, rec, _ = make(2)
    assert cockpit.open_feed(ATIS) is None
    assert rec.messages == ["kpdx3_atis is not open"]
    assert rec.of(ADDED) == []


def test_a_feed_that_will_not_open_warns_instead_of_raising():
    def boom(feed):
        raise RuntimeError("boom")

    cockpit, rec, _ = make(2, opener=boom)
    assert cockpit.open_feed(ATIS) is None
    assert rec.messages == ["could not open kpdx3_atis: boom"]


def test_an_opened_feed_is_added_before_it_is_started():
    """The owner needs somewhere to put the feed's first state change, and
    a session's opening act can be a warning."""
    late = late_session()
    cockpit, rec, _ = make(2, opener=lambda feed: late)
    assert cockpit.open_feed(ATIS) is late
    assert cockpit.sessions[-1] is late
    assert late.connected
    added = rec.events.index((ADDED, late))
    started = rec.events.index((FEED, late))
    assert added < started
    assert "opened kpdx3_atis" in rec.messages


def test_a_feed_opened_at_the_audible_limit_opens_muted():
    late = late_session()
    cockpit, rec, _ = make(2, limit=2, audible=(0, 1), opener=lambda f: late)
    cockpit.open_feed(ATIS)
    assert late.muted is True
    assert cockpit.audible_count() == 2
    assert any("Opened ATIS muted" in m for m in rec.messages), rec.messages


def test_an_opened_feed_is_findable_by_ident():
    late = late_session()
    cockpit, _, _ = make(2, opener=lambda feed: late)
    cockpit.open_feed(ATIS)
    assert cockpit.session("kpdx3_atis") is late
```

- [ ] **Step 2:** Run; expect `AttributeError: 'Cockpit' object has no attribute 'open_feed'`.

- [ ] **Step 3: Implement**

```python
    # -- opening a feed ------------------------------------------------

    def open_feed(self, feed: Feed):
        """Add a feed to the running stack, metering and audible.

        Audible rather than muted: this is only reached by picking a feed
        that is not open, which is an explicit request to hear it. Returns
        the new session, or None if there is nothing to add.
        """
        if self.feed_opener is None:
            self.warn(f"{feed.ident} is not open")
            return None
        try:
            session = self.feed_opener(feed)
        except Exception as exc:  # a dead feed must not take the cockpit with it
            self.warn(f"could not open {feed.ident}: {exc}")
            return None
        if not session.muted and self.audible_count() >= self.max_streams:
            # Open it muted rather than not at all: the row is still what
            # was asked for, and unmuting it later is one key.
            session.muted = True
            self.warn(
                f"{self.max_streams} feeds already audible — LiveATC's "
                f"limit. Opened {session.name} muted."
            )
        session.soloed = False
        self._sessions.append(session)
        # Announced before it is connected, so its first state change has
        # a row to land on.
        self._emit(ADDED, session)
        self.reconcile_streams()
        self.warn(f"opened {feed.ident}")
        return session
```

Opening a feed that is already open is the caller's business (the terminal
app jumps to it instead); `open_feed` does not check, and Task 6 keeps that
check in `SquelchApp.jump_to_feed` where it is today.

- [ ] **Step 4:** `pytest tests/test_cockpit.py -q` → `34 passed`.

- [ ] **Step 5: Revert-check**

| Break | Expected failure |
|---|---|
| move `self._emit(ADDED, session)` below `self.reconcile_streams()` | `test_an_opened_feed_is_added_before_it_is_started` |
| delete the `session.muted = True` line | `test_a_feed_opened_at_the_audible_limit_opens_muted` |

- [ ] **Step 6:** Full suite → 766 passed. Commit
`feat(squelch): opening a feed in Cockpit`.

---

### Task 6: SquelchApp drives the Cockpit

The only task that touches working code. No new tests: the gate is that the
existing 732 pass **without one edited line**.

**Files:** Modify `src/squelch/app.py`

- [ ] **Step 1: Construction.** In `SquelchApp.__init__`, delete
`self._sessions = list(sessions)`, `self._feed_opener = feed_opener`,
`self._max_streams = ...`, `self._solo = Solo()`, `self._resorter =
Resorter()` and the `for session ... soloed = False` loop. In their place:

```python
        self._cockpit = Cockpit(
            config,
            sessions,
            feed_opener=feed_opener,
            on_change=self._on_cockpit_change,
        )
        # The stack as the widgets show it. Kept in step with the cockpit by
        # _on_cockpit_change; selection is an index into this, because
        # selection belongs to a viewer and the cockpit has no viewers.
        self._shown: list = self._cockpit.sessions
```

Imports: add `from squelch.cockpit import ADDED, FEED, MESSAGE, ORDER, Cockpit`;
drop `Resorter`, `rank`, `Solo` and `slots`, which `app.py` no longer uses.

- [ ] **Step 2: The names the tests and `__main__` reach for.** These stay,
as thin properties, so nothing outside `app.py` changes:

```python
    # tests/test_app.py, tests/test_feed_picker.py and squelch.__main__ read
    # these. They are views of the cockpit now, not state of their own.
    @property
    def _sessions(self) -> list:
        return self._shown

    @property
    def _solo(self):
        return self._cockpit.solo

    @property
    def _feed_opener(self):
        return self._cockpit.feed_opener

    @_feed_opener.setter
    def _feed_opener(self, opener) -> None:
        self._cockpit.feed_opener = opener
```

`_sessions` returns the live mirror, not a copy, because
`tests/test_app.py` does `app._sessions.index(...)` between events and
expects identity. Nothing may mutate it except `_on_cockpit_change`.

- [ ] **Step 3: The event handler.**

```python
    def _on_cockpit_change(self, kind: str, payload) -> None:
        """Turn what the cockpit did into what the widgets show."""
        if kind == FEED:
            self._refresh_row(payload)
            self._refresh_header()
        elif kind == ORDER:
            self._show_order(payload)
        elif kind == ADDED:
            self._shown.append(payload)
            row = FeedRow(payload, classes="feed")
            self._rows[id(payload)] = row
            if self._feed_list is not None:
                self._feed_list.mount(row)
        elif kind == MESSAGE:
            # Looked up at call time: tests replace app.warn with a list's
            # append, and must keep catching these.
            self.warn(payload)

    def _show_order(self, order: list) -> None:
        """Move rows to match the cockpit's order, keeping the selection on
        its feed. Moves rather than remounts, so meter history survives."""
        selected = self.selected_session
        self._shown = list(order)
        feed_list = self._feed_list
        if feed_list is not None:
            for index, session in enumerate(self._shown):
                row = self._rows.get(id(session))
                if row is not None:
                    feed_list.move_child(row, before=index)
        if selected is not None and selected in self._shown:
            self._selected = self._shown.index(selected)
        self._apply_selection()
```

Note one deliberate difference from the old `apply_order`: the mirror is
updated even before the feed list is mounted. The old method returned early
and left `_sessions` stale, which was harmless only because nothing
reordered before mount.

- [ ] **Step 4: Delegate the actions.** Replace the bodies; delete
`apply_order`, `_ranked`, `_reorder_now`, `_audible_count`,
`_refuse_over_limit`, `_apply_mix` and `_clear_solo_marks`.

```python
    def on_key(self, event) -> None:
        # A row that moves between deciding on a key and pressing it acts on
        # the wrong feed.
        self._cockpit.note_input()

    def _tick_resort(self) -> None:
        self._cockpit.tick_resort()

    def start_streams(self) -> None:
        self._cockpit.start()
        self._refresh_header()

    def reconcile_streams(self) -> None:
        self._cockpit.reconcile_streams()
        self._refresh_header()

    def action_toggle_mute(self) -> None:
        session = self.selected_session
        if session is not None:
            self._cockpit.toggle_mute(session.feed.ident)

    def action_toggle_solo(self) -> None:
        session = self.selected_session
        if session is not None:
            self._cockpit.toggle_solo(session.feed.ident)

    def action_toggle_ambient(self) -> None:
        session = self.selected_session
        if session is not None:
            self._cockpit.toggle_ambient(session.feed.ident)

    def jump_to_feed(self, feed) -> None:
        # (keep the existing docstring)
        for index, session in enumerate(self._shown):
            if session.feed.ident == feed.ident:
                self._selected = index
                self._apply_selection()
                return
        self.open_feed(feed)

    def open_feed(self, feed) -> None:
        # (keep the existing docstring)
        session = self._cockpit.open_feed(feed)
        if session is None:
            return
        self._selected = self._shown.index(session)
        self._apply_selection()
        self._refresh_header()
```

In `on_row_clicked`, replace `self._resorter.note_input()` with
`self._cockpit.note_input()`. Everything else in it stays: it already
dispatches to the three actions.

- [ ] **Step 5: What stays exactly as it is.** Rendering (`_refresh_header`,
`_refresh_footer`, `_tick_clock`, `_refresh_row`, `_refresh_rows`), selection
(`selected_session`, `_apply_selection`, the cursor actions), `_tick_levels`,
`set_state`, `warn`, `warn_for`, the message log, the theme poll, the config
overlay, the feed picker and its worker, and every timer. If you find
yourself editing one of these, stop: it is not part of this task.

- [ ] **Step 6: The gate**

```
find . -name __pycache__ -not -path './.venv/*' -exec rm -rf {} +
uv run --project . pytest -q
```
Expected: **766 passed** (732 existing + 34 new).

```
git diff --stat main -- tests/
```
Expected: exactly one line, `tests/test_cockpit.py`. Anything else means a
test was edited to fit, which defeats the gate: revert it and fix `app.py`.

```
grep -nE '_resorter|Solo\(|slots\.plan|rank\(' src/squelch/app.py
```
Expected: no output. The rules live in one place.

- [ ] **Step 7: Prove the app goes through the cockpit.** One break: in
`cockpit.py`, make `_refuse_over_limit` always return `False`. Run
`pytest tests/test_app.py -q -k refused`. Expected:
`test_unmuting_past_the_limit_is_refused_and_explained` fails. Restore,
purge, rerun green. This is what shows the terminal app has no private
copy of the rule left.

- [ ] **Step 8: By hand, on the Mac, with real audio.** `uv run squelch`
(outside the cockpit is fine). Check: rows meter; `space` mutes and the row
moves at once; `S` solos and `S` again restores; `a` marks ambient; `f`
opens the picker and picking a feed that is not open opens it; at an
airport with more than seven feeds (`--icao KORD`) the parked notice
appears and unmuting a parked feed brings it in. `q` quits cleanly.

- [ ] **Step 9:** Commit `refactor(squelch): SquelchApp drives Cockpit`.

---

### Task 7: Documentation

**Files:** Modify the spec and `docs/README.md`

- [ ] **Step 1:** In the spec, under "The controller", replace the sentence
beginning "`SquelchApp` is then rewritten to drive a `Cockpit`" through
"with no Textual involved." with:

  > `SquelchApp` is then rewritten to drive a `Cockpit`. **That is the gate
  > for everything after it:** the terminal squelch keeps working on the new
  > controller, every existing test passes without being edited, and
  > `test_cockpit.py` covers the same rules with no Textual involved. The
  > app's tests retire with the terminal UI in phase E; the cockpit's stay.

- [ ] **Step 2:** In `docs/README.md`, under the web cockpit heading, add a
phase table like the audio pane one, with phase A linked to this plan and
marked built, and B to E marked not started.

- [ ] **Step 3:** Commit `docs: phase A done`.

---

## Execution record

Built 2026-10-18 on `feat/web-cockpit`, one commit per task. Every
revert-check in Tasks 1 to 6 was run as written and failed the named test.
Run in a Linux sandbox without PortAudio, so the five `test_main.py` tests
that build a real `Mixer` were run against a stand-in `sounddevice` whose
output stream never opens (squelch's "no audio device" path); with it, the
full suite was **766 passed**. Task 6 Step 8, the by-hand check with real
audio, is still to do on the Mac.

## Self-Review Notes

- **Dry run, 2026-10-18.** Every code block in Tasks 1 to 6 was assembled
  into a scratch copy of the repo and run: `tests/test_cockpit.py` 34
  passed; the full suite 766 collected, 761 passed, and the 5 failures were
  the PortAudio ones named in Global Constraints (Linux VM, no PortAudio).
  No existing test was edited. Task 6 Step 7's break was confirmed to fail
  `test_unmuting_past_the_limit_is_refused_and_explained`. The dry run is
  not a substitute for the revert-checks, which still have to be done one at
  a time as written.

- **Spec coverage.** The spec's `Cockpit` lists `snapshot`, `levels`,
  `set_volume` and `stop`; they are deferred to phase B on purpose (see
  Interfaces). Everything the spec says moves out of `SquelchApp` does:
  selection excepted, which the spec itself keeps per viewer.
- **Behaviour change, deliberate and invisible:** parking and starting now
  emit `feed` events, so rows redraw through the normal path instead of the
  app calling `set_state` by hand after `park()`.
- **Behaviour change, deliberate and invisible:** the app's mirror of the
  stack is kept in step before mount as well as after.
- **Solo is keyed by ident** rather than `id(session)`. Safe because idents
  are unique, which `parse_airport_page` guarantees and the constructor now
  enforces.
- **Message text is unchanged**, character for character, because the
  unedited app tests assert on it.
- **Test count:** 732 → 739 (T1) → 746 (T2) → 758 (T3) → 761 (T4) → 766 (T5)
  → 766 (T6, no new tests).
