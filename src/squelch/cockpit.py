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
