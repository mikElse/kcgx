"""What crosses the WebSocket, in both directions.

Pure functions from cockpit state to JSON-ready dicts, and a strict parser
for what a page may send. Kept apart from the server so every shape can be
tested without a socket, and so the page has one file to read to learn the
protocol.

Feeds are addressed by ident everywhere, including in the level and
chatter frames, which are keyed by ident rather than given in stack order:
the order can change between two frames, and a positional list would
attribute one frame's levels to the wrong rows.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Callable, Iterable
from typing import Any

from kcgx.prefs import SCHEMA, CellError, defaults

PROTOCOL = 1

# LiveATC idents as parse_airport_page leaves them: lower case, digits and
# underscores. Anything else from a page is not an ident.
IDENT_RE = re.compile(r"[a-z0-9_]{1,64}")

# `select` is the page's: one feed audible, the rest muted (phase G
# decision 3). `mute` and `solo` stay for /debug; the page no longer sends them.
IDENT_ACTIONS = ("select", "mute", "solo", "ambient")

# A feed's title as the page shows it, for a session. The station's says the
# name without the airport (kcgx.names); without one, the title is the name.
TitleOf = Callable[[Any], str]


def encode(frame: dict) -> str:
    """Compact JSON, UTF-8 left as is (feed names carry em dashes)."""
    return json.dumps(frame, separators=(",", ":"), ensure_ascii=False)


# -- server to page ----------------------------------------------------------


def feed_view(session: Any, title_of: TitleOf | None = None) -> dict:
    return {
        "ident": session.feed.ident,
        "label": session.feed.label,
        "name": session.name,
        "title": title_of(session) if title_of else session.name,
        "state": session.state,
        "muted": bool(session.muted),
        "soloed": bool(getattr(session, "soloed", False)),
        "ambient": bool(getattr(session, "ambient", False)),
        "connected": bool(session.connected),
        "chatter": round(float(session.activity), 3),
    }


def airport_view(airport: Any, icao: str) -> dict:
    """The airport as the page shows it. `airport` is a kcgx.airports.Airport,
    or None for an ICAO the dataset does not know."""
    if airport is None:
        return {"icao": icao, "iata": "", "name": "", "where": "", "lat": None, "lon": None}
    return {
        "icao": airport.icao,
        "iata": airport.iata,
        "name": airport.name,
        "where": airport.where,
        "lat": airport.lat,
        "lon": airport.lon,
    }


def snapshot(
    *,
    airport: Any,
    icao: str,
    loading: bool,
    sessions: Iterable,
    volume: float,
    muted: bool = False,
    max_streams: int,
    audio_ok: bool,
    log: Iterable[dict],
    prefs: dict | None = None,
    radar: dict | None = None,
    title_of: TitleOf | None = None,
) -> dict:
    """Everything a page needs to draw from nothing: sent on connect and
    after every airport change."""
    return {
        "t": "snapshot",
        "protocol": PROTOCOL,
        "airport": airport_view(airport, icao),
        "loading": bool(loading),
        "feeds": [feed_view(s, title_of) for s in sessions],
        "volume": round(float(volume), 2),
        "muted": bool(muted),
        "max_streams": int(max_streams),
        "audio_ok": bool(audio_ok),
        "log": list(log),
        "prefs": dict(prefs) if prefs else defaults(),
        "radar": radar,
    }


def feed_frame(session: Any, title_of: TitleOf | None = None) -> dict:
    return {"t": "feed", "feed": feed_view(session, title_of)}


def added_frame(session: Any, title_of: TitleOf | None = None) -> dict:
    return {"t": "added", "feed": feed_view(session, title_of)}


def order_frame(sessions: Iterable) -> dict:
    return {"t": "order", "idents": [s.feed.ident for s in sessions]}


def levels_frame(sessions: Iterable) -> dict:
    return {"t": "levels", "v": {s.feed.ident: round(float(s.level), 1) for s in sessions}}


def chatter_frame(sessions: Iterable) -> dict:
    return {"t": "chatter", "v": {s.feed.ident: round(float(s.activity), 3) for s in sessions}}


def volume_frame(value: float, muted: bool = False) -> dict:
    """The master volume and the master mute, which leaves the volume as it
    was: the server's audio state, not prefs."""
    return {"t": "volume", "value": round(float(value), 2), "muted": bool(muted)}


def prefs_frame(prefs: dict) -> dict:
    return {"t": "prefs", **prefs}


def message_frame(entry: dict) -> dict:
    return {"t": "message", **entry}


def error_frame(text: str) -> dict:
    return {"t": "error", "text": text}


# -- page to server ----------------------------------------------------------


class BadMessage(ValueError):
    """A page sent something this protocol does not have."""


def parse_client(text: str) -> dict:
    """Validate one message from a page, or raise BadMessage.

    Strict on purpose: every field is checked for type and shape, and
    anything unrecognised is refused rather than ignored, so a page bug
    shows up as an error frame instead of a control that silently does
    nothing.
    """
    try:
        data = json.loads(text)
    except (ValueError, RecursionError):  # nested too deep to read is not JSON here either
        raise BadMessage("not JSON") from None
    if not isinstance(data, dict):
        raise BadMessage("not a JSON object")
    kind = data.get("t")
    if kind in IDENT_ACTIONS:
        return {"t": kind, "ident": _ident(data)}
    if kind == "open_feed":
        return {"t": "open_feed", "ident": _ident(data)}
    if kind == "volume":
        value = data.get("value")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise BadMessage("volume needs a number")
        if not math.isfinite(value):
            raise BadMessage("volume needs a finite number")
        return {"t": "volume", "value": min(1.0, max(0.0, float(value)))}
    if kind == "master_mute":
        on = data.get("on")
        if not isinstance(on, bool):
            raise BadMessage("master_mute needs on: true or false")
        return {"t": "master_mute", "on": on}
    if kind == "input":
        return {"t": "input"}
    if kind == "prefs":
        return {"t": "prefs", **_prefs(data)}
    raise BadMessage(f"unknown message type: {kind!r}")


def _prefs(data: dict) -> dict:
    """At least one setting from kcgx.prefs.SCHEMA, each as its kind allows,
    and nothing else: a name the schema does not have refuses the message
    even beside ones it does, so a mistyped setting is not silently dropped.
    Names are exact: the page sends what the server sent it. What comes back
    is canonical (a subset in schema order, without repeats). A table may be
    sent in part, any of its cells; one bad cell refuses the message too,
    and the refusal names it (`map.COAST.alpha`)."""
    for key in data:
        if key != "t" and key not in SCHEMA:
            raise BadMessage(f"unknown setting: {key}")
    changes = {}
    for key, spec in SCHEMA.items():
        if key not in data:
            continue
        try:
            changes[key] = spec.check(data[key])
        except CellError as bad:
            raise BadMessage(f"{key}.{bad.where} {bad.reason}") from None
        except ValueError as reason:
            raise BadMessage(f"{key} {reason}") from None
    if not changes:
        raise BadMessage("prefs needs at least one setting")
    return changes


def _ident(data: dict) -> str:
    value = data.get("ident")
    if not isinstance(value, str) or not IDENT_RE.fullmatch(value):
        raise BadMessage("bad feed ident")
    return value
