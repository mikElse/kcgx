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
_STRONG_RE = re.compile(r"<strong>([^<]{1,80})</strong>", re.IGNORECASE)


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

    Feeds are anchored on /play/<ident>.pls links. Each feed's link lives
    inside its own `<table class="body">...</table>` block, whose *first*
    <strong> element is the human-readable feed name (e.g. "KPDX Tower
    (Both)") -- earlier in the DOM than the "Feed Status:"/"Listeners:"
    labels that also use <strong> further down the same table. The label
    falls back to a title-cased ident if no such heading can be found, so a
    label is never empty.
    """
    feeds: list[Feed] = []
    seen: set[str] = set()
    for match in _FEED_LINK_RE.finditer(html):
        ident = match.group(1).lower()
        if ident in seen:
            continue
        seen.add(ident)
        feeds.append(Feed(ident=ident, label=_label_for(html, match.start(), ident)))
    if not feeds:
        raise FeedError("no feeds found on page")
    return feeds


def _label_for(html: str, pos: int, ident: str) -> str:
    """Find the display label for the feed link at `pos`.

    Walk backward to the start of the enclosing `<table` for this feed, then
    take the first <strong>...</strong> at or after that point but before the
    link itself -- that's the feed name, not one of the later status labels.
    """
    table_start = html.rfind("<table", 0, pos)
    search_start = table_start if table_start != -1 else max(0, pos - 1500)
    match = _STRONG_RE.search(html, search_start, pos)
    if match:
        return _clean(match.group(1))
    return ident.replace("_", " ").upper()


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
