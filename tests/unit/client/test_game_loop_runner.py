from __future__ import annotations

import cv2

from kungfu_chess.client.animation.animation_state import AnimationState
from kungfu_chess.client.loop.game_loop import GameLoopRunner
from kungfu_chess.model.board import Board
from kungfu_chess.model.color import Color
from kungfu_chess.model.piece import Piece, PieceKind
from kungfu_chess.model.position import Position
from kungfu_chess.realtime.real_time_arbiter import MS_PER_SQUARE

# A full real-time loop with a live cv2 window (the blocking while-loop
# in run(), real mouse events, real window-close detection) is not
# something this suite attempts to automate - matching the same
# precedent already established for this project's loop/window-heavy
# code (e.g. scripts/demo_stage6_render_board.py is a manual, human-run
# check, not a pytest target). What CAN be verified without a real
# window loop - the wiring, the event-driven game-over flag, and one
# isolated frame of _run_one_frame - is what these tests cover.
#
# GameLoopRunner.__init__ does create a real (small, briefly-visible)
# OpenCV window via cv2.namedWindow/MouseAdapter.attach - this is an
# accepted, necessary side effect of constructing the real thing rather
# than a fake; every test below calls cv2.destroyAllWindows() itself
# afterward so no window is left open once the test finishes.


def _empty_grid(rows: int, cols: int) -> list[list[None]]:
    return [[None for _ in range(cols)] for _ in range(rows)]


def _piece(color: Color, kind: PieceKind, cell: Position) -> Piece:
    return Piece(color=color, kind=kind, cell=cell)


def test_construction_wires_all_three_observers_to_real_published_events():
    grid = _empty_grid(3, 3)
    rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    pawn = _piece(Color.BLACK, PieceKind.PAWN, Position(row=0, col=1))
    grid[0][0] = rook
    grid[0][1] = pawn
    board = Board(grid)

    runner = GameLoopRunner(board, window_name="TestWiring")
    try:
        result = runner.publisher.request_move(Position(row=0, col=0), Position(row=0, col=1))
        assert result.is_accepted is True

        # PieceAnimatorRegistry subscription: the rook's own animator
        # really transitioned to MOVE in reaction to the real event.
        assert runner.piece_animator_registry.animator_for(rook.id).current_state == AnimationState.MOVE

        runner.publisher.wait(MS_PER_SQUARE)

        # ScoreObserver subscription: white really gained the pawn's
        # real PIECE_VALUES score (1), not just "subscribe() was called".
        score = runner.score_observer.snapshot()
        assert score.score_by_color[Color.WHITE] == 1

        # MovesLogObserver subscription: a real move entry and a real
        # capture entry were both actually recorded.
        entries = runner.moves_log_observer.snapshot().entries
        assert len(entries) == 2
    finally:
        cv2.destroyAllWindows()


def test_game_over_listener_sets_the_flag_on_a_real_game_over_event():
    grid = _empty_grid(3, 3)
    rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    king = _piece(Color.BLACK, PieceKind.KING, Position(row=0, col=1))
    grid[0][0] = rook
    grid[0][1] = king
    board = Board(grid)

    runner = GameLoopRunner(board, window_name="TestGameOver")
    try:
        assert runner._game_over is False

        runner.publisher.request_move(Position(row=0, col=0), Position(row=0, col=1))
        runner.publisher.wait(MS_PER_SQUARE)

        assert runner._game_over is True
    finally:
        cv2.destroyAllWindows()


def test_run_one_frame_does_not_raise_and_advances_a_moving_pieces_animation():
    grid = _empty_grid(3, 3)
    rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    grid[0][0] = rook
    board = Board(grid)

    runner = GameLoopRunner(board, window_name="TestOneFrame")
    try:
        runner.publisher.request_move(Position(row=0, col=0), Position(row=0, col=2))
        animator = runner.piece_animator_registry.animator_for(rook.id)
        assert animator.current_state == AnimationState.MOVE
        assert animator.elapsed_ms_in_state == 0

        runner._run_one_frame(50)  # no exception == success

        assert animator.elapsed_ms_in_state > 0
    finally:
        cv2.destroyAllWindows()
