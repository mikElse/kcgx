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
