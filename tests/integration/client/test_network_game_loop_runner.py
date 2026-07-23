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

UPDATED for Stage E1's real matchmaking (feature/matchmaking-elo-
queue-e1): NetworkGameLoopRunner's own constructor now blocks until a
rating-compatible opponent has ALSO joined the matchmaking queue (see
server/application/game_server.py's own "STAGE E1" docstring section).
Two runners that need to match each other can therefore no longer be
constructed sequentially on the same test thread (the first
constructor call would block forever waiting for a compatible second
party whose own constructor call hasn't even started yet) -
`_construct_concurrently`, below, constructs each one on its OWN
background thread instead. A test that only needs ONE real runner
still needs a real, compatible second party concurrently connected to
unblock it - `_connect_dummy_opponent` connects a throwaway, same-
rated (fresh accounts, always rating-compatible) raw NetworkGameClient
on a background thread purely for this purpose, mirroring
tests/integration/client/test_network_game_client.py's own
`_connect_with_dummy_opponent` helper (a raw NetworkGameClient is used
here rather than a second full NetworkGameLoopRunner since the dummy
never needs any of the runner's own rendering/click machinery). Color
assignment is now driven by matchmaking queue order, not connection
order, so which of two concurrently-connecting runners ends up WHITE
vs BLACK is genuinely racy from a test's point of view - see
`_white_and_black`, below, mirroring test_network_game_client.py's own
helper of the same name.
"""

from __future__ import annotations

import asyncio
import threading
import time

import cv2
import websockets

from kungfu_chess.client.loop.network_game_loop_runner import NetworkGameLoopRunner
from kungfu_chess.client.network.network_game_client import NetworkGameClient
from kungfu_chess.io.board_printer import BoardPrinter
from kungfu_chess.model.color import Color
from kungfu_chess.model.piece import PieceKind
from kungfu_chess.model.position import Position
from kungfu_chess.realtime.real_time_arbiter import CELL_SIZE, MS_PER_SQUARE
from server.application.game_server import GameServer
from server.application.game_session import GameSession

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
    """Convert a logical cell to a WINDOW pixel coordinate a real mouse
    click at that cell would produce - i.e. the board's own offset
    within the window (runner._board_origin_x/_y) plus the cell's own
    pixel position within the board, mirroring
    tests/unit/client/test_game_loop_runner.py's own established click-
    offset-aware test pattern exactly (see that file's own
    test_left_click_correctly_selects_the_piece_under_the_cursor_
    despite_the_panel_offset). Passing raw board-relative pixels
    directly (without this offset) would click the wrong cell, since
    ScreenToImageMapper.to_image subtracts window_origin before
    resolving a cell - the same real bug class that test file's own
    click-offset regression tests exist to catch."""

    window_x = runner._board_origin_x + cell.col * CELL_SIZE + CELL_SIZE // 2
    window_y = runner._board_origin_y + cell.row * CELL_SIZE + CELL_SIZE // 2
    return window_x, window_y


def _construct_concurrently(uri: str, username: str, password: str) -> tuple[threading.Thread, list]:
    """Constructs a NetworkGameLoopRunner on its own background thread
    - see module docstring for why two runners that need to match each
    other can no longer be constructed sequentially. Returns the thread
    (caller must .join() it) and a one-element list the constructed
    runner is appended to once ready (a list rather than a plain return
    value since a thread target has no return channel of its own)."""

    result: list[NetworkGameLoopRunner] = []

    def _construct() -> None:
        result.append(NetworkGameLoopRunner(uri, username=username, password=password, headless=True))

    thread = threading.Thread(target=_construct, daemon=True)
    thread.start()
    return thread, result


def _start_dummy_opponent(uri: str, username: str) -> tuple[NetworkGameClient, threading.Thread]:
    """Starts (but does not wait for) a throwaway, same-rated dummy
    opponent connecting on a background thread - purely to unblock a
    single real runner's own real matchmaking wait. MUST be started
    BEFORE constructing the real runner under test (NetworkGameLoop
    Runner's own constructor blocks synchronously on the calling
    thread until matched), not after - see module docstring for the
    full reasoning. Caller is responsible for joining the returned
    thread once the real runner's own construction has returned."""

    dummy = NetworkGameClient()
    dummy_thread = threading.Thread(
        target=dummy.connect, args=(uri, f"{username}_dummy_opponent", "dummy password"), daemon=True
    )
    dummy_thread.start()
    return dummy, dummy_thread


def _white_and_black(
    runner1: NetworkGameLoopRunner, runner2: NetworkGameLoopRunner
) -> tuple[NetworkGameLoopRunner, NetworkGameLoopRunner]:
    """Returns (white_runner, black_runner) - see module docstring for
    why color assignment can no longer be assumed from construction
    order."""

    assert {runner1.assigned_color, runner2.assigned_color} == {Color.WHITE, Color.BLACK}
    if runner1.assigned_color == Color.WHITE:
        return runner1, runner2
    return runner2, runner1


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
    thread1, result1 = _construct_concurrently(test_server.uri, "runner1", "runner1_pw")
    thread2, result2 = _construct_concurrently(test_server.uri, "runner2", "runner2_pw")
    thread1.join(timeout=_JOIN_TIMEOUT_S)
    thread2.join(timeout=_JOIN_TIMEOUT_S)
    runner1, runner2 = result1[0], result2[0]
    try:
        _white_and_black(runner1, runner2)
    finally:
        runner2.close()
        runner1.close()
        test_server.stop()


def test_a_click_sequence_on_the_local_players_own_piece_sends_a_real_move_and_is_reflected_after_broadcast():
    test_server = _BackgroundTestServer()
    thread1, result1 = _construct_concurrently(test_server.uri, "runner1", "runner1_pw")
    thread2, result2 = _construct_concurrently(test_server.uri, "runner2", "runner2_pw")
    thread1.join(timeout=_JOIN_TIMEOUT_S)
    thread2.join(timeout=_JOIN_TIMEOUT_S)
    other_runner = None
    try:
        # e2->e4 is a WHITE pawn move - run the click sequence against
        # whichever of the two concurrently-connected runners actually
        # ended up WHITE (see module docstring for why that can't be
        # assumed from construction order), and close the other one as
        # a bystander that plays no further part.
        runner, other_runner = _white_and_black(result1[0], result2[0])
        # Seed the known starting position - see module docstring's
        # "DOCUMENTED, ACCEPTED GAP" section for why this is necessary
        # and how it's justified.
        runner._apply_broadcast(_STARTING_BOARD_TEXT)

        e2 = Position(row=6, col=4)
        e4 = Position(row=4, col=4)
        window_x, window_y = _window_pixel(runner, e2)
        runner.mouse_adapter.on_mouse_event(cv2.EVENT_LBUTTONDOWN, window_x, window_y, 0, None)
        window_x, window_y = _window_pixel(runner, e4)
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
        if other_runner is not None:
            other_runner.close()
        runner.close()
        test_server.stop()


def test_click_on_a_cell_with_no_piece_selected_and_no_board_yet_does_not_crash():
    test_server = _BackgroundTestServer()
    dummy, dummy_thread = _start_dummy_opponent(test_server.uri, "runner")
    runner = NetworkGameLoopRunner(test_server.uri, username="runner", password="runner_pw", headless=True)
    try:
        dummy_thread.join(timeout=_JOIN_TIMEOUT_S)
        # No _apply_broadcast call at all - runner.board is still None.
        runner.mouse_adapter.on_mouse_event(cv2.EVENT_LBUTTONDOWN, 0, 0, 0, None)  # must not raise

        assert runner.click_controller.selected is None
    finally:
        runner.close()
        dummy.close()
        test_server.stop()


def test_click_on_the_opponents_piece_does_not_send_a_move():
    test_server = _BackgroundTestServer()
    thread1, result1 = _construct_concurrently(test_server.uri, "runner1", "runner1_pw")
    thread2, result2 = _construct_concurrently(test_server.uri, "runner2", "runner2_pw")
    thread1.join(timeout=_JOIN_TIMEOUT_S)
    thread2.join(timeout=_JOIN_TIMEOUT_S)
    other_runner = None
    try:
        # Need "runner" to be WHITE specifically, so the black pawn at
        # row 1 genuinely belongs to the OTHER side - see module
        # docstring for why this can't be assumed from construction
        # order.
        runner, other_runner = _white_and_black(result1[0], result2[0])
        runner._apply_broadcast(_STARTING_BOARD_TEXT)

        sent: list = []
        runner.network_client.send_move = lambda *args, **kwargs: sent.append((args, kwargs))

        black_pawn = Position(row=1, col=4)
        window_x, window_y = _window_pixel(runner, black_pawn)
        runner.mouse_adapter.on_mouse_event(cv2.EVENT_LBUTTONDOWN, window_x, window_y, 0, None)

        assert sent == []
        assert runner.click_controller.selected is None
    finally:
        if other_runner is not None:
            other_runner.close()
        runner.close()
        test_server.stop()


def test_two_independent_runners_get_opposite_colors_and_each_see_the_others_move():
    test_server = _BackgroundTestServer()
    thread1, result1 = _construct_concurrently(test_server.uri, "runner1", "runner1_pw")
    thread2, result2 = _construct_concurrently(test_server.uri, "runner2", "runner2_pw")
    thread1.join(timeout=_JOIN_TIMEOUT_S)
    thread2.join(timeout=_JOIN_TIMEOUT_S)
    try:
        runner_white, runner_black = _white_and_black(result1[0], result2[0])
        try:
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
