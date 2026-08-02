"""Discovery and resolution of LiveATC.net feeds."""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

Fetcher = Callable[[str], str]

BASE = "https://www.liveatc.net"
USER_AGENT = "squelch/0.1 (personal listener)"

_PLS_FILE_RE = re.compile(r"^\s*File\d+\s*=\s*(\S+)\s*$", re.MULTILINE)
_FEED_LINK_RE = re.compile(r"/play/([a-z0-9_\-]+)\.pls", re.IGNORECASE)
# Attribute-tolerant: matches <strong>, <strong class="x">, <STRONG>, etc.
_STATUS_MARKER_RE = re.compile(r"^\s*feed\s+status", re.IGNORECASE)
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

    Scans the region between the end of the previous feed's link (or the
    start of the document, for the first feed) and the start of this one's,
    and anchors on the feed's own status block: every feed on the page
    renders as

        <strong>NAME</strong> ... <strong>Feed Status:</strong> UP ...

    so the label is the **last non-boilerplate <strong> before "Feed
    Status:"**. Anchoring on that marker rather than on a position is what
    makes this robust in both directions:

    - Taking the *first* non-boilerplate <strong> in the window breaks the
      opening feed, whose window starts at the top of the document. On the
      live KPDX page that region holds section headings ("KPDX ADS-B Flight
      Tracking"), and the first feed came back labelled with one.
    - Taking the *last* breaks on anything injected after the name -- an ad
      block carrying its own <strong> sits between the status rows and the
      play link.

    Deliberately does *not* anchor on any enclosing `<table`: a stray or
    injected `<table>` between a feed's label and its link would make a
    "nearest preceding <table>" heuristic latch onto the wrong block.
    """
    window = html[window_start:pos]
    candidates = [
        (match.start(), _clean(match.group(1)))
        for match in _STRONG_RE.finditer(window)
    ]
    status_at = max(
        (at for at, text in candidates if _STATUS_MARKER_RE.match(text)),
        default=None,
    )
    if status_at is not None:
        candidates = [(at, text) for at, text in candidates if at < status_at]

    for _at, text in reversed(candidates):
        if not _is_boilerplate(text):
            return text
    return ident.replace("_", " ").upper()


def _is_boilerplate(text: str) -> bool:
    return text.endswith(":") or text.upper() in _STATUS_WORDS


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


# LiveATC fronts /search/ with Cloudflare bot protection. Measured against
# the live site: a browser User-Agent does not help, spacing requests out
# does not help, and roughly one request in four is allowed through anyway.
# So a 403 here is a coin flip to be re-flipped, not an answer. (/play/*.pls
# is not protected, which is why streaming works regardless.)
CHALLENGE_STATUSES = frozenset({403, 429, 503})
FETCH_ATTEMPTS = 5

CACHE_DIR = Path.home() / ".cache" / "squelch"
# Feed lists change on the order of months, and every fetch is a request to
# somebody else's server that mostly gets refused. A week-old list is much
# better than another handful of 403s at every startup.
CACHE_TTL_SECONDS = 7 * 24 * 60 * 60


def http_get_with_retry(
    url: str,
    *,
    get: Fetcher | None = None,
    sleep: Callable[[float], None] = time.sleep,
    attempts: int = FETCH_ATTEMPTS,
) -> str:
    """GET `url`, re-flipping the coin on a bot-protection challenge.

    Only challenge statuses are retried: a 404 is a real answer and
    retrying it just delays the failure.
    """
    fetch = get or _http_get_once
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            return fetch(url)
        except urllib.error.HTTPError as exc:
            if exc.code not in CHALLENGE_STATUSES:
                raise
            last = exc
            if attempt < attempts - 1:
                sleep(min(0.5 * (2 ** attempt), 4.0))
    assert last is not None
    raise last


def cache_path(icao: str, *, directory: Path | None = None) -> Path:
    return (directory or CACHE_DIR) / f"feeds-{icao.lower()}.json"


def write_cached_feeds(
    icao: str, feeds: list[Feed], *, directory: Path | None = None
) -> None:
    path = cache_path(icao, directory=directory)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps([{"ident": f.ident, "label": f.label} for f in feeds])
        )
    except OSError:
        # A cache that cannot be written is a missed optimisation, not a
        # reason to fail a launch.
        pass


def read_cached_feeds(
    icao: str, *, directory: Path | None = None
) -> list[Feed] | None:
    path = cache_path(icao, directory=directory)
    try:
        data = json.loads(path.read_text())
        return [Feed(ident=item["ident"], label=item["label"]) for item in data]
    except (OSError, ValueError, KeyError, TypeError):
        return None


def cached_age_seconds(icao: str, *, directory: Path | None = None) -> float | None:
    path = cache_path(icao, directory=directory)
    try:
        return max(0.0, time.time() - path.stat().st_mtime)
    except OSError:
        return None


def _http_get_once(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=15) as response:
        return response.read().decode("utf-8", errors="replace")


def fetch_feeds(icao: str, fetch: Fetcher | None = None) -> list[Feed]:
    if fetch is not None:
        return parse_airport_page(fetch(airport_url(icao)))
    return parse_airport_page(http_get_with_retry(airport_url(icao)))


def resolve_stream(ident: str, fetch: Fetcher = _http_get_once) -> str:
    # /play/ is not behind the bot protection that /search/ is, so no retry
    # loop here -- a failure is a real failure.
    return parse_pls(fetch(pls_url(ident)))
