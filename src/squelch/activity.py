"""How busy a feed has been, and what order that puts the stack in.

Deliberately free of Textual and of `FeedSession`: this is arithmetic over
level readings and a clock, and it is the cheapest possible thing to test.
"""

from __future__ import annotations

import time
from collections.abc import Callable

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
