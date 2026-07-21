"""Unit tests for build_snapshot_from_board's new, OPTIONAL
`active_motions` parameter (Stage B7.5 - see kungfu_chess/view/
renderer.py's own "EXTRACTED, Stage B7.5" docstring section for the
full reasoning).

NEW, SEPARATE test file (not an edit to the existing
tests/unit/test_renderer_from_board.py), matching this codebase's own
established "new behavior gets a new test file" convention (see
tests/unit/client/test_piece_animator_arrival_transition.py's own
docstring for the identical precedent) - that file's own existing
tests already prove the `active_motions=None` (default) behavior is
completely unaffected; not re-duplicated here.

build_snapshot_from_board itself has no engine/arbiter/clock of its
own (see that function's own docstring) - it never computes progress
itself, only interpolates a position from an ALREADY-clamped progress
value a caller supplies via InFlightMotion. This keeps it fully
agnostic of WHICH clock produced that fraction (a local engine's
clock_ms, as build_snapshot itself uses; a client's own wall-clock
elapsed time, as NetworkGameLoopRunner uses; or any future source).
"""

from __future__ import annotations

from kungfu_chess.model.board import Board
from kungfu_chess.model.color import Color
from kungfu_chess.model.piece import Piece, PieceKind
from kungfu_chess.model.position import Position
from kungfu_chess.realtime.real_time_arbiter import CELL_SIZE
from kungfu_chess.view.renderer import InFlightMotion, build_snapshot_from_board


def _empty_grid(rows: int, cols: int) -> list[list[None]]:
    return [[None for _ in range(cols)] for _ in range(rows)]


def _piece(color: Color, kind: PieceKind, cell: Position) -> Piece:
    return Piece(color=color, kind=kind, cell=cell)


def test_a_piece_with_no_active_motion_entry_still_renders_at_its_own_cell():
    grid = _empty_grid(3, 3)
    rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=1, col=2))
    grid[1][2] = rook
    board = Board(grid)

    snapshot = build_snapshot_from_board(board, active_motions={})

    piece_snapshot = snapshot.pieces[0]
    assert (piece_snapshot.x, piece_snapshot.y) == (2 * CELL_SIZE, 1 * CELL_SIZE)


def test_a_piece_with_an_active_motion_renders_at_the_interpolated_position_not_its_own_cell():
    grid = _empty_grid(3, 3)
    # The piece's OWN cell (row=0, col=0) deliberately differs from the
    # motion's from_cell/to_cell below - proving rendering position
    # comes entirely from InFlightMotion when present, not from
    # piece.cell at all (matching build_snapshot's own local-play
    # in-flight behavior, where the board itself hasn't moved the
    # piece yet either, per docs/spec.md's "board changes only after
    # arrival" rule).
    rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    grid[0][0] = rook
    board = Board(grid)

    active_motions = {
        rook.id: InFlightMotion(from_cell=Position(row=0, col=0), to_cell=Position(row=0, col=2), progress=0.5)
    }

    snapshot = build_snapshot_from_board(board, active_motions=active_motions)

    piece_snapshot = snapshot.pieces[0]
    assert (piece_snapshot.x, piece_snapshot.y) == (1 * CELL_SIZE, 0)


def test_active_motions_defaults_to_none_and_behaves_exactly_like_before_this_stage():
    grid = _empty_grid(2, 2)
    rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=1, col=1))
    grid[1][1] = rook
    board = Board(grid)

    snapshot = build_snapshot_from_board(board)  # no active_motions argument at all

    piece_snapshot = snapshot.pieces[0]
    assert (piece_snapshot.x, piece_snapshot.y) == (1 * CELL_SIZE, 1 * CELL_SIZE)


def test_only_the_piece_with_a_matching_id_uses_its_active_motion_others_stay_static():
    grid = _empty_grid(3, 3)
    moving_rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    static_bishop = _piece(Color.BLACK, PieceKind.BISHOP, Position(row=2, col=2))
    grid[0][0] = moving_rook
    grid[2][2] = static_bishop
    board = Board(grid)

    active_motions = {
        moving_rook.id: InFlightMotion(from_cell=Position(row=0, col=0), to_cell=Position(row=2, col=0), progress=1.0)
    }

    snapshot = build_snapshot_from_board(board, active_motions=active_motions)

    moving_snapshot = next(p for p in snapshot.pieces if p.id == moving_rook.id)
    static_snapshot = next(p for p in snapshot.pieces if p.id == static_bishop.id)

    assert (moving_snapshot.x, moving_snapshot.y) == (0, 2 * CELL_SIZE)
    assert (static_snapshot.x, static_snapshot.y) == (2 * CELL_SIZE, 2 * CELL_SIZE)
