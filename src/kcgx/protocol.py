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
from collections.abc import Iterable
from typing import Any

PROTOCOL = 1

# LiveATC idents as parse_airport_page leaves them: lower case, digits and
# underscores. Anything else from a page is not an ident.
IDENT_RE = re.compile(r"[a-z0-9_]{1,64}")

IDENT_ACTIONS = ("mute", "solo", "ambient")


def encode(frame: dict) -> str:
    """Compact JSON, UTF-8 left as is (feed names carry em dashes)."""
    return json.dumps(frame, separators=(",", ":"), ensure_ascii=False)


# -- server to page ----------------------------------------------------------


def feed_view(session: Any) -> dict:
    return {
        "ident": session.feed.ident,
        "label": session.feed.label,
        "name": session.name,
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
    max_streams: int,
    audio_ok: bool,
    log: Iterable[dict],
) -> dict:
    """Everything a page needs to draw from nothing: sent on connect and
    after every airport change."""
    return {
        "t": "snapshot",
        "protocol": PROTOCOL,
        "airport": airport_view(airport, icao),
        "loading": bool(loading),
        "feeds": [feed_view(s) for s in sessions],
        "volume": round(float(volume), 2),
        "max_streams": int(max_streams),
        "audio_ok": bool(audio_ok),
        "log": list(log),
    }


def feed_frame(session: Any) -> dict:
    return {"t": "feed", "feed": feed_view(session)}


def added_frame(session: Any) -> dict:
    return {"t": "added", "feed": feed_view(session)}


def order_frame(sessions: Iterable) -> dict:
    return {"t": "order", "idents": [s.feed.ident for s in sessions]}


def levels_frame(sessions: Iterable) -> dict:
    return {"t": "levels", "v": {s.feed.ident: round(float(s.level), 1) for s in sessions}}


def chatter_frame(sessions: Iterable) -> dict:
    return {"t": "chatter", "v": {s.feed.ident: round(float(s.activity), 3) for s in sessions}}


def volume_frame(value: float) -> dict:
    return {"t": "volume", "value": round(float(value), 2)}


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
    except ValueError:
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
    if kind == "input":
        return {"t": "input"}
    raise BadMessage(f"unknown message type: {kind!r}")


def _ident(data: dict) -> str:
    value = data.get("ident")
    if not isinstance(value, str) or not IDENT_RE.fullmatch(value):
        raise BadMessage("bad feed ident")
    return value
