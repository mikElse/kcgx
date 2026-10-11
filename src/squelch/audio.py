"""Stream acquisition, level measurement, and playback.

One ffmpeg process decodes the feed to 16 kHz mono PCM. Those frames go to
the speaker and to the level meter.
"""

from __future__ import annotations

import array
import math
import subprocess
import time
from collections.abc import Callable, Iterator

import numpy as np

from squelch.feeds import USER_AGENT

Spawner = Callable[[str], subprocess.Popen]

SAMPLE_RATE = 16_000
FRAME_MS = 20
FRAME_SAMPLES = SAMPLE_RATE * FRAME_MS // 1000  # 320
FRAME_BYTES = FRAME_SAMPLES * 2                 # 640
SILENCE_FLOOR_DBFS = -96.0

READ_SIZE = FRAME_BYTES * 4


def rms_dbfs(pcm: bytes) -> float:
    """Frame energy in dBFS, floored at SILENCE_FLOOR_DBFS."""
    samples = array.array("h")
    samples.frombytes(pcm)
    if not samples:
        return SILENCE_FLOOR_DBFS
    mean_square = sum(s * s for s in samples) / len(samples)
    if mean_square <= 0:
        return SILENCE_FLOOR_DBFS
    return max(
        SILENCE_FLOOR_DBFS, 20 * math.log10(math.sqrt(mean_square) / 32768.0)
    )

# While waiting out a reconnect backoff there is, by definition, no audio to
# yield -- but the consumer still needs to hear from us. Sleeping the whole
# delay in one call makes `frames()` silent for up to 30 s, during which the
# Pipeline is parked inside its `for` statement and cannot report anything at
# all: the header stays on whatever it last said (i.e. "LIVE") and the meter
# freezes. Ticking at this interval and yielding `None` instead keeps the
# consumer running so it can report "reconnecting" and keep the pane alive,
# which is what the spec's "the pane never silently freezes" requires.
RECONNECT_TICK_S = 0.25


# LiveATC's stream servers answer 403 to ffmpeg's own User-Agent ("Lavf/..."),
# any version, while serving the identical request under any other name --
# measured 2026-10-10: curl, a bare "Mozilla/5.0" and squelch's own UA all got
# 200 from the same server that refused Lavf. Nothing on screen says so: the
# feed just sits on "connecting" forever, because a 403 looks like any other
# dropout to the reconnect loop. So name ourselves, as the feed-list fetch does.
def ffmpeg_command(url: str) -> list[str]:
    return [
        "ffmpeg",
        "-hide_banner",
        "-loglevel", "error",
        "-nostdin",
        # An input option: it has to come before the -i it applies to.
        "-user_agent", USER_AGENT,
        "-i", url,
        "-vn",
        "-ac", "1",
        "-ar", str(SAMPLE_RATE),
        "-f", "s16le",
        "-",
    ]


def backoff_delays(cap: float = 30.0) -> Iterator[float]:
    """1, 2, 4, 8, ... capped. Feed dropouts are routine, not exceptional."""
    delay = 1.0
    while True:
        yield min(delay, cap)
        delay *= 2


def _spawn_ffmpeg(url: str) -> subprocess.Popen:
    return subprocess.Popen(
        ffmpeg_command(url),
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )


class StreamReader:
    """Yield fixed-size PCM frames, respawning ffmpeg on failure."""

    def __init__(
        self,
        url: str,
        *,
        spawn: Spawner = _spawn_ffmpeg,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._url = url
        self._spawn = spawn
        self._sleep = sleep
        self._stopped = False
        self._process: subprocess.Popen | None = None
        self.reconnecting = False

    def frames(self) -> Iterator[bytes | None]:
        """Yield PCM frames, or `None` while waiting out a reconnect.

        A `bytes` value is exactly `FRAME_BYTES` of live audio. A `None` is
        a heartbeat emitted roughly every `RECONNECT_TICK_S` while the feed
        is down and the backoff is being waited out: there is no audio to
        deliver, but the consumer must keep running so it can report the
        outage rather than sit blocked inside its `for` statement. The
        consumer must therefore treat `None` as "no audio this tick" -- not
        write it to the speaker, and not feed it to the segmenter.
        """
        delays = backoff_delays()
        while not self._stopped:
            self._process = self._spawn(self._url)
            self.reconnecting = False
            # A partial frame left over from a dead connection belongs to a
            # stream that no longer exists. Splicing it onto the next
            # connection's bytes would produce a frame containing audio from
            # two unrelated sources, so it must be discarded here rather than
            # carried across the reconnect.
            buffer = b""
            delivered = False
            while not self._stopped:
                chunk = self._process.stdout.read(READ_SIZE)
                if not chunk:
                    break
                buffer += chunk
                while len(buffer) >= FRAME_BYTES:
                    yield buffer[:FRAME_BYTES]
                    delivered = True
                    buffer = buffer[FRAME_BYTES:]
                    if self._stopped:
                        break
            self._kill()
            if self._stopped:
                return
            self.reconnecting = True
            if delivered:
                # The previous connection was healthy -- it actually handed
                # us audio -- so this is a fresh outage, not a continuation
                # of the last one. Without resetting, a handful of dropouts
                # over a multi-hour session permanently pins every later
                # gap at the 30 s cap, long after the feed has recovered.
                delays = backoff_delays()
            yield from self._wait_out(next(delays))

    def _wait_out(self, delay: float) -> Iterator[None]:
        """Sleep `delay` in short ticks, yielding `None` after each one."""
        remaining = delay
        while remaining > 0 and not self._stopped:
            step = min(RECONNECT_TICK_S, remaining)
            self._sleep(step)
            remaining -= step
            yield None

    def stop(self) -> None:
        self._stopped = True
        self._kill()

    def _kill(self) -> None:
        if self._process is None:
            return
        proc = self._process
        self._process = None
        try:
            proc.kill()
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            # SIGKILL was sent but the process hasn't been reaped yet
            # (e.g. stuck in uninterruptible I/O). Block until it exits
            # rather than abandoning an unreaped, potentially zombie
            # process.
            try:
                proc.wait()
            except Exception:
                pass
        except Exception:
            pass


def pcm_to_float(pcm: bytes, out: np.ndarray) -> int:
    """Decode s16le bytes into normalised floats, in place.

    Writes into `out` rather than returning an array: this runs on the feed
    thread for every frame, and the destination is a preallocated staging
    buffer.
    """
    samples = np.frombuffer(pcm, dtype="<i2")
    n = min(len(samples), len(out))
    if n:
        # Assignment casts int16 to float32; scaling in place afterwards
        # avoids the dtype juggling `np.multiply(..., out=)` would need.
        out[:n] = samples[:n]
        out[:n] *= 1.0 / 32768.0
    return n
