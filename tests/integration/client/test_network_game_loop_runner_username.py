"""Real, end-to-end integration tests proving NetworkGameLoopRunner's
own `username` constructor parameter is threaded through and stored
correctly, and (as of Stage D2 - feature/home-screen-d2-auth-protocol)
that `username`/`password` are now REQUIRED, real credentials, not the
optional/None-defaulting cosmetic value they were when this file was
first written.

SUPERSEDED BY STAGE D2 - WHY THIS FILE'S OWN ORIGINAL "backward
compatibility with omitting username" TEST WAS REMOVED, NOT JUST
PATCHED: `username` moved from an optional constructor parameter
(defaulting to None) to a REQUIRED one, and a new REQUIRED `password`
parameter was added (kungfu_chess/client/loop/network_game_loop_runner.py's
own "STAGE D2" docstring section - both are now real login/signup
credentials sent to the server, not a cosmetic-only display value).
There is no longer any way to "omit" a required parameter to test the
old backward-compatible default - that scenario is not just changed,
it is no longer EXPRESSIBLE. Replaced below with a test proving the
new, intentional requirement instead (omitting either now raises
TypeError) - real regression coverage for this stage's own breaking
change, not a silently-dropped test.

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

UPDATED for Stage E1's real matchmaking (feature/matchmaking-elo-
queue-e1): see test_network_game_loop_runner.py's own "UPDATED for
Stage E1" docstring section for the full reasoning. Neither test that
constructs a real runner cares about its assigned color, so each gets
a throwaway dummy opponent connected concurrently to unblock its real
matchmaking wait.
"""

from __future__ import annotations

import asyncio
import threading

import pytest
import websockets

from kungfu_chess.client.loop.network_game_loop_runner import NetworkGameLoopRunner
from kungfu_chess.client.network.network_game_client import NetworkGameClient
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


def _start_dummy_opponent(uri: str, username: str) -> tuple[NetworkGameClient, threading.Thread]:
    """Starts (but does not wait for) a throwaway, same-rated dummy
    opponent connecting on a background thread - must be started BEFORE
    constructing the real runner under test - see
    test_network_game_loop_runner.py's own identically-named helper for
    the full reasoning."""

    dummy = NetworkGameClient()
    dummy_thread = threading.Thread(
        target=dummy.connect, args=(uri, f"{username}_dummy_opponent", "dummy password"), daemon=True
    )
    dummy_thread.start()
    return dummy, dummy_thread


def test_a_provided_username_is_stored_on_the_runner():
    test_server = _BackgroundTestServer()
    dummy, dummy_thread = _start_dummy_opponent(test_server.uri, "Alice")
    runner = NetworkGameLoopRunner(test_server.uri, username="Alice", password="correct horse battery staple", headless=True)
    try:
        dummy_thread.join(timeout=_JOIN_TIMEOUT_S)
        assert runner.username == "Alice"
    finally:
        runner.close()
        dummy.close()
        test_server.stop()


def test_omitting_username_or_password_raises_typeerror_since_both_are_now_required():
    # Stage D2's own intentional breaking change - see module
    # docstring's "SUPERSEDED BY STAGE D2" section: there is no longer
    # a legitimate way to connect without real credentials, so a
    # missing default is the correct signal, not an oversight.
    test_server = _BackgroundTestServer()
    try:
        with pytest.raises(TypeError):
            NetworkGameLoopRunner(test_server.uri, headless=True)  # type: ignore[call-arg]
    finally:
        test_server.stop()


def test_a_frame_renders_without_raising_for_a_real_authenticated_runner():
    # A real, end-to-end smoke test that the PlayerLabelRenderer wiring
    # inside _run_one_frame does not crash the per-frame render
    # pipeline for a real, authenticated runner.
    test_server = _BackgroundTestServer()
    dummy, dummy_thread = _start_dummy_opponent(test_server.uri, "Bob")
    runner = NetworkGameLoopRunner(test_server.uri, username="Bob", password="another real password", headless=True)
    try:
        dummy_thread.join(timeout=_JOIN_TIMEOUT_S)
        runner._run_one_frame()
    finally:
        runner.close()
        dummy.close()
        test_server.stop()
