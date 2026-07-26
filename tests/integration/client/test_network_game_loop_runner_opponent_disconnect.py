"""Real, end-to-end integration tests for Stage E2's disconnect-
countdown/auto-resign client-side UX (kungfu_chess/client/loop/
network_game_loop_runner.py's own new "STAGE E2" docstring section) - a
real GameServer-backed server (own background thread + loop, mirroring
test_network_game_loop_runner.py's own _BackgroundTestServer helper) and
a real NetworkGameLoopRunner (headless), matching this project's own
established convention.

WHY THE "OPPONENT" SIDE IS A RAW NetworkGameClient, NOT A SECOND
NetworkGameLoopRunner: these tests only need to prove what THIS
client's own countdown-display/reconnect-clearing STATE does in
response to real wire messages - a full second GUI-capable runner on
the opponent's side would add nothing (its own rendering is not under
test here) while making disconnect/reconnect control (close(), then a
fresh connect() under the SAME username) more awkward than
NetworkGameClient's own already-synchronous, already-reusable
connect()/close() contract provides directly. Mirrors
tests/integration/client/test_home_screen_login.py's own
"_connect_with_dummy_opponent"-style precedent of using a raw
NetworkGameClient as the concurrently-connecting OTHER party while the
real class under test is a full NetworkGameLoopRunner.

WHY disconnect_countdown_s IS OVERRIDDEN TO A SHORT VALUE: mirrors
Stage E1's own established `matchmaking_timeout_s` override precedent -
no test here ever waits out a real 20-second countdown.
"""

from __future__ import annotations

import asyncio
import threading
import time

import pytest
import websockets

from kungfu_chess.client.loop.network_game_loop_runner import NetworkGameLoopRunner
from kungfu_chess.client.network.network_game_client import NetworkGameClient
from server.application.game_server import GameServer

# Marked slow: this file constructs a real, background-threaded/tasked
# server and relies on real wall-clock waiting (asyncio.sleep/time.sleep,
# real tick-loop cadence, or real network round trips) - excluded from
# `pytest -m "not slow"` for fast, deterministic day-to-day runs; still
# run in full via the dedicated slow/real-time pass.
pytestmark = pytest.mark.slow


_JOIN_TIMEOUT_S = 5.0
_POLL_INTERVAL_S = 0.05
_SHORT_COUNTDOWN_S = 1.0
_REACTION_DELAY_S = 0.3
# The reconnect scenario needs real headroom beyond the bare countdown
# window: reconnecting goes through NetworkGameClient's own real
# background-thread startup and a genuine PBKDF2-hashed AUTH round
# trip (server/persistence/user_repository.py's own deliberately-slow-
# by-design cost, re-verified elsewhere in this project's own tests at
# ~0.3s/call) - a bare 1-second window (fine for the raw-websocket
# server-side equivalent test, test_disconnect_countdown_autoresign.py,
# which has none of that extra client-side overhead) is too tight here
# and would race the real auto-resign before the reconnect can land.
_RECONNECT_COUNTDOWN_S = 6.0


class _BackgroundTestServer:
    """Identical in shape to test_network_game_loop_runner.py's own
    _BackgroundTestServer, extended with an overridable
    disconnect_countdown_s (mirrors test_matchmaking_protocol.py's own
    overridable matchmaking_timeout_s precedent)."""

    def __init__(self, disconnect_countdown_s: float = 20.0) -> None:
        self.uri: str = ""
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop_event: asyncio.Event | None = None
        ready = threading.Event()
        self._thread = threading.Thread(target=self._run, args=(ready, disconnect_countdown_s), daemon=True)
        self._thread.start()
        if not ready.wait(timeout=_JOIN_TIMEOUT_S):
            raise RuntimeError("background test server failed to start in time")

    def _run(self, ready: threading.Event, disconnect_countdown_s: float) -> None:
        asyncio.run(self._serve(ready, disconnect_countdown_s))

    async def _serve(self, ready: threading.Event, disconnect_countdown_s: float) -> None:
        game_server = GameServer(user_repository_db_path=":memory:", disconnect_countdown_s=disconnect_countdown_s)
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


def _start_opponent(uri: str) -> tuple[NetworkGameClient, threading.Thread]:
    """Starts (but does not wait for) a raw NetworkGameClient
    "opponent" connecting on a background thread - must be started
    BEFORE constructing the real NetworkGameLoopRunner under test, since
    that class's own constructor blocks the calling thread until
    matched (see test_network_game_loop_runner.py's own identically-
    shaped helper for the full reasoning)."""

    opponent = NetworkGameClient()
    thread = threading.Thread(target=opponent.connect, args=(uri, "bob", "a real password"), daemon=True)
    thread.start()
    return opponent, thread


def _poll_until(runner: NetworkGameLoopRunner, predicate, timeout_s: float) -> None:
    deadline = time.perf_counter() + timeout_s
    while time.perf_counter() < deadline:
        runner.poll_and_process()
        if predicate(runner):
            return
        time.sleep(_POLL_INTERVAL_S)


def test_a_real_opponent_disconnect_starts_a_client_local_countdown_that_clears_on_reconnect_and_the_match_continues():
    test_server = _BackgroundTestServer(disconnect_countdown_s=_RECONNECT_COUNTDOWN_S)
    opponent, opponent_thread = _start_opponent(test_server.uri)
    runner = NetworkGameLoopRunner(test_server.uri, username="alice", password="correct horse battery staple", headless=True)
    try:
        opponent_thread.join(timeout=_JOIN_TIMEOUT_S)
        _poll_until(runner, lambda r: r.board is not None, _JOIN_TIMEOUT_S)
        assert runner._opponent_disconnected_remaining_seconds() is None

        opponent.close()

        _poll_until(runner, lambda r: r._opponent_disconnected_remaining_seconds() is not None, timeout_s=5.0)
        assert runner._opponent_disconnected_countdown_seconds == _RECONNECT_COUNTDOWN_S
        remaining = runner._opponent_disconnected_remaining_seconds()
        assert remaining is not None and remaining <= _RECONNECT_COUNTDOWN_S

        # The match is NOT over yet - this client can still see its own
        # opponent-disconnected state, but no GameOver has arrived.
        assert runner._game_over is False

        # Reconnect with the SAME username, well before the countdown
        # expires - a brand new NetworkGameClient, mirroring a real
        # human relaunching their own client and logging back in.
        reconnected_opponent = NetworkGameClient()
        reconnected_opponent.connect(test_server.uri, "bob", "a real password")
        try:
            _poll_until(runner, lambda r: r._opponent_disconnected_remaining_seconds() is None, timeout_s=5.0)
            assert runner._opponent_disconnected_remaining_seconds() is None
            assert runner._game_over is False

            # Real wait past what would have been the original
            # countdown's own expiry - proving it was genuinely
            # cancelled, not just temporarily cleared.
            time.sleep(_RECONNECT_COUNTDOWN_S + _REACTION_DELAY_S)
            runner.poll_and_process()
            assert runner._game_over is False
            assert runner._opponent_disconnected_remaining_seconds() is None
        finally:
            reconnected_opponent.close()
    finally:
        runner.close()
        test_server.stop()


def test_a_real_opponent_disconnect_countdown_expiring_with_no_reconnect_produces_a_real_game_over_won_by_this_client():
    test_server = _BackgroundTestServer(disconnect_countdown_s=_SHORT_COUNTDOWN_S)
    opponent, opponent_thread = _start_opponent(test_server.uri)
    runner = NetworkGameLoopRunner(test_server.uri, username="alice", password="correct horse battery staple", headless=True)
    try:
        opponent_thread.join(timeout=_JOIN_TIMEOUT_S)
        _poll_until(runner, lambda r: r.board is not None, _JOIN_TIMEOUT_S)

        opponent.close()

        _poll_until(runner, lambda r: r._opponent_disconnected_remaining_seconds() is not None, timeout_s=5.0)

        # Real wait past the short countdown - no reconnect ever happens.
        _poll_until(runner, lambda r: r._game_over, timeout_s=_SHORT_COUNTDOWN_S + 5.0)

        assert runner._game_over is True
        assert runner._game_over_winner_color is runner.assigned_color
        assert runner.click_controller.game_over is True
    finally:
        runner.close()
        test_server.stop()
