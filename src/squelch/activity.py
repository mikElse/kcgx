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
