"""Stream acquisition and playback.

One ffmpeg process decodes the feed to 16 kHz mono PCM. Those frames feed
both the speaker and the transcription pipeline, so the two can never drift
apart.
"""

from __future__ import annotations

import subprocess
import time
from collections.abc import Callable, Iterator

from squelch.vad import FRAME_BYTES, SAMPLE_RATE

Spawner = Callable[[str], subprocess.Popen]

READ_SIZE = FRAME_BYTES * 4


def ffmpeg_command(url: str) -> list[str]:
    return [
        "ffmpeg",
        "-hide_banner",
        "-loglevel", "error",
        "-nostdin",
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

    def frames(self) -> Iterator[bytes]:
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
            while not self._stopped:
                chunk = self._process.stdout.read(READ_SIZE)
                if not chunk:
                    break
                buffer += chunk
                while len(buffer) >= FRAME_BYTES:
                    yield buffer[:FRAME_BYTES]
                    buffer = buffer[FRAME_BYTES:]
                    if self._stopped:
                        break
            self._kill()
            if self._stopped:
                return
            self.reconnecting = True
            self._sleep(next(delays))

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


class Player:
    """Speaker output. Muting stops audio but never stops transcription."""

    def __init__(self) -> None:
        self.muted = False
        self._stream = None

    def start(self) -> None:
        import sounddevice

        self._stream = sounddevice.RawOutputStream(
            samplerate=SAMPLE_RATE, channels=1, dtype="int16"
        )
        self._stream.start()

    def write(self, pcm: bytes) -> None:
        if self._stream is None or self.muted:
            return
        try:
            self._stream.write(pcm)
        except Exception:
            pass  # An underrun must never take down the pipeline.

    def toggle_mute(self) -> bool:
        self.muted = not self.muted
        return self.muted

    def stop(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
