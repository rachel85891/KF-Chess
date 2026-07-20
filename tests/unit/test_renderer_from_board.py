"""Unit tests for build_snapshot_from_board (kungfu_chess/view/
renderer.py) - a NEW, ADDITIVE function alongside the existing
build_snapshot, needed for Stage B6's network client: build_snapshot
itself requires a real GameEngine + Controller (it reads
engine.state.clock_ms and engine.arbiter.active_motions() for
in-flight interpolation), but a network client has neither - it only
ever has a plain Board, parsed from a server broadcast via
BoardParser. This file is a NEW test file (tests/unit/test_renderer.py,
build_snapshot's own existing test file, is left completely untouched)
so build_snapshot/Renderer/GameSnapshot's own existing behavior and
tests remain byte-for-byte unchanged.

SCOPE DECISION (documented here and in build_snapshot_from_board's own
docstring): build_snapshot_from_board never interpolates in-flight
motion (there is no RealTimeArbiter to ask) - every piece renders
statically at its own cell's pixel position. This is Stage B6's
explicit, accepted, temporary scope decision (smooth cross-network
animation is a separate future stage), not an oversight.
"""

from __future__ import annotations

from kungfu_chess.model.board import Board
from kungfu_chess.model.color import Color
from kungfu_chess.model.piece import Piece, PieceKind, PieceState
from kungfu_chess.model.position import Position
from kungfu_chess.realtime.real_time_arbiter import CELL_SIZE
from kungfu_chess.view.renderer import build_snapshot_from_board


def _empty_grid(rows: int, cols: int) -> list[list[None]]:
    return [[None for _ in range(cols)] for _ in range(rows)]


def _piece(color: Color, kind: PieceKind, cell: Position) -> Piece:
    return Piece(color=color, kind=kind, cell=cell)


def test_snapshot_reflects_board_dimensions_and_static_piece_position():
    grid = _empty_grid(2, 3)
    rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=1, col=2))
    grid[1][2] = rook
    board = Board(grid)

    snapshot = build_snapshot_from_board(board)

    assert snapshot.board_width == 3
    assert snapshot.board_height == 2
    assert len(snapshot.pieces) == 1

    piece_snapshot = snapshot.pieces[0]
    assert piece_snapshot.id == rook.id
    assert piece_snapshot.kind is PieceKind.ROOK
    assert piece_snapshot.color is Color.WHITE
    assert piece_snapshot.state is PieceState.IDLE
    # Static position - no in-flight interpolation, no RealTimeArbiter
    # involved at all (see module docstring's SCOPE DECISION).
    assert piece_snapshot.x == 2 * CELL_SIZE
    assert piece_snapshot.y == 1 * CELL_SIZE


def test_empty_board_produces_no_piece_snapshots():
    board = Board(_empty_grid(3, 3))

    snapshot = build_snapshot_from_board(board)

    assert snapshot.pieces == ()


def test_selected_cell_is_passed_through_to_the_snapshot():
    board = Board(_empty_grid(3, 3))

    snapshot = build_snapshot_from_board(board, selected=Position(row=1, col=1))

    assert snapshot.selected == Position(row=1, col=1)


def test_selected_defaults_to_none():
    board = Board(_empty_grid(3, 3))

    snapshot = build_snapshot_from_board(board)

    assert snapshot.selected is None


def test_game_over_defaults_to_false():
    # Documented, accepted gap: raw board-state broadcast text carries
    # no explicit game-over signal (see build_snapshot_from_board's own
    # docstring) - this function can never independently know a game
    # ended, so it always defaults to False unless a caller explicitly
    # overrides it.
    board = Board(_empty_grid(3, 3))

    snapshot = build_snapshot_from_board(board)

    assert snapshot.game_over is False


def test_game_over_can_be_explicitly_overridden():
    board = Board(_empty_grid(3, 3))

    snapshot = build_snapshot_from_board(board, game_over=True)

    assert snapshot.game_over is True
