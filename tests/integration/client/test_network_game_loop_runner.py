"""Real, end-to-end integration tests for Stage B6's
NetworkGameLoopRunner (kungfu_chess/client/loop/
network_game_loop_runner.py) - a real GameServer-backed server (own
background thread + loop, mirroring
tests/integration/client/test_network_game_client.py's own
_BackgroundTestServer helper exactly) and one or two real
NetworkGameLoopRunner instances, always constructed with headless=True
(this project's own established GameLoopRunner convention - see
tests/unit/client/test_game_loop_runner.py's own module-level comment
for why: cv2 GUI calls abort the whole process on a display-less
machine). Headless mode here still exercises every real step -
poll_incoming, BoardParser, build_snapshot_from_board, real Renderer/
ImgSurface/CoordinateLabelRenderer/SidePanelRenderer drawing onto a
real in-memory canvas - only the final on-screen display/key-poll are
skipped, exactly mirroring GameLoopRunner's own headless contract.

DOCUMENTED, ACCEPTED GAP THESE TESTS WORK AROUND (see
network_game_loop_runner.py's own module docstring for the full
reasoning): the existing server protocol (Stage B3) never sends an
initial board-state broadcast on join - a client only ever learns the
board from a MoveAccepted/PieceArrived/MoveRejected/GameOver broadcast,
which only exist once somebody has made at least one move. Tests below
that need a KNOWN starting board to click against therefore seed it by
calling the runner's own real `_apply_broadcast` with the real
server's own actual starting-position text (built via the real
BoardPrinter against a real GameSession's own board - not an invented
fixture) - simulating "as if the very first broadcast had already
delivered the true starting position," which is a reasonable stand-in
for the real gap, not a mock of anything this class itself does.
"""

from __future__ import annotations

import asyncio
import threading
import time

import cv2
import websockets

from kungfu_chess.client.loop.network_game_loop_runner import NetworkGameLoopRunner
from kungfu_chess.io.board_printer import BoardPrinter
from kungfu_chess.model.color import Color
from kungfu_chess.model.piece import PieceKind
from kungfu_chess.model.position import Position
from kungfu_chess.realtime.real_time_arbiter import CELL_SIZE, MS_PER_SQUARE
from server.game_server import GameServer
from server.game_session import GameSession

_JOIN_TIMEOUT_S = 5.0
_POLL_TIMEOUT_S = 5.0
_POLL_INTERVAL_S = 0.05

_STARTING_BOARD_TEXT = BoardPrinter().print(GameSession().engine.board)


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


def _poll_until(runner: NetworkGameLoopRunner, predicate, timeout_s: float) -> None:
    """Repeatedly call runner.poll_and_process() (real sleeps, real
    time) until predicate(runner) is True or timeout_s elapses -
    NetworkGameLoopRunner's own synchronous equivalent of
    test_network_game_client.py's own _poll_until."""

    deadline = time.perf_counter() + timeout_s
    while time.perf_counter() < deadline:
        runner.poll_and_process()
        if predicate(runner):
            return
        time.sleep(_POLL_INTERVAL_S)


def test_constructing_in_headless_mode_reads_the_correct_assigned_color():
    test_server = _BackgroundTestServer()
    runner1 = NetworkGameLoopRunner(test_server.uri, headless=True)
    try:
        runner2 = NetworkGameLoopRunner(test_server.uri, headless=True)
        try:
            assert runner1.assigned_color == Color.WHITE
            assert runner2.assigned_color == Color.BLACK
        finally:
            runner2.close()
    finally:
        runner1.close()
        test_server.stop()


def test_a_click_sequence_on_the_local_players_own_piece_sends_a_real_move_and_is_reflected_after_broadcast():
    test_server = _BackgroundTestServer()
    runner = NetworkGameLoopRunner(test_server.uri, headless=True)
    try:
        assert runner.assigned_color == Color.WHITE
        # Seed the known starting position - see module docstring's
        # "DOCUMENTED, ACCEPTED GAP" section for why this is necessary
        # and how it's justified.
        runner._apply_broadcast(_STARTING_BOARD_TEXT)

        e2 = Position(row=6, col=4)
        e4 = Position(row=4, col=4)
        window_x, window_y = e2.col * CELL_SIZE + CELL_SIZE // 2, e2.row * CELL_SIZE + CELL_SIZE // 2
        runner.mouse_adapter.on_mouse_event(cv2.EVENT_LBUTTONDOWN, window_x, window_y, 0, None)
        window_x, window_y = e4.col * CELL_SIZE + CELL_SIZE // 2, e4.row * CELL_SIZE + CELL_SIZE // 2
        runner.mouse_adapter.on_mouse_event(cv2.EVENT_LBUTTONDOWN, window_x, window_y, 0, None)

        def arrived(r: NetworkGameLoopRunner) -> bool:
            piece = r.board.piece_at(e4) if r.board is not None else None
            return piece is not None and piece.kind is PieceKind.PAWN

        timeout_s = (2 * MS_PER_SQUARE) / 1000 + 3.0
        _poll_until(runner, arrived, timeout_s)

        assert runner.board.piece_at(e2) is None
        moved = runner.board.piece_at(e4)
        assert moved is not None and moved.kind is PieceKind.PAWN and moved.color is Color.WHITE
    finally:
        runner.close()
        test_server.stop()


def test_click_on_a_cell_with_no_piece_selected_and_no_board_yet_does_not_crash():
    test_server = _BackgroundTestServer()
    runner = NetworkGameLoopRunner(test_server.uri, headless=True)
    try:
        # No _apply_broadcast call at all - runner.board is still None.
        runner.mouse_adapter.on_mouse_event(cv2.EVENT_LBUTTONDOWN, 0, 0, 0, None)  # must not raise

        assert runner.click_controller.selected is None
    finally:
        runner.close()
        test_server.stop()


def test_click_on_the_opponents_piece_does_not_send_a_move():
    test_server = _BackgroundTestServer()
    runner = NetworkGameLoopRunner(test_server.uri, headless=True)
    try:
        assert runner.assigned_color == Color.WHITE
        runner._apply_broadcast(_STARTING_BOARD_TEXT)

        sent: list = []
        runner.network_client.send_move = lambda *args, **kwargs: sent.append((args, kwargs))

        black_pawn = Position(row=1, col=4)
        window_x, window_y = black_pawn.col * CELL_SIZE + CELL_SIZE // 2, black_pawn.row * CELL_SIZE + CELL_SIZE // 2
        runner.mouse_adapter.on_mouse_event(cv2.EVENT_LBUTTONDOWN, window_x, window_y, 0, None)

        assert sent == []
        assert runner.click_controller.selected is None
    finally:
        runner.close()
        test_server.stop()


def test_two_independent_runners_get_opposite_colors_and_each_see_the_others_move():
    test_server = _BackgroundTestServer()
    runner_white = NetworkGameLoopRunner(test_server.uri, headless=True)
    try:
        runner_black = NetworkGameLoopRunner(test_server.uri, headless=True)
        try:
            assert runner_white.assigned_color == Color.WHITE
            assert runner_black.assigned_color == Color.BLACK

            e2 = Position(row=6, col=4)
            e4 = Position(row=4, col=4)
            runner_white.network_client.send_move(Color.WHITE, PieceKind.PAWN, e2, e4)

            def arrived(r: NetworkGameLoopRunner) -> bool:
                piece = r.board.piece_at(e4) if r.board is not None else None
                return piece is not None and piece.kind is PieceKind.PAWN

            timeout_s = (2 * MS_PER_SQUARE) / 1000 + 3.0
            _poll_until(runner_white, arrived, timeout_s)
            _poll_until(runner_black, arrived, timeout_s)

            assert runner_white.board.piece_at(e2) is None
            assert runner_black.board.piece_at(e2) is None
            assert runner_white.board.piece_at(e4).color is Color.WHITE
            assert runner_black.board.piece_at(e4).color is Color.WHITE
        finally:
            runner_black.close()
    finally:
        runner_white.close()
        test_server.stop()
