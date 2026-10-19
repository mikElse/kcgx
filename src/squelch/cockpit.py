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
