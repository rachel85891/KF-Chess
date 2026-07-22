"""Real, end-to-end integration tests for this stage's own Part C
(right-click -> real jump command over the network) and Part D (a real
JumpLanded starting a real cooldown bar in NetworkGameLoopRunner) - a
real GameServer-backed server and a real NetworkGameLoopRunner
(headless), mirroring test_network_game_loop_runner_animation.py's own
_BackgroundTestServer helper exactly (each test file in this project
stays self-contained, per established precedent).

NEW, SEPARATE test file (not an edit to any existing
test_network_game_loop_runner*.py file), matching this codebase's own
established "new behavior gets a new test file" convention.
"""

from __future__ import annotations

import asyncio
import threading
import time

import cv2
import websockets

from kungfu_chess.client.loop.network_game_loop_runner import NetworkGameLoopRunner
from kungfu_chess.extra.jump import JUMP_COOLDOWN_MS
from kungfu_chess.io.board_printer import BoardPrinter
from kungfu_chess.model.color import Color
from kungfu_chess.model.position import Position
from kungfu_chess.realtime.real_time_arbiter import CELL_SIZE, MS_PER_SQUARE
from server.application.game_server import GameServer
from server.application.game_session import GameSession

_JOIN_TIMEOUT_S = 5.0
_POLL_INTERVAL_S = 0.05

_STARTING_BOARD_TEXT = BoardPrinter().print(GameSession().engine.board)


class _BackgroundTestServer:
    """Identical in shape to test_network_game_loop_runner_animation.py's
    own _BackgroundTestServer."""

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


def _window_pixel(runner: NetworkGameLoopRunner, cell: Position) -> tuple[int, int]:
    """Mirrors test_network_game_loop_runner.py's own identically-named
    helper exactly - see that file's own docstring for the full
    click-offset reasoning."""

    window_x = runner._board_origin_x + cell.col * CELL_SIZE + CELL_SIZE // 2
    window_y = runner._board_origin_y + cell.row * CELL_SIZE + CELL_SIZE // 2
    return window_x, window_y


def _poll_until(runner: NetworkGameLoopRunner, predicate, timeout_s: float) -> None:
    deadline = time.perf_counter() + timeout_s
    while time.perf_counter() < deadline:
        runner.poll_and_process()
        if predicate(runner):
            return
        time.sleep(_POLL_INTERVAL_S)


def test_a_right_click_on_the_local_players_own_piece_sends_a_real_jump_and_a_cooldown_bar_appears_after_landing():
    test_server = _BackgroundTestServer()
    runner = NetworkGameLoopRunner(test_server.uri, username="runner", password="runner_pw", headless=True)
    try:
        assert runner.assigned_color == Color.WHITE
        # Seed the known starting position - see
        # test_network_game_loop_runner.py's own module docstring for
        # why this stand-in for the real "no initial broadcast on join"
        # gap is necessary and justified.
        runner._apply_broadcast(_STARTING_BOARD_TEXT)

        a1 = Position(row=7, col=0)  # White's own a-file rook
        rook = runner.board.piece_at(a1)
        assert rook is not None

        window_x, window_y = _window_pixel(runner, a1)
        runner.mouse_adapter.on_mouse_event(cv2.EVENT_RBUTTONDOWN, window_x, window_y, 0, None)

        # No cooldown bar yet - the jump hasn't landed.
        assert runner.cooldown_tracker.remaining_ratio(rook.id, runner._clock_ms()) == 0.0

        def landed(r: NetworkGameLoopRunner) -> bool:
            return r.cooldown_tracker.remaining_ratio(rook.id, r._clock_ms()) > 0.0

        timeout_s = MS_PER_SQUARE / 1000 + 5.0
        _poll_until(runner, landed, timeout_s)

        # A real, freshly-started jump cooldown - full ratio right at
        # landing, using the real JUMP_COOLDOWN_MS this stage's own
        # jump-cooldown-core work established.
        ratio_at_landing = runner.cooldown_tracker.remaining_ratio(rook.id, runner._clock_ms())
        assert 0.0 < ratio_at_landing <= 1.0

        # The piece genuinely never moved - a jump lands at its own
        # cell, unlike an ordinary move.
        assert runner.board.piece_at(a1) is rook
    finally:
        runner.close()
        test_server.stop()


def test_right_click_on_the_opponents_piece_does_not_send_a_jump():
    test_server = _BackgroundTestServer()
    runner = NetworkGameLoopRunner(test_server.uri, username="runner", password="runner_pw", headless=True)
    try:
        assert runner.assigned_color == Color.WHITE
        runner._apply_broadcast(_STARTING_BOARD_TEXT)

        sent: list = []
        runner.network_client.send_jump = lambda *args, **kwargs: sent.append((args, kwargs))

        black_rook = Position(row=0, col=0)
        window_x, window_y = _window_pixel(runner, black_rook)
        runner.mouse_adapter.on_mouse_event(cv2.EVENT_RBUTTONDOWN, window_x, window_y, 0, None)

        assert sent == []
    finally:
        runner.close()
        test_server.stop()


def test_cooldown_ratio_decreases_over_real_time_after_a_real_jump_landing():
    test_server = _BackgroundTestServer()
    runner = NetworkGameLoopRunner(test_server.uri, username="runner", password="runner_pw", headless=True)
    try:
        runner._apply_broadcast(_STARTING_BOARD_TEXT)
        a1 = Position(row=7, col=0)
        rook = runner.board.piece_at(a1)

        window_x, window_y = _window_pixel(runner, a1)
        runner.mouse_adapter.on_mouse_event(cv2.EVENT_RBUTTONDOWN, window_x, window_y, 0, None)

        def landed(r: NetworkGameLoopRunner) -> bool:
            return r.cooldown_tracker.remaining_ratio(rook.id, r._clock_ms()) > 0.0

        timeout_s = MS_PER_SQUARE / 1000 + 5.0
        _poll_until(runner, landed, timeout_s)

        ratio_soon_after_landing = runner.cooldown_tracker.remaining_ratio(rook.id, runner._clock_ms())

        # Real wait for a real fraction of JUMP_COOLDOWN_MS - the ratio
        # must have genuinely decreased, proving this is a real,
        # client-clock-driven depletion, not a value stuck at whatever
        # it started at.
        time.sleep((JUMP_COOLDOWN_MS / 1000) * 0.5)
        runner.poll_and_process()
        ratio_later = runner.cooldown_tracker.remaining_ratio(rook.id, runner._clock_ms())

        assert ratio_later < ratio_soon_after_landing
    finally:
        runner.close()
        test_server.stop()
