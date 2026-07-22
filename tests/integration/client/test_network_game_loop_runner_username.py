"""Real, end-to-end integration tests proving NetworkGameLoopRunner's
own new, optional `username` constructor parameter is threaded through
and stored correctly, and that omitting it entirely (the default,
`None`) does not break construction - full backward compatibility with
every existing headless test construction that never passed one.

Constructing a real NetworkGameLoopRunner inherently requires a real
network connect() (see that class's own __init__) - there is no
mock-network unit-test convention for this class anywhere in this
project (tests/integration/client/test_network_game_loop_runner.py's
own module docstring establishes headless=True + a real background
test server as the established substitute for a real display), so this
lives here, mirroring that file's own _BackgroundTestServer helper
exactly (kept local/self-contained per this project's own established
"each test file stays self-contained" precedent - see e.g.
tests/integration/server/test_initial_board_state_on_join.py's own
docstring for that same precedent).
"""

from __future__ import annotations

import asyncio
import threading

import websockets

from kungfu_chess.client.loop.network_game_loop_runner import NetworkGameLoopRunner
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


def test_a_provided_username_is_stored_on_the_runner():
    test_server = _BackgroundTestServer()
    runner = NetworkGameLoopRunner(test_server.uri, headless=True, username="Alice")
    try:
        assert runner.username == "Alice"
    finally:
        runner.close()
        test_server.stop()


def test_omitting_username_defaults_to_none_and_does_not_break_construction():
    # Backward compatibility - every existing headless test/caller that
    # never passed a username must keep working unchanged.
    test_server = _BackgroundTestServer()
    runner = NetworkGameLoopRunner(test_server.uri, headless=True)
    try:
        assert runner.username is None
    finally:
        runner.close()
        test_server.stop()


def test_a_frame_renders_without_raising_whether_or_not_a_username_was_provided():
    # A real, end-to-end smoke test that the new PlayerLabelRenderer
    # wiring inside _run_one_frame does not crash the per-frame render
    # pipeline in either case.
    test_server = _BackgroundTestServer()
    runner_with_username = NetworkGameLoopRunner(test_server.uri, headless=True, username="Alice")
    try:
        runner_with_username._run_one_frame()

        runner_without_username = NetworkGameLoopRunner(test_server.uri, headless=True)
        try:
            runner_without_username._run_one_frame()
        finally:
            runner_without_username.close()
    finally:
        runner_with_username.close()
        test_server.stop()
