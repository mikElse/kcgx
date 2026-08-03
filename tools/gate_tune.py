"""Tune the gate threshold against real ATC audio.

Capture a few minutes of a feed first, with no audio device involved:

    ffmpeg -nostdin -i http://d.liveatc.net/kpdx3_twr \\
        -t 300 -ac 1 -ar 16000 -f s16le -y kpdx3_twr.raw

then:  uv run --project . python tools/gate_tune.py kpdx3_twr.raw


Replays captured s16le/16k PCM through the *real* Compressor, one
BLOCK at a time, and reports for each candidate threshold:

  - toggles/min : how often the gate flips. This is the breathing metric.
  - open %      : fraction of blocks with the gate open.
  - slew        : the largest single-block change in gain_db. With the
                  hysteresis gone the ramp is all that damps this, so a
                  big number here is an audible step.

Nothing opens an audio device; this is arithmetic over a file.
"""

from __future__ import annotations

import sys

import numpy as np

from squelch.dsp import BLOCK, SAMPLE_RATE, Compressor, block_dbfs


def load(path):
    pcm = np.fromfile(path, dtype="<i2").astype(np.float32) / 32768.0
    usable = (len(pcm) // BLOCK) * BLOCK
    return pcm[:usable].reshape(-1, BLOCK)


def level_profile(blocks):
    return np.array([block_dbfs(b) for b in blocks])


def simulate(blocks, *, open_at, close_at):
    comp = Compressor(gate_open=open_at, gate_close=close_at)
    out = np.zeros(BLOCK, dtype=np.float32)
    toggles = 0
    open_blocks = 0
    was_open = comp.gate_open
    previous_gain = comp.gain_db
    max_slew = 0.0
    for block in blocks:
        comp.process(block, out)
        if comp.gate_open != was_open:
            toggles += 1
            was_open = comp.gate_open
        open_blocks += 1 if comp.gate_open else 0
        max_slew = max(max_slew, abs(comp.gain_db - previous_gain))
        previous_gain = comp.gain_db
    minutes = len(blocks) * BLOCK / SAMPLE_RATE / 60.0
    return {
        "toggles_per_min": toggles / max(minutes, 1e-9),
        "open_pct": 100.0 * open_blocks / len(blocks),
        "max_slew_db": max_slew,
    }


def main(paths):
    for path in paths:
        blocks = load(path)
        minutes = len(blocks) * BLOCK / SAMPLE_RATE / 60.0
        levels = level_profile(blocks)
        print(f"\n=== {path}  ({minutes:.1f} min, {len(blocks)} blocks) ===")
        percentiles = [1, 5, 10, 25, 50, 75, 90, 95, 99]
        values = np.percentile(levels, percentiles)
        print("level distribution (dBFS):")
        for p, v in zip(percentiles, values):
            print(f"  p{p:<3} {v:7.1f}")
        print(f"  min {levels.min():7.1f}   max {levels.max():7.1f}")

        print("\n  threshold   toggles/min   open%   max slew dB")
        for open_at in (-70.0, -65.0, -60.0, -55.0, -50.0, -46.0, -44.0, -42.0, -40.0, -38.0, -36.0, -34.0):
            r = simulate(blocks, open_at=open_at, close_at=open_at)
            print(
                f"   {open_at:6.1f}      {r['toggles_per_min']:8.1f}"
                f"   {r['open_pct']:6.1f}      {r['max_slew_db']:6.2f}"
            )

        print("\n  with 6 dB hysteresis, for comparison:")
        for open_at in (-40.0, -50.0, -60.0):
            r = simulate(blocks, open_at=open_at, close_at=open_at - 6.0)
            print(
                f"   {open_at:6.1f}/{open_at - 6.0:6.1f} {r['toggles_per_min']:8.1f}"
                f"   {r['open_pct']:6.1f}      {r['max_slew_db']:6.2f}"
            )


if __name__ == "__main__":
    main(sys.argv[1:])
