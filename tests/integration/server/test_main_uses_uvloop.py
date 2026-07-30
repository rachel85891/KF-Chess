"""Stage G3 smoke test - server/main.py's own main() is a long-lived,
blocking entry point (`server.serve_forever()` inside it, until process
kill), so it is never actually invoked here. Instead this is a
lightweight, source-level confirmation that main()'s own
`asyncio.run(...)` call is wired to uvloop where uvloop is available,
and cleanly falls back to asyncio's own default event loop where it
isn't (uvloop has no Windows support - see server/main.py's own comment
at its `sys.platform` guard and at the `loop_factory` call site).

No existing test imports/calls `server.main.main` directly (verified by
inspection before writing this file) - `test_ws_skeleton.py` only uses
`build_handler`/`echo_message`, Stage B1's own unrelated swap point, not
main()'s composition root. So this file is the only place this stage's
own change is exercised at all, deliberately not exercising the real
uvloop event loop itself under pytest (see the module-level skip below
on Windows, this repo's own dev platform) - closing that gap is left to
a Linux CI/CD run, not this stage.
"""

from __future__ import annotations

import inspect
import sys

import pytest

import server.main


def test_main_wires_loop_factory_with_a_platform_guard() -> None:
    source = inspect.getsource(server.main)
    assert "sys.platform" in source
    assert "loop_factory=_loop_factory" in source


def test_uvloop_is_the_loop_factory_on_non_windows() -> None:
    if sys.platform == "win32":
        pytest.skip(
            "uvloop has no Windows support - see server/main.py's own "
            "sys.platform guard; unexercised on this dev platform, a "
            "real gap left open for a Linux CI/CD run to close."
        )

    import uvloop

    assert server.main._loop_factory is uvloop.new_event_loop


def test_loop_factory_falls_back_to_default_on_windows() -> None:
    if sys.platform != "win32":
        pytest.skip("fallback path is Windows-only; uvloop is used instead")

    assert server.main._loop_factory is None
