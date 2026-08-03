"""Where does a real feed actually sit, relative to the gate?

The chatter risk is not the threshold's absolute value -- it is how much
signal sits *near* it. A feed that is either loud or digitally silent
cannot chatter at any threshold; a feed with an open-squelch noise floor
can chatter badly at the wrong one.
"""

from __future__ import annotations

import sys

import numpy as np

from squelch.dsp import BLOCK, SAMPLE_RATE, block_dbfs

BANDS = [
    (-96.0, -90.0, "digital silence"),
    (-90.0, -60.0, "very low"),
    (-60.0, -50.0, "low"),
    (-50.0, -44.0, "just under gate"),
    (-44.0, -36.0, "AMBIGUOUS (gate band)"),
    (-36.0, -30.0, "just over gate"),
    (-30.0, -20.0, "speech"),
    (-20.0, 0.0, "loud speech"),
]


def main(paths):
    for path in paths:
        pcm = np.fromfile(path, dtype="<i2").astype(np.float32) / 32768.0
        usable = (len(pcm) // BLOCK) * BLOCK
        blocks = pcm[:usable].reshape(-1, BLOCK)
        levels = np.array([block_dbfs(b) for b in blocks])
        minutes = len(blocks) * BLOCK / SAMPLE_RATE / 60.0
        print(f"\n=== {path}  ({minutes:.1f} min) ===")
        for low, high, name in BANDS:
            n = int(((levels >= low) & (levels < high)).sum())
            pct = 100.0 * n / len(levels)
            bar = "#" * int(pct / 2)
            print(f"  {low:6.0f}..{high:<6.0f} {name:<22} {pct:5.1f}%  {bar}")

        ambiguous = float(((levels >= -46.0) & (levels < -34.0)).mean() * 100)
        print(f"\n  blocks within +/-6 dB of the -40 gate: {ambiguous:.2f}%")
        if ambiguous < 0.5:
            print("  -> nothing sits near the threshold; chatter is not possible here")
        else:
            print("  -> real occupancy near the threshold; hysteresis earns its keep")

        # Longest run of consecutive blocks inside the ambiguous band: a
        # sustained hover is what actually breathes, not a passing crossing.
        inside = (levels >= -46.0) & (levels < -34.0)
        longest = current = 0
        for flag in inside:
            current = current + 1 if flag else 0
            longest = max(longest, current)
        print(f"  longest sustained hover: {longest} blocks "
              f"({longest * BLOCK / SAMPLE_RATE * 1000:.0f} ms)")


if __name__ == "__main__":
    main(sys.argv[1:])
