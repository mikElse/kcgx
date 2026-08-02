"""Solo: hear one feed, then get your mix back.

Kept apart from the UI and from `FeedSession` because the interesting part
is not muting -- it is that engaging records the mix so one press returns to
it, and that the recording has to survive the solo moving to another feed
while being discarded the moment the user mutes something by hand.
"""

from __future__ import annotations


class Solo:
    def __init__(self) -> None:
        self._recorded: dict | None = None
        self.target = None

    @property
    def active(self) -> bool:
        return self._recorded is not None

    def engage(self, target, states: dict) -> dict:
        """Mute everything but `target`, recording `states` the first time.

        Moving the solo to a different feed deliberately does *not*
        re-record: the recording is of the mix the user built, and the mixes
        that solo itself creates are not worth returning to.
        """
        if self._recorded is None:
            self._recorded = dict(states)
        self.target = target
        return {key: key != target for key in states}

    def disengage(self) -> dict | None:
        recorded, self._recorded = self._recorded, None
        self.target = None
        return recorded

    def cancel(self) -> None:
        """Drop the recording without restoring it.

        Called when the user mutes something by hand while solo is active:
        they have expressed a new intent, so returning to the old mix later
        would undo it.
        """
        self._recorded = None
        self.target = None

    def is_soloed(self, key) -> bool:
        return self.active and key == self.target
