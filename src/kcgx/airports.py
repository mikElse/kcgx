"""The airport dataset, and searching it.

Pure data: no Textual, no tmux, no network. Everything here is a function
of the committed CSV.
"""

from __future__ import annotations

from pathlib import Path

DATA_PATH = Path(__file__).parent / "data" / "airports.csv"
