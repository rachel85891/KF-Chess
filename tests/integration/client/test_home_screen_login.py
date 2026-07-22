"""Real, end-to-end integration test for Stage C1's shell login flow
(kungfu_chess/client/home_screen.py) - a REAL GameServer-backed server
(own background thread + loop) and a REAL NetworkGameLoopRunner
connection (constructed with headless=True - this project's own
established convention for exercising real network/client behavior
without a real display, see
tests/integration/client/test_network_game_loop_runner.py's own module
docstring for the full reasoning), mirroring this project's
established "real server, real client, no mocking" convention for
everything network-related.

WHAT THIS TEST DOES NOT COVER, AND WHY: run_shell_login_and_launch's
own prompt/validation/welcome-formatting/server_full logic is already
fully covered, with a fake connect_fn/launch_gui_fn, by
tests/unit/client/test_home_screen.py - re-testing that logic here
against a real server would duplicate coverage without proving
anything new. This test's own, distinct job is narrower and genuinely
different: proving the injected `connect_fn` this module actually uses
in production (constructing a real NetworkGameLoopRunner) really does
reach a real running server and really does yield the correct,
server-assigned Color - exactly the same real connection behavior
tests/integration/client/test_network_game_loop_runner.py's own
test_constructing_in_headless_mode_reads_the_correct_assigned_color
already proves for NetworkGameLoopRunner directly, now proven again
through run_shell_login_and_launch's own real call path instead of a
fake one. launch_gui_fn is still injected as a spy here (not the real
_default_launch_gui) - actually calling runner.run() would enter a
real, indefinitely-running frame loop with no window to ever close it
(this class's own two exit conditions, _should_exit, both require
either a real 'q' keypress or a real window close - neither is
possible in headless mode), which is unrelated to what THIS test
proves; the spy simply closes the real connection once it is handed
the runner, and records the call for assertion.
"""

from __future__ import annotations

import asyncio
import threading

import websockets

from kungfu_chess.client.home_screen import format_welcome_message
from kungfu_chess.client.home_screen import run_shell_login_and_launch
from kungfu_chess.client.loop.network_game_loop_runner import NetworkGameLoopRunner
from kungfu_chess.model.color import Color
from server.application.game_server import GameServer

_JOIN_TIMEOUT_S = 5.0


class _BackgroundTestServer:
    """Identical in shape to tests/integration/client/
    test_network_game_client.py's own _BackgroundTestServer - see that
    file's own docstring for the full reasoning (a real server on its
    own background thread + loop, separate from any
    NetworkGameLoopRunner's own background thread)."""

    def __init__(self) -> None:
        self.uri: str = ""
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop_event: asyncio.Event | None = None
        ready = threading.Event()
        self._thread = threading.Thread(target=self._run, args=(ready,), daemon=True)
        self._thread.start()
        if not ready.wait(timeout=_JOIN_TIMEOUT_S):
            raise RuntimeError("background test server failed to start in time")

    def _run(self, ready: threading.Event) -> None:
        asyncio.run(self._serve(ready))

    async def _serve(self, ready: threading.Event) -> None:
        game_server = GameServer()
        server = await websockets.serve(game_server.handle_connection, "localhost", 0)
        tick_task = asyncio.create_task(game_server.run_tick_loop())
        port = server.sockets[0].getsockname()[1]
        self.uri = f"ws://localhost:{port}"
        self._loop = asyncio.get_running_loop()
        self._stop_event = asyncio.Event()
        ready.set()

        await self._stop_event.wait()

        tick_task.cancel()
        server.close()
        await server.wait_closed()

    def stop(self) -> None:
        if self._loop is not None and self._stop_event is not None:
            self._loop.call_soon_threadsafe(self._stop_event.set)
        self._thread.join(timeout=_JOIN_TIMEOUT_S)


def test_shell_login_connects_to_a_real_server_and_shows_the_correct_assigned_color():
    test_server = _BackgroundTestServer()
    printed: list[str] = []
    launched_runners: list[NetworkGameLoopRunner] = []

    def fake_input(prompt: str) -> str:
        return "Alice"

    def real_connect(uri: str, username: str | None) -> NetworkGameLoopRunner:
        # The exact real connection path production code uses (mirrors
        # home_screen.py's own _default_connect) - see module docstring
        # for why headless=True is the correct, established substitute
        # for a real display here. `username` is threaded through to
        # NetworkGameLoopRunner's own constructor parameter (feature/
        # display-username-and-local-player-label), proving it reaches
        # a REAL runner via this real connect path, not just a fake one.
        return NetworkGameLoopRunner(uri, headless=True, username=username)

    def spy_launch_gui(runner: NetworkGameLoopRunner) -> None:
        launched_runners.append(runner)
        runner.close()

    try:
        run_shell_login_and_launch(
            test_server.uri,
            input_fn=fake_input,
            output_fn=printed.append,
            connect_fn=real_connect,
            launch_gui_fn=spy_launch_gui,
        )
    finally:
        test_server.stop()

    assert len(launched_runners) == 1
    real_runner = launched_runners[0]
    assert real_runner.assigned_color == Color.WHITE
    assert real_runner.username == "Alice"

    assert format_welcome_message("Alice", Color.WHITE) in printed
