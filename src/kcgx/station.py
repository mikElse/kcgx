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
from kcgx.prefs import DEFAULTS, write_prefs
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
        prefs: dict | None = None,
        remember_prefs: Callable[[dict], None] = write_prefs,
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
        self._remember_prefs = remember_prefs
        self.prefs = dict(prefs or DEFAULTS)
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
            self.hub.note(_for_the_page(message))
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
        elif kind == "prefs":
            self.set_prefs({k: v for k, v in message.items() if k != "t"})

    def set_volume(self, value: float) -> None:
        self.mixer.volume = float(value)
        self.hub.broadcast(protocol.volume_frame(self.mixer.volume))

    def set_prefs(self, changes: dict) -> None:
        """Palette, glow or display, already validated by the protocol.
        Remembered, and sent to every page so all tabs look the same."""
        self.prefs = {**self.prefs, **changes}
        self._remember_prefs(self.prefs)
        self.hub.broadcast(protocol.prefs_frame(self.prefs))

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
            prefs=self.prefs,
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


def _for_the_page(message: str) -> str:
    """squelch's listing warnings name the terminal's key; the page's retry
    is the FEEDS button, whose list is fetched afresh on every open."""
    return message.replace("press f to retry", "open FEEDS to retry")
