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
own prompt/validation/welcome-formatting/server_full/wrong_password
logic is already fully covered, with a fake connect_fn/launch_gui_fn,
by tests/unit/client/test_home_screen.py - re-testing that logic here
against a real server would duplicate coverage without proving
anything new. This test's own, distinct job is narrower and genuinely
different: proving the injected `connect_fn` this module actually uses
in production (constructing a real NetworkGameLoopRunner with real
credentials) really does reach a real running server and really does
yield the correct, server-assigned Color AND rating - exactly the same
real connection behavior tests/integration/client/
test_network_game_loop_runner.py's own
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

UPDATED for Stage D2's real auth handshake (feature/home-screen-d2-
auth-protocol): `password_input_fn` is now also faked (a real, fixed
password), forwarded by `real_connect` to NetworkGameLoopRunner's own
now-required `password` parameter; GameServer is constructed with
user_repository_db_path=":memory:" so this test never touches a real
database file; the final assertion now also checks the real, returned
rating.

UPDATED AGAIN for Stage E1's real matchmaking
(feature/matchmaking-elo-queue-e1): NetworkGameLoopRunner's own
constructor now blocks until a rating-compatible opponent has ALSO
joined the matchmaking queue (see server/application/game_server.py's
own "STAGE E1" docstring section) - a single real connection with no
opponent would otherwise wait out the server's own real matchmaking
timeout. A throwaway, same-rated dummy NetworkGameClient is connected
concurrently on a background thread purely to unblock the real
runner's own connect - it plays no further part in this test, mirroring
tests/integration/client/test_network_game_client.py's own
`_connect_with_dummy_opponent` helper. `real_connect` is also handed a
4th `on_searching_for_opponent` parameter now (mirrors home_screen.py's
own `_default_connect` signature) - unused here since this test does
not assert anything about the searching-for-opponent UX, which is
already covered by tests/unit/client/test_home_screen.py.
"""

from __future__ import annotations

import asyncio
import threading

import websockets

from kungfu_chess.client.home_screen import format_welcome_message
from kungfu_chess.client.home_screen import run_shell_login_and_launch
from kungfu_chess.client.loop.network_game_loop_runner import NetworkGameLoopRunner
from kungfu_chess.client.network.network_game_client import NetworkGameClient
from kungfu_chess.model.color import Color
from server.application.game_server import GameServer
from server.persistence.user_repository import DEFAULT_STARTING_RATING

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
        game_server = GameServer(user_repository_db_path=":memory:")
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

    def fake_password_input(prompt: str) -> str:
        return "correct horse battery staple"

    def real_connect(uri: str, username: str, password: str, on_searching_for_opponent) -> NetworkGameLoopRunner:
        # The exact real connection path production code uses (mirrors
        # home_screen.py's own _default_connect) - see module docstring
        # for why headless=True is the correct, established substitute
        # for a real display here. `username`/`password` are threaded
        # through to NetworkGameLoopRunner's own now-required
        # constructor parameters (feature/home-screen-d2-auth-protocol),
        # proving they reach a REAL runner via this real connect path,
        # not just a fake one.
        return NetworkGameLoopRunner(uri, headless=True, username=username, password=password)

    def spy_launch_gui(runner: NetworkGameLoopRunner) -> None:
        launched_runners.append(runner)
        runner.close()

    dummy_opponent = NetworkGameClient()
    dummy_thread = threading.Thread(
        target=dummy_opponent.connect, args=(test_server.uri, "Alice_dummy_opponent", "dummy password"), daemon=True
    )
    dummy_thread.start()
    try:
        run_shell_login_and_launch(
            test_server.uri,
            input_fn=fake_input,
            output_fn=printed.append,
            password_input_fn=fake_password_input,
            connect_fn=real_connect,
            launch_gui_fn=spy_launch_gui,
        )
    finally:
        dummy_thread.join(timeout=_JOIN_TIMEOUT_S)
        dummy_opponent.close()
        test_server.stop()

    assert len(launched_runners) == 1
    real_runner = launched_runners[0]
    # Real matchmaking assigns color by queue arrival order, not
    # connection identity - the dummy opponent connects concurrently, so
    # which of the two gets WHITE is genuinely racy here (see
    # test_network_game_client.py's own `_white_and_black` docstring).
    assert real_runner.assigned_color in (Color.WHITE, Color.BLACK)
    assert real_runner.username == "Alice"
    assert real_runner.rating == DEFAULT_STARTING_RATING

    assert format_welcome_message("Alice", real_runner.assigned_color, DEFAULT_STARTING_RATING) in printed
