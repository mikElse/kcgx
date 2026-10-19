"""The web side must never need Textual: it ships without it in phase E."""

from __future__ import annotations

import subprocess
import sys

import pytest

WEB_MODULES = [
    "squelch.runtime",
    "squelch.cockpit",
    "kcgx.protocol",
    "kcgx.hub",
    "kcgx.station",
]


@pytest.mark.parametrize("module", WEB_MODULES)
def test_importing_it_does_not_import_textual(module):
    probe = f"import sys, {module}; sys.exit('textual' in sys.modules)"
    assert subprocess.run([sys.executable, "-c", probe]).returncode == 0, module
