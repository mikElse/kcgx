"""Discovery and resolution of LiveATC.net feeds."""

from __future__ import annotations

import re
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass

Fetcher = Callable[[str], str]

BASE = "https://www.liveatc.net"
USER_AGENT = "squelch/0.1 (personal listener)"

_PLS_FILE_RE = re.compile(r"^\s*File\d+\s*=\s*(\S+)\s*$", re.MULTILINE)
_FEED_LINK_RE = re.compile(r"/play/([a-z0-9_\-]+)\.pls", re.IGNORECASE)
# Attribute-tolerant: matches <strong>, <strong class="x">, <STRONG>, etc.
_STRONG_RE = re.compile(r"<strong[^>]*>([^<]{1,80})</strong>", re.IGNORECASE)
# LiveATC's boilerplate <strong> rows are always a "Field:" caption or a bare
# status word -- real feed names are neither, so this is used to filter
# out captions/status without hardcoding every phrase the site might use.
_STATUS_WORDS = {"UP", "DOWN"}


class FeedError(Exception):
    """A feed could not be discovered or resolved."""


@dataclass(frozen=True)
class Feed:
    ident: str
    label: str


def pls_url(ident: str) -> str:
    return f"{BASE}/play/{ident}.pls"


def airport_url(icao: str) -> str:
    return f"{BASE}/search/?icao={icao.lower()}"


def parse_pls(text: str) -> str:
    """Return the first stream URL in a PLS playlist."""
    match = _PLS_FILE_RE.search(text)
    if not match:
        raise FeedError("no File entry in playlist")
    return match.group(1)


def parse_airport_page(html: str) -> list[Feed]:
    """Extract feeds from a LiveATC airport search page.

    Feeds are anchored on /play/<ident>.pls links. Each feed's link lives in
    a block whose first <strong> element is the human-readable feed name
    (e.g. "KPDX Tower (Both)") -- earlier in the DOM than the "Feed
    Status:"/"Listeners:" captions that also use <strong> further down. The
    label falls back to a title-cased ident if no such heading can be found,
    so a label is never empty.
    """
    feeds: list[Feed] = []
    seen: set[str] = set()
    window_start = 0
    for match in _FEED_LINK_RE.finditer(html):
        ident = match.group(1).lower()
        if ident in seen:
            continue
        seen.add(ident)
        label = _label_for(html, window_start, match.start(), ident)
        feeds.append(Feed(ident=ident, label=label))
        window_start = match.end()
    if not feeds:
        raise FeedError("no feeds found on page")
    return feeds


def _label_for(html: str, window_start: int, pos: int, ident: str) -> str:
    """Find the display label for the feed link at `pos`.

    Deliberately does *not* anchor on any enclosing `<table` -- a stray or
    injected `<table>` between a feed's real label and its link (e.g. an ad
    block) would make a "nearest preceding <table>" heuristic latch onto the
    wrong block and silently return the wrong text. Instead this scans the
    region between the end of the *previous* feed's link (or the start of
    the document, for the first feed) and the start of this feed's link, and
    returns the first <strong> in that region that isn't a boilerplate
    caption/status ("Feed Status:", "Listeners:", "UP", "DOWN", ...). Since
    the real label always appears before any of a feed's own boilerplate
    rows -- and, per the observed markup, before any ad content too -- the
    first non-boilerplate <strong> in the window is the label, regardless of
    what shows up structurally (nested tables, extra attributes) after it.

    Note: this assumes injected content sits *after* the real label, which
    matches every case observed on the live page. Non-boilerplate text
    injected *before* the label within the same window would still fool
    this, same as any positional heuristic would.
    """
    window = html[window_start:pos]
    for candidate in _STRONG_RE.finditer(window):
        text = _clean(candidate.group(1))
        if _is_boilerplate(text):
            continue
        return text
    return ident.replace("_", " ").upper()


def _is_boilerplate(text: str) -> bool:
    return text.endswith(":") or text.upper() in _STATUS_WORDS


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _http_get(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=15) as response:
        return response.read().decode("utf-8", errors="replace")


def fetch_feeds(icao: str, fetch: Fetcher = _http_get) -> list[Feed]:
    return parse_airport_page(fetch(airport_url(icao)))


def resolve_stream(ident: str, fetch: Fetcher = _http_get) -> str:
    return parse_pls(fetch(pls_url(ident)))
