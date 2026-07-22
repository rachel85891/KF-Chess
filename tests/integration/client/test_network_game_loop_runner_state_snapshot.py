"""Real, end-to-end integration tests for the feature/network-side-
panel-captured-pieces-timer stage (kungfu_chess/client/loop/
network_game_loop_runner.py's own "SCORE / MOVE-LOG / CAPTURED-PIECES /
TIMER OVER THE NETWORK" docstring section) - a real GameServer-backed
server and a real NetworkGameLoopRunner (headless), mirroring
test_network_game_loop_runner_jump_cooldown.py's own _BackgroundTestServer
pattern exactly (each test file in this project stays self-contained,
per established precedent), extended with an optional injected
GameSession (mirroring test_score_moveslog_timer_broadcast.py's own
session-injection pattern) so a small custom board with an immediate
capture scenario can be used.

NEW, SEPARATE test file (not an edit to any existing
test_network_game_loop_runner*.py file), matching this codebase's own
established "new behavior gets a new test file" convention.
"""

from __future__ import annotations

import asyncio
import threading
import time
from typing import Optional

import websockets

from kungfu_chess.client.events.observers import CaptureLogEntry, MoveLogEntry, MovesLogSnapshot, ScoreSnapshot
from kungfu_chess.client.loop.network_game_loop_runner import NetworkGameLoopRunner
from kungfu_chess.client.ui.captured_pieces_renderer import group_captured_pieces_by_color
from kungfu_chess.client.ui.score_table import PIECE_VALUES
from kungfu_chess.model.board import Board
from kungfu_chess.model.color import Color
from kungfu_chess.model.piece import Piece, PieceKind
from kungfu_chess.model.position import Position
from kungfu_chess.notation.game_state_snapshot_wire_format import format_game_state_snapshot
from kungfu_chess.realtime.real_time_arbiter import MS_PER_SQUARE
from server.application.game_server import GameServer
from server.application.game_session import GameSession

_JOIN_TIMEOUT_S = 5.0
_POLL_INTERVAL_S = 0.05


class _FakeClock:
    """A controllable, injectable time source (Stage B7.5's own
    `clock: Callable[[], float]` constructor parameter) - mirrors
    test_network_game_loop_runner_pixel_sliding.py's own identical
    helper exactly."""

    def __init__(self, start: float = 0.0) -> None:
        self.value = start

    def __call__(self) -> float:
        return self.value


class _BackgroundTestServer:
    """Identical in shape to test_network_game_loop_runner_jump_
    cooldown.py's own _BackgroundTestServer, extended with an optional
    injected GameSession (mirrors test_score_moveslog_timer_broadcast.py's
    own session-injection pattern)."""

    def __init__(self, session: Optional[GameSession] = None) -> None:
        self.uri: str = ""
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._stop_event: Optional[asyncio.Event] = None
        ready = threading.Event()
        self._thread = threading.Thread(target=self._run, args=(ready, session), daemon=True)
        self._thread.start()
        if not ready.wait(timeout=_JOIN_TIMEOUT_S):
            raise RuntimeError("background test server failed to start in time")

    def _run(self, ready: threading.Event, session: Optional[GameSession]) -> None:
        asyncio.run(self._serve(ready, session))

    async def _serve(self, ready: threading.Event, session: Optional[GameSession]) -> None:
        game_server = GameServer(session=session)
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
    deadline = time.perf_counter() + timeout_s
    while time.perf_counter() < deadline:
        runner.poll_and_process()
        if predicate(runner):
            return
        time.sleep(_POLL_INTERVAL_S)


def _empty_grid(rows: int, cols: int) -> list[list[None]]:
    return [[None for _ in range(cols)] for _ in range(rows)]


def _capture_ready_session() -> GameSession:
    """A white rook one square away from a black pawn - the minimum
    setup for a real, immediate, one-square capturing move (mirrors
    test_score_moveslog_timer_broadcast.py's own identical scenario)."""

    grid = _empty_grid(3, 3)
    mover = Piece(color=Color.WHITE, kind=PieceKind.ROOK, cell=Position(row=0, col=0))  # a8
    target = Piece(color=Color.BLACK, kind=PieceKind.PAWN, cell=Position(row=0, col=1))  # b8
    grid[0][0] = mover
    grid[0][1] = target
    return GameSession(board=Board(grid))


# --- Deterministic, fake-clock-driven parsing/holding tests (no real capture needed) ---


def test_apply_state_snapshot_replaces_previously_held_score_log_and_clock():
    test_server = _BackgroundTestServer()
    runner = NetworkGameLoopRunner(test_server.uri, headless=True)
    try:
        assert runner._latest_score.score_by_color == {Color.WHITE: 0, Color.BLACK: 0}
        assert runner._latest_log.entries == ()
        assert runner._latest_clock_ms == 0

        first_score = ScoreSnapshot(score_by_color={Color.WHITE: 3, Color.BLACK: 0})
        first_log = MovesLogSnapshot(
            entries=(
                MoveLogEntry(
                    piece_kind=PieceKind.ROOK, piece_color=Color.WHITE,
                    from_cell=Position(row=0, col=0), to_cell=Position(row=0, col=1),
                    is_jump=False, recorded_at_clock_ms=1000,
                ),
            )
        )
        runner._apply_state_snapshot(format_game_state_snapshot(first_score, first_log, clock_ms=1000))

        assert runner._latest_score == first_score
        assert runner._latest_log == first_log
        assert runner._latest_clock_ms == 1000

        # A SECOND, later snapshot completely REPLACES the first - never
        # merges/accumulates on top of it (every "STATE:" message is
        # already a full, authoritative snapshot).
        second_score = ScoreSnapshot(score_by_color={Color.WHITE: 3, Color.BLACK: 3})
        second_log = MovesLogSnapshot(entries=())
        runner._apply_state_snapshot(format_game_state_snapshot(second_score, second_log, clock_ms=2000))

        assert runner._latest_score == second_score
        assert runner._latest_log == second_log
        assert runner._latest_clock_ms == 2000
    finally:
        runner.close()
        test_server.stop()


def test_apply_state_snapshot_ignores_malformed_text_without_crashing():
    test_server = _BackgroundTestServer()
    runner = NetworkGameLoopRunner(test_server.uri, headless=True)
    try:
        runner._apply_state_snapshot("STATE:not_an_int:0:0:")  # must not raise

        assert runner._latest_score.score_by_color == {Color.WHITE: 0, Color.BLACK: 0}
        assert runner._latest_log.entries == ()
        assert runner._latest_clock_ms == 0
    finally:
        runner.close()
        test_server.stop()


def test_displayed_clock_ms_interpolates_forward_using_the_client_clock_between_broadcasts():
    fake_clock = _FakeClock(start=0.0)
    test_server = _BackgroundTestServer()
    runner = NetworkGameLoopRunner(test_server.uri, headless=True, clock=fake_clock)
    try:
        score = ScoreSnapshot(score_by_color={Color.WHITE: 0, Color.BLACK: 0})
        log = MovesLogSnapshot(entries=())

        fake_clock.value = 5.0
        runner._apply_state_snapshot(format_game_state_snapshot(score, log, clock_ms=10_000))
        assert runner._displayed_clock_ms() == 10_000  # no client time has passed yet

        fake_clock.value = 7.5  # 2.5s of real client time passes
        assert runner._displayed_clock_ms() == 12_500

        # A fresh broadcast re-anchors the interpolation to its own new
        # authoritative value, correcting any accumulated drift.
        fake_clock.value = 8.0
        runner._apply_state_snapshot(format_game_state_snapshot(score, log, clock_ms=20_000))
        assert runner._displayed_clock_ms() == 20_000
    finally:
        runner.close()
        test_server.stop()


# --- Real, end-to-end network test: a real capture updates held state ---


def test_a_real_capture_updates_held_score_log_and_produces_the_correct_captured_pieces_grouping():
    session = _capture_ready_session()
    test_server = _BackgroundTestServer(session=session)
    runner = NetworkGameLoopRunner(test_server.uri, headless=True)
    try:
        assert runner.assigned_color == Color.WHITE
        _poll_until(runner, lambda r: r.board is not None, _JOIN_TIMEOUT_S)

        # a8 -> b8: a real, one-square, capturing rook move.
        runner.network_client.send_move(
            Color.WHITE, PieceKind.ROOK, Position(row=0, col=0), Position(row=0, col=1)
        )

        def capture_reflected(r: NetworkGameLoopRunner) -> bool:
            return r._latest_score.score_by_color.get(Color.WHITE, 0) > 0

        timeout_s = MS_PER_SQUARE / 1000 + 5.0
        _poll_until(runner, capture_reflected, timeout_s)

        assert capture_reflected(runner), "held score never reflected the real capture"
        assert runner._latest_score.score_by_color[Color.WHITE] == PIECE_VALUES[PieceKind.PAWN]
        assert runner._latest_score.score_by_color[Color.BLACK] == 0

        capture_entries = [entry for entry in runner._latest_log.entries if isinstance(entry, CaptureLogEntry)]
        assert len(capture_entries) == 1
        assert capture_entries[0].captured_piece_kind is PieceKind.PAWN
        assert capture_entries[0].captured_piece_color is Color.BLACK

        # Real elapsed game time genuinely advanced too.
        assert runner._latest_clock_ms > 0

        grouped = group_captured_pieces_by_color(runner._latest_log)
        assert grouped[Color.WHITE] == [PieceKind.PAWN]
        assert grouped[Color.BLACK] == []
    finally:
        runner.close()
        test_server.stop()
