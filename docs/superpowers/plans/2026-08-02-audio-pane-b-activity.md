# Audio Pane B — Activity Ranking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rank feeds by how busy they have been over the trailing five minutes, reorder the stack accordingly without rows moving under the user's hand, and colour the expanded meter as a VU gradient.

**Architecture:** Activity is a bucketed counter updated on the audio thread and never marshalled to the UI. Ranking and resort debouncing are pure, clock-injected functions in a new `activity.py`. The pipeline grows a second level tap so activity can be measured pre-compression while the meter displays post-compression — a split that matters only once spec D lands, but which must exist before it does.

**Tech Stack:** Python 3.14, Textual 8.2.8, Rich (bundled with Textual) for per-cell meter colouring, pytest 9.1.1.

**Spec:** `docs/superpowers/specs/2026-08-02-audio-pane-activity-design.md`

**Depends on:** `docs/superpowers/plans/2026-08-02-audio-pane-a-rows.md` must be complete. This plan uses `rows.py`, `control_line`, `meter_rows`, and the compact/expanded row states from it.

## Global Constraints

- Activity is **the fraction of the trailing 5 minutes above `activity_threshold_dbfs`**, default **−40.0 dBFS**.
- The activity window is **60 buckets of 5 seconds**. Never a per-sample deque.
- Activity is measured **pre-compression**; the displayed meter is **post-compression**. Until spec D lands, both taps read the same value, and the split must survive it.
- Activity readings are consumed on the audio thread. They are **never** sent through `call_from_thread`.
- Resort applies only after the same order holds for **3 consecutive computations (15 s)** and **no input in the last 2 s**. Ranking recomputes every **5 s**.
- Selection tracks the **session**, never the row index. `SquelchApp._rows` stays keyed by `id(session)`.
- Order is **descending by activity**, ties broken by **original discovery order**.
- `activity.py`, `pipeline.py`, and `session.py` **must not import `textual`**.
- The pane is **48 columns**; no rendered line may exceed it. Expanded rows are 6 cells tall, compact 2.
- No test may access the network, open an audio device, or sleep on a real clock. Inject clocks.
- Run tests with `uv run pytest`.

---

## File Structure

| File | Responsibility |
|---|---|
| `src/squelch/activity.py` | **New.** `ActivityTracker`, `rank`, `Resorter`. Pure, clock-injected |
| `src/squelch/pipeline.py` | Two level taps; switchable display decimation |
| `src/squelch/session.py` | Owns its tracker; exposes `activity`; switches display rate on mute change |
| `src/squelch/rows.py` | VU gradient meter rendering |
| `src/squelch/app.py` | Resort timer, input debounce, widget reordering |
| `src/squelch/config.py` | `activity_threshold_dbfs` |
| `tests/test_activity.py` | **New.** Tracker, ranking, debounce |
| `tests/test_pipeline.py` | Extended: two taps, switchable decimation |
| `tests/test_rows.py` | Extended: gradient |
| `tests/test_app.py` | Extended: resort behaviour, selection stability |

---

### Task 1: The activity tracker

**Files:**
- Create: `src/squelch/activity.py`
- Create: `tests/test_activity.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `WINDOW_SECONDS = 300.0`, `BUCKET_SECONDS = 5.0`, `BUCKET_COUNT = 60`, and class `ActivityTracker(threshold_dbfs: float = -40.0, *, clock: Callable[[], float] = time.monotonic)` with `push(dbfs: float) -> None` and `fraction() -> float` in `0.0..1.0`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_activity.py`:

```python
"""Activity tracking: how busy has this frequency been lately.

A rolling five-minute window over a 10 Hz reading is 3000 samples per feed
and twelve feeds. These tests pin the bucketed approximation that replaces
that, and the clock is always injected -- nothing here sleeps.
"""

from squelch.activity import BUCKET_COUNT, BUCKET_SECONDS, ActivityTracker

LOUD = -20.0
QUIET = -70.0
THRESHOLD = -40.0


class FakeClock:
    def __init__(self, now=0.0):
        self.now = now

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def tracker(clock=None):
    return ActivityTracker(THRESHOLD, clock=clock or FakeClock())


def test_a_cold_tracker_reports_no_activity():
    assert tracker().fraction() == 0.0


def test_a_cold_tracker_does_not_divide_by_zero():
    """A feed that has never delivered a frame must not raise."""
    assert tracker().fraction() == 0.0


def test_all_loud_is_full_activity():
    t = tracker()
    for _ in range(20):
        t.push(LOUD)
    assert t.fraction() == 1.0


def test_all_quiet_is_no_activity():
    t = tracker()
    for _ in range(20):
        t.push(QUIET)
    assert t.fraction() == 0.0


def test_half_loud_is_half_activity():
    t = tracker()
    for _ in range(10):
        t.push(LOUD)
        t.push(QUIET)
    assert t.fraction() == 0.5


def test_a_level_exactly_at_the_threshold_is_not_busy():
    """Strictly greater than, so the threshold itself is the quiet side."""
    t = tracker()
    t.push(THRESHOLD)
    assert t.fraction() == 0.0


def test_just_above_the_threshold_is_busy():
    t = tracker()
    t.push(THRESHOLD + 0.1)
    assert t.fraction() == 1.0


def test_readings_older_than_the_window_are_evicted():
    clock = FakeClock()
    t = tracker(clock)
    for _ in range(10):
        t.push(LOUD)
    assert t.fraction() == 1.0
    clock.advance(BUCKET_SECONDS * BUCKET_COUNT + 1)
    for _ in range(10):
        t.push(QUIET)
    assert t.fraction() == 0.0, "the loud minute has aged out entirely"


def test_the_window_is_five_minutes():
    assert BUCKET_SECONDS * BUCKET_COUNT == 300.0


def test_a_partially_aged_window_blends_old_and_new():
    clock = FakeClock()
    t = tracker(clock)
    for _ in range(10):
        t.push(LOUD)
    clock.advance(150.0)  # half the window
    for _ in range(10):
        t.push(QUIET)
    assert t.fraction() == 0.5, "both halves are still inside the window"


def test_a_long_silence_decays_to_zero_without_new_readings():
    """An offline feed stops pushing entirely and must still sink."""
    clock = FakeClock()
    t = tracker(clock)
    for _ in range(10):
        t.push(LOUD)
    clock.advance(BUCKET_SECONDS * BUCKET_COUNT + 1)
    assert t.fraction() == 0.0


def test_memory_is_bounded_by_the_bucket_count():
    clock = FakeClock()
    t = tracker(clock)
    for _ in range(1000):
        t.push(LOUD)
        clock.advance(1.0)
    assert len(t._buckets) == BUCKET_COUNT
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_activity.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'squelch.activity'`.

- [ ] **Step 3: Implement**

Create `src/squelch/activity.py`:

```python
"""How busy a feed has been, and what order that puts the stack in.

Deliberately free of Textual and of `FeedSession`: this is arithmetic over
level readings and a clock, and it is the cheapest possible thing to test.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence

WINDOW_SECONDS = 300.0
BUCKET_SECONDS = 5.0
BUCKET_COUNT = int(WINDOW_SECONDS / BUCKET_SECONDS)  # 60


class ActivityTracker:
    """The fraction of the last five minutes spent above a threshold.

    Sixty five-second buckets rotated in place, rather than a deque of every
    reading: at 10 Hz a true rolling window is 3000 samples per feed and
    twelve feeds, for an average whose useful resolution is nowhere near
    that fine.
    """

    def __init__(
        self,
        threshold_dbfs: float = -40.0,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._threshold = threshold_dbfs
        self._clock = clock
        # (busy, total) per bucket, indexed by bucket number modulo count.
        self._buckets: list[list[int]] = [[0, 0] for _ in range(BUCKET_COUNT)]
        # Which absolute bucket number each slot currently holds, so a slot
        # left behind by a silent gap is recognised as stale rather than
        # counted as old data.
        self._stamps: list[int] = [-1] * BUCKET_COUNT

    def push(self, dbfs: float) -> None:
        index, slot = self._slot()
        if self._stamps[slot] != index:
            self._stamps[slot] = index
            self._buckets[slot] = [0, 0]
        self._buckets[slot][0] += 1 if dbfs > self._threshold else 0
        self._buckets[slot][1] += 1

    def fraction(self) -> float:
        current, _slot = self._slot()
        oldest = current - BUCKET_COUNT + 1
        busy = total = 0
        for slot, stamp in enumerate(self._stamps):
            if stamp < oldest:
                continue
            busy += self._buckets[slot][0]
            total += self._buckets[slot][1]
        if total == 0:
            return 0.0
        return busy / total

    def _slot(self) -> tuple[int, int]:
        index = int(self._clock() // BUCKET_SECONDS)
        return index, index % BUCKET_COUNT
```

- [ ] **Step 4: Run**

Run: `uv run pytest tests/test_activity.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/squelch/activity.py tests/test_activity.py
git commit -m "feat(squelch): track per-feed activity over a five-minute window"
```

---

### Task 2: Ranking and the resort debounce

**Files:**
- Modify: `src/squelch/activity.py`
- Modify: `tests/test_activity.py`

**Interfaces:**
- Consumes: nothing from Task 1 at runtime; shares the module.
- Produces:
  - `rank(items: Sequence, activity_of: Callable[[object], float]) -> list` — descending by activity, ties by position in `items`.
  - `SETTLE_ROUNDS = 3`, `QUIET_SECONDS = 2.0`
  - class `Resorter(*, clock: Callable[[], float] = time.monotonic, settle: int = SETTLE_ROUNDS, quiet: float = QUIET_SECONDS)` with `note_input() -> None` and `propose(order: Sequence) -> list | None` returning the order to apply, or `None` to hold.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_activity.py`:

```python
from squelch.activity import SETTLE_ROUNDS, Resorter, rank


def test_rank_puts_the_busiest_first():
    busy = {"a": 0.1, "b": 0.9, "c": 0.5}
    assert rank(["a", "b", "c"], busy.__getitem__) == ["b", "c", "a"]


def test_rank_breaks_ties_by_discovery_order():
    """Two equally idle feeds must not swap places every five seconds."""
    busy = {"a": 0.0, "b": 0.0, "c": 0.0}
    assert rank(["a", "b", "c"], busy.__getitem__) == ["a", "b", "c"]
    assert rank(["c", "b", "a"], busy.__getitem__) == ["c", "b", "a"]


def test_rank_leaves_an_empty_list_alone():
    assert rank([], lambda item: 0.0) == []


def resorter(clock):
    return Resorter(clock=clock)


def test_a_new_order_is_held_until_it_settles():
    clock = FakeClock(100.0)
    r = resorter(clock)
    for _ in range(SETTLE_ROUNDS - 1):
        assert r.propose(["b", "a"]) is None
    assert r.propose(["b", "a"]) == ["b", "a"]


def test_a_changing_order_never_settles():
    clock = FakeClock(100.0)
    r = resorter(clock)
    assert r.propose(["b", "a"]) is None
    assert r.propose(["a", "b"]) is None
    assert r.propose(["b", "a"]) is None


def test_recent_input_defers_an_otherwise_ready_resort():
    """A row that moves between the decision to click and the click itself
    mutes the wrong frequency."""
    clock = FakeClock(100.0)
    r = resorter(clock)
    for _ in range(SETTLE_ROUNDS - 1):
        r.propose(["b", "a"])
    r.note_input()
    assert r.propose(["b", "a"]) is None, "deferred by the keypress"
    clock.advance(2.5)
    assert r.propose(["b", "a"]) == ["b", "a"]


def test_input_does_not_reset_the_settle_count():
    clock = FakeClock(100.0)
    r = resorter(clock)
    for _ in range(SETTLE_ROUNDS):
        r.propose(["b", "a"])
    r.note_input()
    assert r.propose(["b", "a"]) is None
    clock.advance(2.5)
    assert r.propose(["b", "a"]) == ["b", "a"], "still settled, just delayed"


def test_applying_an_order_does_not_immediately_reapply_it():
    clock = FakeClock(100.0)
    r = resorter(clock)
    for _ in range(SETTLE_ROUNDS - 1):
        r.propose(["b", "a"])
    assert r.propose(["b", "a"]) == ["b", "a"]
    assert r.propose(["b", "a"]) is None, "already the applied order"


def test_reverting_to_the_applied_order_is_not_a_change():
    clock = FakeClock(100.0)
    r = resorter(clock)
    for _ in range(SETTLE_ROUNDS):
        r.propose(["b", "a"])
    r.propose(["a", "b"])
    assert r.propose(["b", "a"]) is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_activity.py -k "rank or resort or settle or input" -v`
Expected: FAIL with `ImportError: cannot import name 'rank'`.

- [ ] **Step 3: Implement**

Append to `src/squelch/activity.py`:

```python
SETTLE_ROUNDS = 3
QUIET_SECONDS = 2.0


def rank(items: Sequence, activity_of: Callable[[object], float]) -> list:
    """Busiest first, ties broken by the order they were discovered in.

    The tie-break is what stops two equally idle feeds trading places every
    time the ranking is recomputed.
    """
    return [
        item
        for _key, item in sorted(
            ((-activity_of(item), index), item)
            for index, item in enumerate(items)
        )
    ]


class Resorter:
    """Decides when a proposed order is safe to apply.

    Two guards, for two different problems. The settle count stops the stack
    twitching on a ranking that has not stabilised. The quiet period stops a
    row moving between the moment the user decides to click it and the
    moment they do -- which matters because a click on a row body toggles
    its mute, so a row that moves silences the wrong frequency.
    """

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        settle: int = SETTLE_ROUNDS,
        quiet: float = QUIET_SECONDS,
    ) -> None:
        self._clock = clock
        self._settle = settle
        self._quiet = quiet
        self._applied: list | None = None
        self._candidate: list | None = None
        self._held = 0
        self._last_input: float | None = None

    def note_input(self) -> None:
        self._last_input = self._clock()

    def propose(self, order: Sequence) -> list | None:
        proposed = list(order)
        if proposed == self._applied:
            self._candidate = None
            self._held = 0
            return None
        if proposed != self._candidate:
            self._candidate = proposed
            self._held = 1
            return None
        self._held += 1
        if self._held < self._settle:
            return None
        if self._last_input is not None:
            if self._clock() - self._last_input < self._quiet:
                # Settled, but the user's hand is on the stack. Hold the
                # count so this applies as soon as they stop.
                return None
        self._applied = proposed
        self._candidate = None
        self._held = 0
        return proposed
```

- [ ] **Step 4: Run**

Run: `uv run pytest tests/test_activity.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/squelch/activity.py tests/test_activity.py
git commit -m "feat(squelch): rank feeds by activity behind a resort debounce"
```

---

### Task 3: Two level taps in the pipeline

**Files:**
- Modify: `src/squelch/pipeline.py`
- Modify: `tests/test_pipeline.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `Events` gains `on_activity: Callable[[float], None]`, defaulting to a no-op so existing construction sites keep working.
  - `ACTIVITY_DECIMATION = 5` (10 Hz, fixed).
  - `Pipeline.set_level_every(n: int) -> None` — change the display decimation at runtime.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_pipeline.py`:

```python
def collect_all():
    got = {"levels": [], "states": [], "activity": []}
    return got, Events(
        on_level=lambda d: got["levels"].append(d),
        on_state=lambda s: got["states"].append(s),
        on_activity=lambda d: got["activity"].append(d),
    )


def loud_frames(n):
    return [struct.pack("<h", 8000) * (FRAME_BYTES // 2) for _ in range(n)]


def test_activity_is_reported_at_a_fixed_ten_hertz():
    got, events = collect_all()
    Pipeline(FakeReader(loud_frames(20)), FakePlayer(), events).run()
    assert len(got["activity"]) == 4, "20 frames at one per 5 is 4 readings"


def test_the_display_rate_is_independent_of_the_activity_rate():
    got, events = collect_all()
    Pipeline(
        FakeReader(loud_frames(20)), FakePlayer(), events, level_every=2
    ).run()
    assert len(got["levels"]) == 10
    assert len(got["activity"]) == 4


def test_the_display_rate_can_be_changed_at_runtime():
    got, events = collect_all()
    pipeline = Pipeline(FakeReader(loud_frames(20)), FakePlayer(), events)
    pipeline.set_level_every(2)
    pipeline.run()
    assert len(got["levels"]) == 10


def test_a_reconnect_heartbeat_does_not_feed_activity():
    """A `None` is the absence of a sample, not five minutes of silence."""
    got, events = collect_all()
    Pipeline(FakeReader([None] * 10), FakePlayer(), events).run()
    assert got["activity"] == []
    assert got["states"] == ["reconnecting"]


def test_events_can_still_be_built_without_an_activity_callback():
    """Existing construction sites must keep working."""
    events = Events(on_level=lambda d: None, on_state=lambda s: None)
    Pipeline(FakeReader(loud_frames(10)), FakePlayer(), events).run()


def test_a_failing_activity_callback_does_not_stop_the_pump():
    def explode(_dbfs):
        raise RuntimeError("boom")

    events = Events(
        on_level=lambda d: None,
        on_state=lambda s: None,
        on_activity=explode,
    )
    player = FakePlayer()
    Pipeline(FakeReader(loud_frames(10)), player, events).run()
    assert len(player.written) == 10, "audio must survive a broken callback"
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_pipeline.py -k activity -v`
Expected: FAIL with `TypeError: Events.__init__() got an unexpected keyword argument 'on_activity'`.

- [ ] **Step 3: Implement**

In `src/squelch/pipeline.py`, extend the module docstring with:

```python
"""...

Two level taps leave here, not one. `on_level` is what the meter draws and
is decimated to whatever rate the row needs; `on_activity` is what the
five-minute ranking counts and is fixed at 10 Hz. They are separate because
the mixing engine compresses the audio between them -- upward compression
exists to raise quiet signals, so ranking on a post-compression level would
push every feed toward the same number and destroy the ranking entirely.
`on_activity` is consumed on this thread and is never marshalled to the UI.
"""
```

Replace `Events` and the relevant parts of `Pipeline`:

```python
# Activity is counted at a fixed 10 Hz regardless of what the meter is
# doing: it feeds a five-minute average, where more resolution buys nothing.
ACTIVITY_DECIMATION = 5


@dataclass
class Events:
    on_level: Callable[[float], None]
    on_state: Callable[[str], None]
    # Defaulted so every existing construction site keeps working. A feed
    # whose activity nobody is counting is a legitimate configuration.
    on_activity: Callable[[float], None] = lambda _dbfs: None
```

In `Pipeline.__init__`, after the existing level counters:

```python
        self._activity_count = 0
        self._activity_peak = SILENCE_FLOOR_DBFS
```

Add:

```python
    def set_level_every(self, n: int) -> None:
        """Change the display rate. Safe to call from another thread.

        A compact row draws no meter, so it stops emitting display levels
        entirely; an expanded row wants more than the 10 Hz the ranking
        needs. Rebinding an int is atomic under CPython, and a rate that
        takes effect one frame late is not observable.
        """
        self._level_every = max(1, n)
```

In `run()`, replace the live-frame branch:

```python
            self._report_state("live")
            self._player.write(frame)
            raw = rms_dbfs(frame)
            # Pre-compression, for the ranking. Post-compression, for the
            # meter. Identical until the mixing engine lands between them.
            self._emit_activity(raw)
            self._emit_level(raw)
```

and add:

```python
    def _emit_activity(self, dbfs: float) -> None:
        self._activity_peak = max(self._activity_peak, dbfs)
        self._activity_count += 1
        if self._activity_count < ACTIVITY_DECIMATION:
            return
        peak = self._activity_peak
        self._activity_count = 0
        self._activity_peak = SILENCE_FLOOR_DBFS
        self._emit(self._events.on_activity, peak)
```

Leave the `frame is None` branch alone: it must keep reporting `reconnecting` and forcing a display level, and must not touch activity.

- [ ] **Step 4: Run**

Run: `uv run pytest tests/test_pipeline.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/squelch/pipeline.py tests/test_pipeline.py
git commit -m "feat(squelch): split the activity tap from the meter tap"
```

---

### Task 4: Sessions own their tracker and their display rate

**Files:**
- Modify: `src/squelch/session.py`
- Modify: `src/squelch/config.py`
- Modify: `tests/test_session.py`
- Modify: `tests/test_config.py`

**Interfaces:**
- Consumes: `ActivityTracker` (Task 1), `Events.on_activity` and `Pipeline.set_level_every` (Task 3).
- Produces:
  - `Config.activity_threshold_dbfs: float = -40.0`
  - `FeedSession.activity -> float` property
  - `FeedSession.muted` setter also switches the display rate
  - `EXPANDED_DECIMATION = 2` (25 Hz), `COMPACT_DECIMATION = 0` meaning "emit nothing"

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_config.py`:

```python
def test_the_activity_threshold_defaults_to_minus_forty(tmp_path):
    assert Config().activity_threshold_dbfs == -40.0


def test_the_activity_threshold_can_be_configured(tmp_path):
    path = tmp_path / "squelch.toml"
    path.write_text("activity_threshold_dbfs = -35.5\n")
    assert load_config(path).activity_threshold_dbfs == -35.5


def test_a_non_numeric_activity_threshold_is_rejected(tmp_path):
    path = tmp_path / "squelch.toml"
    path.write_text('activity_threshold_dbfs = "loud"\n')
    with pytest.raises(ConfigError) as exc:
        load_config(path)
    assert "activity_threshold_dbfs" in str(exc.value)
```

Append to `tests/test_session.py`:

```python
def test_a_session_starts_with_no_activity():
    assert make_session().activity == 0.0


def test_activity_readings_reach_the_tracker():
    session = make_session()
    for _ in range(10):
        session._on_activity(-10.0)
    assert session.activity == 1.0


def test_activity_ignores_levels_below_the_threshold():
    session = make_session()
    for _ in range(10):
        session._on_activity(-70.0)
    assert session.activity == 0.0


def test_unmuting_raises_the_display_rate():
    session = make_session()
    fake = FakePipeline()
    session._pipeline = fake
    session.muted = False
    assert fake.level_every == 2, "an expanded row draws a meter at 25 Hz"


def test_muting_stops_display_levels_entirely():
    session = make_session()
    fake = FakePipeline()
    session._pipeline = fake
    session.muted = False
    session.muted = True
    assert fake.level_every == 0, "a compact row draws no meter"


def test_switching_the_rate_before_the_pipeline_exists_is_safe():
    """Mute can be toggled between construction and the thread starting."""
    session = make_session()
    assert session._pipeline is None
    session.muted = False
```

Add to `tests/test_session.py` near its other fakes:

```python
class FakePipeline:
    def __init__(self):
        self.level_every = None

    def set_level_every(self, n):
        self.level_every = n

    def run(self):
        pass

    def stop(self):
        pass
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_session.py tests/test_config.py -v`
Expected: FAIL with `AttributeError: 'FeedSession' object has no attribute 'activity'`.

- [ ] **Step 3: Implement the config key**

In `src/squelch/config.py`, add to `Config`:

```python
    # Above this, a frame counts as busy for the five-minute activity
    # ranking. ATC feeds sit on a noise floor around -50 dBFS with speech
    # peaking -20 to -10, so this separates the two with margin on both
    # sides.
    activity_threshold_dbfs: float = -40.0
```

`_checked` derives the expected type from `type(field.default)`, so `float` is handled with no further change. Note that an integer value in TOML (`activity_threshold_dbfs = -40`) will be rejected as `int`; document that in the README table in Task 8 by showing a decimal default.

- [ ] **Step 4: Implement the session changes**

In `src/squelch/session.py`, add imports and constants:

```python
from squelch.activity import ActivityTracker

# A compact row draws no meter, so it emits no display levels at all. An
# expanded row decimates by 2 for 25 Hz -- fast enough to read as a
# waveform, and the cost now scales with what you are listening to rather
# than with how many feeds exist.
EXPANDED_DECIMATION = 2
COMPACT_DECIMATION = 0
```

In `__init__`, accept a threshold and build the tracker:

```python
        activity_threshold: float = -40.0,
```

as a keyword argument, and in the body:

```python
        self._activity = ActivityTracker(activity_threshold)
```

Replace the `muted` setter:

```python
    @muted.setter
    def muted(self, value: bool) -> None:
        # Gated at the player, so the stream, the reader and the activity
        # count all keep running -- muting silences a feed without making it
        # stop being watched. What it does change is the *display* rate: a
        # muted feed is compact and draws no meter, so emitting levels for
        # it would be marshalling work nobody renders.
        self._player.muted = bool(value)
        self._apply_display_rate()

    def _apply_display_rate(self) -> None:
        if self._pipeline is None:
            return
        self._pipeline.set_level_every(
            COMPACT_DECIMATION if self.muted else EXPANDED_DECIMATION
        )

    @property
    def activity(self) -> float:
        return self._activity.fraction()

    def _on_activity(self, dbfs: float) -> None:
        # Stays on this thread: the tracker is arithmetic, and marshalling a
        # 10 Hz reading per feed onto the UI thread would cost more than the
        # ranking is worth.
        self._activity.push(dbfs)
```

In `_run`, extend the `Events` construction:

```python
            Events(
                on_level=lambda dbfs: self._set_level(dbfs),
                on_state=lambda state: self._set_state(state),
                on_activity=self._on_activity,
            ),
```

and immediately after building `self._pipeline`, apply the rate so a session that started unmuted gets the right one:

```python
        self._apply_display_rate()
```

`Pipeline.set_level_every` clamps to a minimum of 1, so `COMPACT_DECIMATION = 0` must be handled: change the clamp in `pipeline.py` to allow 0 and skip emission entirely when it is 0:

```python
    def set_level_every(self, n: int) -> None:
        self._level_every = max(0, n)
```

and at the top of `_emit_level`:

```python
        if self._level_every == 0 and not force:
            # A compact row draws no meter; there is nobody to tell.
            return
```

- [ ] **Step 5: Pass the threshold through**

In `src/squelch/__main__.py`, in `build_sessions`, add to the `session_factory` call:

```python
                activity_threshold=config.activity_threshold_dbfs,
```

- [ ] **Step 6: Run**

Run: `uv run pytest`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/squelch/session.py src/squelch/config.py src/squelch/pipeline.py src/squelch/__main__.py tests/test_session.py tests/test_config.py
git commit -m "feat(squelch): give each session an activity tracker and display rate"
```

---

### Task 5: The VU gradient

**Files:**
- Modify: `src/squelch/rows.py`
- Modify: `tests/test_rows.py`

**Interfaces:**
- Consumes: `level_step`, `meter_rows`, `METER_STEPS` from plan A.
- Produces:
  - `MeterPalette` dataclass with `dim: str`, `text: str`, `accent: str`, `peak: str` (Rich style strings)
  - `DEFAULT_PALETTE` using Textual variables
  - `gradient_style(step: int, palette: MeterPalette) -> str`
  - `meter_text(history: Sequence[float], palette: MeterPalette, width: int = METER_WIDTH) -> Text`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_rows.py`:

```python
from rich.text import Text

from squelch.rows import (
    DEFAULT_PALETTE,
    METER_STEPS,
    MeterPalette,
    gradient_style,
    meter_text,
)

PALETTE = MeterPalette(dim="dim", text="white", accent="green", peak="red")


def test_silence_uses_the_dim_stop():
    assert gradient_style(0, PALETTE) == "dim"


def test_a_peak_uses_the_peak_stop():
    assert gradient_style(METER_STEPS - 1, PALETTE) == "red"


def test_the_gradient_climbs_through_every_stop():
    seen = [gradient_style(step, PALETTE) for step in range(METER_STEPS)]
    assert set(seen) == {"dim", "white", "green", "red"}


def test_the_gradient_never_goes_backwards():
    order = ["dim", "white", "green", "red"]
    seen = [order.index(gradient_style(s, PALETTE)) for s in range(METER_STEPS)]
    assert seen == sorted(seen), "louder must never render cooler"


def test_meter_text_is_three_lines():
    text = meter_text([-20.0] * 10, PALETTE, width=10)
    assert isinstance(text, Text)
    assert text.plain.count("\n") == 2


def test_meter_text_matches_the_plain_renderer():
    history = [-50.0, -20.0, -5.0]
    plain = "\n".join(meter_rows(history, width=3))
    assert meter_text(history, PALETTE, width=3).plain == plain


def test_meter_text_colours_a_loud_column_differently_from_a_quiet_one():
    text = meter_text([-96.0, 0.0], PALETTE, width=2)
    styles = {str(span.style) for span in text.spans}
    assert "dim" in styles
    assert "red" in styles


def test_the_default_palette_defines_every_stop():
    for stop in ("dim", "text", "accent", "peak"):
        assert getattr(DEFAULT_PALETTE, stop)
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_rows.py -k "gradient or palette or meter_text" -v`
Expected: FAIL with `ImportError: cannot import name 'MeterPalette'`.

- [ ] **Step 3: Implement**

Append to `src/squelch/rows.py`, importing `from dataclasses import dataclass` and `from rich.text import Text`:

```python
@dataclass(frozen=True)
class MeterPalette:
    """The four colour stops the meter climbs through.

    Supplied by the active theme, so the meter recolours when the radar
    pane's theme changes. Rich style strings, not Textual CSS: these are
    applied per cell, which stylesheets cannot express.
    """

    dim: str
    text: str
    accent: str
    peak: str


DEFAULT_PALETTE = MeterPalette(
    dim="$text-disabled",
    text="$text",
    accent="$primary",
    peak="$warning",
)

# Step boundaries for each stop, over METER_STEPS (24). Roughly: the bottom
# third is noise floor, the middle is ordinary speech, the top is a strong
# signal, and the last few steps are approaching clipping.
_GRADIENT_STOPS = ((8, "dim"), (16, "text"), (21, "accent"), (METER_STEPS, "peak"))


def gradient_style(step: int, palette: MeterPalette) -> str:
    for boundary, name in _GRADIENT_STOPS:
        if step < boundary:
            return getattr(palette, name)
    return palette.peak


def meter_text(
    history: Sequence[float],
    palette: MeterPalette,
    width: int = METER_WIDTH,
) -> Text:
    """The three meter rows, with each column coloured by its own level.

    Built as one `Text` with per-cell spans rather than three styled
    widgets: the colour has to follow the sample, and a sample spans all
    three rows.
    """
    recent = list(history)[-width:]
    steps = [0] * (width - len(recent)) + [level_step(level) for level in recent]
    rows = meter_rows(history, width=width)
    text = Text(no_wrap=True)
    for row_index, row in enumerate(rows):
        if row_index:
            text.append("\n")
        for column, glyph in enumerate(row):
            text.append(glyph, style=gradient_style(steps[column], palette))
    return text
```

- [ ] **Step 4: Use it in `FeedRow`**

Give `FeedRow` a palette and render through it:

```python
    def __init__(self, session, *, palette: MeterPalette = DEFAULT_PALETTE, **kwargs) -> None:
        super().__init__(**kwargs)
        self.session = session
        self.palette = palette
        ...
```

```python
    def refresh_meter(self) -> None:
        if self._meter_widget is None or not self.expanded:
            return
        self._meter_widget.update(
            meter_text(self._history, self.palette), layout=False
        )
```

`Static.update` accepts a Rich renderable, and `markup=False` on the widget is irrelevant to a `Text` built with explicit styles — no third-party string is ever parsed.

- [ ] **Step 5: Run**

Run: `uv run pytest`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/squelch/rows.py tests/test_rows.py
git commit -m "feat(squelch): colour the expanded meter as a VU gradient"
```

---

### Task 6: Resort the stack in the app

**Files:**
- Modify: `src/squelch/app.py`
- Modify: `tests/test_app.py`

**Interfaces:**
- Consumes: `rank`, `Resorter` (Task 2), `session.activity` (Task 4).
- Produces: `SquelchApp._resorter`, `SquelchApp.RESORT_INTERVAL = 5.0`, `SquelchApp._tick_resort()`, and `SquelchApp.apply_order(order: list) -> None`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_app.py`:

```python
# -- activity sorting ------------------------------------------------------


def set_activity(app, values):
    for session, value in zip(app._sessions, values):
        session.activity = value


@pytest.mark.asyncio
async def test_the_stack_reorders_busiest_first_once_settled():
    app = make_app(3)
    async with app.run_test(size=SIZE) as pilot:
        set_activity(app, [0.1, 0.9, 0.5])
        original = list(app._sessions)
        for _ in range(3):
            app._tick_resort()
        await pilot.pause()
        assert app._sessions == [original[1], original[2], original[0]]


@pytest.mark.asyncio
async def test_one_tick_is_not_enough_to_reorder():
    app = make_app(3)
    async with app.run_test(size=SIZE) as pilot:
        set_activity(app, [0.1, 0.9, 0.5])
        original = list(app._sessions)
        app._tick_resort()
        await pilot.pause()
        assert app._sessions == original


@pytest.mark.asyncio
async def test_a_keypress_defers_a_resort():
    app = make_app(3)
    async with app.run_test(size=SIZE) as pilot:
        set_activity(app, [0.1, 0.9, 0.5])
        original = list(app._sessions)
        for _ in range(2):
            app._tick_resort()
        await pilot.press("down")
        await pilot.pause()
        app._tick_resort()
        await pilot.pause()
        assert app._sessions == original, "the stack must not move under a keypress"


@pytest.mark.asyncio
async def test_the_selection_follows_the_feed_across_a_resort():
    app = make_app(3)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("down")
        await pilot.pause()
        selected = app.selected_session
        set_activity(app, [0.1, 0.9, 0.5])
        for _ in range(3):
            app._tick_resort()
        await pilot.pause()
        assert app.selected_session is selected, "a resort must not change what is selected"


@pytest.mark.asyncio
async def test_a_resort_moves_the_widgets_not_just_the_list():
    app = make_app(3)
    async with app.run_test(size=SIZE) as pilot:
        set_activity(app, [0.1, 0.9, 0.5])
        for _ in range(3):
            app._tick_resort()
        await pilot.pause()
        painted = [row.session for row in app.query(FeedRow)]
        assert painted == app._sessions


@pytest.mark.asyncio
async def test_a_resort_preserves_meter_history():
    """Rows are moved, never remounted."""
    app = make_app(3)
    async with app.run_test(size=SIZE) as pilot:
        session = app._sessions[2]
        for level in (-20.0, -10.0, -5.0):
            app.set_level(session, level)
        set_activity(app, [0.1, 0.9, 0.5])
        for _ in range(3):
            app._tick_resort()
        await pilot.pause()
        assert len(app._rows[id(session)]._history) == 3


@pytest.mark.asyncio
async def test_offline_feeds_sink_to_the_bottom():
    app = make_app(3)
    async with app.run_test(size=SIZE) as pilot:
        set_activity(app, [0.0, 0.4, 0.8])
        original = list(app._sessions)
        for _ in range(3):
            app._tick_resort()
        await pilot.pause()
        assert app._sessions[-1] is original[0]
```

Add `self.activity = 0.0` to `FakeSession.__init__` in `tests/test_app.py` if Task 5 of plan A did not already.

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_app.py -k resort -v`
Expected: FAIL with `AttributeError: 'SquelchApp' object has no attribute '_tick_resort'`.

- [ ] **Step 3: Implement**

In `src/squelch/app.py`, import `from squelch.activity import Resorter, rank` and add to `SquelchApp`:

```python
    # Ranking is cheap; applying it is what needs to be rare.
    RESORT_INTERVAL = 5.0
```

In `__init__`:

```python
        self._resorter = Resorter()
        self._resort_timer = None
```

In `on_mount`, beside the clock timer:

```python
        self._resort_timer = self.set_interval(self.RESORT_INTERVAL, self._tick_resort)
```

In `on_unmount`, beside the clock timer teardown:

```python
        if self._resort_timer is not None:
            self._resort_timer.stop()
            self._resort_timer = None
```

Add the methods:

```python
    def _tick_resort(self) -> None:
        order = self._resorter.propose(
            rank(self._sessions, lambda session: session.activity)
        )
        if order is not None:
            self.apply_order(order)

    def apply_order(self, order: list) -> None:
        """Reorder the stack, moving rows rather than remounting them.

        Remounting would drop every row's meter history and its scroll
        position. `move_child` keeps the same widget instances, which is
        also why `_rows` can stay keyed by `id(session)` -- the mapping does
        not change, only the order of the children.
        """
        feed_list = self._feed_list
        if feed_list is None:
            return
        selected = self.selected_session
        self._sessions = list(order)
        for index, session in enumerate(self._sessions):
            row = self._rows.get(id(session))
            if row is not None:
                feed_list.move_child(row, before=index)
        if selected is not None:
            # Selection belongs to a feed, not to a position.
            self._selected = self._sessions.index(selected)
        self._apply_selection()
```

Record input for the debounce. Add to `SquelchApp`:

```python
    def on_key(self, event) -> None:
        self._resorter.note_input()
```

and at the top of `on_row_clicked` (from plan A Task 6):

```python
        self._resorter.note_input()
```

- [ ] **Step 4: Feed activity to the control line**

`control_line` already takes `activity` and `FeedRow.refresh_name` already reads `getattr(session, "activity", None)` from plan A. Change that read to always pass the float, since every real session now has one:

```python
                    activity=session.activity,
```

- [ ] **Step 5: Run**

Run: `uv run pytest`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/squelch/app.py tests/test_app.py
git commit -m "feat(squelch): reorder the stack by activity behind a debounce"
```

---

### Task 7: Documentation

**Files:**
- Modify: `README.md`

**Interfaces:**
- Consumes: everything above.
- Produces: nothing code-facing.

- [ ] **Step 1: Document the ranking**

Add a section after the sample pane:

> ### Ordering
>
> Feeds are ordered by how busy they have been over the last five minutes —
> the fraction of that window spent above `activity_threshold_dbfs`. The
> busiest frequency is at the top, and an offline feed decays to 0% and sinks.
> The expanded row shows the figure as `busy 34%`.
>
> The order does not change the instant the ranking does. A new order is
> applied only once it has held for fifteen seconds and you have not touched
> the pane for two — because clicking a row toggles its mute, and a row that
> moves while you are reaching for it silences the wrong frequency.
>
> Activity is measured **before** the compressor, so making quiet feeds louder
> does not make them look busier.

- [ ] **Step 2: Add the config key**

Extend the configuration table:

```markdown
| `activity_threshold_dbfs` | `-40.0` | Level above which a feed counts as busy for the five-minute ranking. Must be written as a decimal (`-40.0`, not `-40`). |
```

- [ ] **Step 3: Update "Known limitations"**

Delete "Scrolls when there are more feeds than rows; arrows move the selection and bring it into view" from the feature list only if it is now inaccurate; otherwise leave it. Add:

> - Ranking is by level crossings, not by speech detection — a feed with a
>   noisy carrier will rank above a quiet but busy one.

- [ ] **Step 4: Run the full suite**

Run: `uv run pytest`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add README.md
git commit -m "docs(squelch): document activity ranking"
```

---

## Verification

- `uv run pytest` passes with no skips.
- `activity.py`, `pipeline.py`, and `session.py` do not import `textual`.
- No `time.sleep` appears in `tests/test_activity.py`.
- With twelve feeds and three audible, marshalled level updates total 75/s, not 120/s: confirm by counting `set_level` calls over a second in a manual run.
