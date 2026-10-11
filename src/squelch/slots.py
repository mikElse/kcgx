"""Which feeds get one of the streams LiveATC will let us hold open.

LiveATC allows one address a fixed number of concurrent streams -- measured
2026-10-10 at seven: the first seven of twelve played, and the eighth onward
were cut off with "Connection reset by peer" the moment they connected, each
of them playing perfectly well on its own. squelch opens one stream per feed
and an airport like KORD publishes thirty, so the other twenty-three sat on
"reconnecting" forever. Worse, a few dozen reconnect loops against a server
that is refusing them looks like abuse, and is treated like it: the stream
server stopped answering this address altogether for a quarter of an hour.

So the feeds over the limit are parked -- no playlist fetch, no ffmpeg, no
request of any kind -- rather than left to knock.

Kept apart from the UI and from `FeedSession` because the interesting part
is the order of precedence, not the starting and stopping.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

# Measured, not documented: LiveATC publishes no figure. Configurable as
# `max_streams` for the day it changes.
MAX_STREAMS = 7


def plan(
    items: Sequence,
    limit: int,
    *,
    audible_of: Callable[[object], bool],
    connected_of: Callable[[object], bool],
    activity_of: Callable[[object], float],
) -> list:
    """The items that should hold a stream, at most `limit` of them.

    In order of precedence:

    1. Everything audible. Those are what you are listening to; a feed you
       unmuted and cannot hear would read as broken. The UI refuses to make
       more than `limit` audible, so this alone never overflows -- and if it
       somehow did, the earliest win rather than all of them failing.
    2. Muted feeds that already hold a stream, busiest first. They spend the
       spare slots metering, which is what keeps the activity ranking alive.
       Preferring the ones already connected is what stops slots churning;
       ordering them by activity is what makes the quietest one the one that
       gives up its place when an audible feed needs it.
    3. Muted feeds that do not, in the order given, to fill whatever is left.
    """
    if limit <= 0:
        return []
    audible = [item for item in items if audible_of(item)]
    muted = [item for item in items if not audible_of(item)]
    # sorted() is stable, so equally quiet feeds keep the order given and a
    # recompute does not swap two idle feeds in and out.
    held = sorted(
        (item for item in muted if connected_of(item)),
        key=lambda item: -activity_of(item),
    )
    waiting = [item for item in muted if not connected_of(item)]
    return (audible + held + waiting)[:limit]
