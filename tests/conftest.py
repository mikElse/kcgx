"""Suite-wide safety nets.

Nothing here replaces a test's own explicit setup. These are backstops: the
things that must hold even when a test forgets, and — more to the point —
even when the code under test is broken in the exact way a test is trying
to prove it is not.
"""

from __future__ import annotations

import pytest

import kcgx.state


@pytest.fixture(autouse=True)
def isolate_kcgx_state(tmp_path, monkeypatch):
    """Keep every test's idea of the remembered airport inside tmp_path.

    `kcgx.state` resolves its default in two steps: the KCGX_STATE_PATH
    environment variable, then the STATE_PATH constant under $HOME. Tests
    that care about that precedence set the environment themselves and this
    fixture gets out of their way — but a test proving the precedence works
    is exactly the test that runs while the precedence is *broken*, and a
    break in either direction routes an unqualified `write_airport()` at the
    real ~/.local/state/kcgx/airport. That has already put a file in the
    owner's home directory once in this project's history.

    So all three levers are redirected, not one:

    - KCGX_STATE_PATH, which is what a test normally overrides, and what
      reaches Python through a subprocess (the launcher's server, the self check);
    - kcgx.state.STATE_PATH, for anything in-process that ignores the env
      var -- the constant is bound at import, so patching HOME cannot
      reach it;
    - HOME, for anything in a *subprocess* that ignores the env var -- there
      the constant is computed fresh at import from Path.home(), so the env
      var is the only lever the parent process has, and it is precisely the
      lever a seam break removes.

    That third one is not hypothetical. Breaking the precedence with only
    the first two in place still wrote KORD into the owner's real
    ~/.local/state/kcgx/airport, from `kcgx go KORD` two processes down.

    Tests keep their own explicit `path=` and KCGX_STATE_PATH usages; this
    sits underneath them.
    """
    path = tmp_path / "kcgx-state-backstop" / "airport"
    monkeypatch.setattr(kcgx.state, "STATE_PATH", path)
    monkeypatch.setenv("KCGX_STATE_PATH", str(path))

    home = tmp_path / "kcgx-state-backstop" / "home"
    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HOME", str(home))
    return path
