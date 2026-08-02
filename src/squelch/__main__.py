"""Command line entry point."""

from __future__ import annotations

import argparse
import sys
import threading
from collections.abc import Callable
from dataclasses import replace

from squelch.app import SquelchApp
from squelch.asr import Transcript, WhisperTranscriber
from squelch.audio import Player, StreamReader
from squelch.config import Config, load_config
from squelch.feeds import fetch_feeds, resolve_stream
from squelch.pipeline import Events, Pipeline
from squelch.vad import Segmenter


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="squelch", description=__doc__)
    parser.add_argument("--feed", help="LiveATC feed ident, e.g. kpdx3_twr")
    parser.add_argument("--icao", help="Airport ICAO for the feed picker")
    return parser.parse_args(argv)


def try_start(
    start: Callable[[], None], on_error: Callable[[str], None], message: str
) -> bool:
    """Run a startup step, degrading rather than crashing.

    A missing model or unavailable audio device should cost you one feature,
    not the whole application.
    """
    try:
        start()
    except Exception:
        on_error(message)
        return False
    return True


class _NullTranscriber:
    """Stands in when the model will not load, so audio still plays."""

    def transcribe(self, pcm: bytes) -> Transcript:
        return Transcript(text="", avg_logprob=0.0)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    config = load_config()
    if args.feed:
        config = replace(config, feed=args.feed)
    if args.icao:
        config = replace(config, icao=args.icao)

    app = SquelchApp(
        config,
        feed_label=config.feed,
        feed_loader=lambda: fetch_feeds(config.icao),
    )

    player = Player()
    transcriber = WhisperTranscriber(config.model, compute_type=config.compute_type)
    app.on_mute_change = lambda muted: setattr(player, "muted", muted)

    events = Events(
        on_level=lambda d: app.call_from_thread(app.set_level, d),
        on_pending=lambda: app.call_from_thread(app.mark_pending),
        on_block=lambda b: app.call_from_thread(app.add_block, b),
        on_state=lambda s: app.call_from_thread(app.set_state, s),
        on_dropped=lambda: app.call_from_thread(app.mark_dropped),
    )

    def _safe_call(func: Callable[..., None], *call_args) -> None:
        """Marshal onto the UI thread without ever raising back onto ours.

        Unlike the five `Events` callbacks above -- which route through
        `Pipeline._emit`'s own exception-swallowing wrapper -- calls made
        directly from this module (`warn()`, and the offline-state signal
        below) have no such guard. If the app has already quit by the time
        one of these fires (e.g. `try_start`'s `on_error`, or feed
        resolution failing right as the user hits `q`), `call_from_thread`
        raises `RuntimeError("App is not running")`. That's harmless --
        there is nobody left to warn -- but left uncaught it would kill
        this background thread with a stray traceback: the same hazard
        class hardened against in the Pipeline itself (Task 6).
        """
        try:
            app.call_from_thread(func, *call_args)
        except Exception:
            pass

    def warn(message: str) -> None:
        _safe_call(app.warn, message)

    def run_pipeline() -> None:
        # The model load below is synchronous and blocking: nothing else in
        # this function -- including player.start(), so audio itself --
        # runs until it returns. On a first run that's a ~1.5 GB download
        # plus load, i.e. several minutes of an apparently dead pane if the
        # user isn't told why. Surfacing that expectation, and its outcome,
        # is deliberately the only change made here: backgrounding the load
        # and hot-swapping the transcriber once ready would be the better
        # long-term fix, but is more machinery than this final task should
        # introduce (see README's "Known limitations").
        warn(
            "loading transcription model — first run downloads roughly "
            "1.5 GB and can take several minutes"
        )
        active = transcriber
        if try_start(transcriber.load, warn, "model unavailable — audio only"):
            warn("transcription model ready")
        else:
            active = _NullTranscriber()
        try_start(player.start, warn, "no audio device — transcribing only")

        try:
            url = resolve_stream(config.feed)
        except Exception:
            warn(f"could not resolve feed {config.feed}")
            # The header must not keep claiming "● LIVE" once nothing is
            # actually playing -- see set_state's "offline" entry.
            _safe_call(app.set_state, "offline")
            return

        Pipeline(
            StreamReader(url),
            Segmenter(aggressiveness=config.vad_aggressiveness),
            active,
            player,
            events,
        ).run()

    threading.Thread(target=run_pipeline, daemon=True).start()
    app.run()
    player.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
