from __future__ import annotations

from kungfu_chess.domain.color import Color
from kungfu_chess.model.board import Board
from kungfu_chess.model.piece import Piece, PieceKind
from kungfu_chess.model.position import Position
from kungfu_chess.rules.piece_rules import (
    BishopRules,
    KingRules,
    KnightRules,
    PawnRules,
    QueenRules,
    RookRules,
)


def _empty_grid(rows: int, cols: int) -> list[list[None]]:
    return [[None for _ in range(cols)] for _ in range(rows)]


def _piece(color: Color, kind: PieceKind, cell: Position) -> Piece:
    return Piece(color=color, kind=kind, cell=cell)


# ---------------------------------------------------------------------
# Rook
# ---------------------------------------------------------------------


def test_rook_moves_across_empty_row_and_col():
    grid = _empty_grid(5, 5)
    rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=2, col=2))
    grid[2][2] = rook
    board = Board(grid)

    destinations = RookRules().legal_destination(board, rook)

    expected = {Position(row=2, col=c) for c in range(5) if c != 2}
    expected |= {Position(row=r, col=2) for r in range(5) if r != 2}
    assert destinations == expected


def test_rook_stops_before_a_friendly_blocker():
    grid = _empty_grid(4, 4)
    rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    friendly = _piece(Color.WHITE, PieceKind.PAWN, Position(row=0, col=2))
    grid[0][0] = rook
    grid[0][2] = friendly
    board = Board(grid)

    destinations = RookRules().legal_destination(board, rook)

    assert Position(row=0, col=1) in destinations
    assert Position(row=0, col=2) not in destinations
    assert Position(row=0, col=3) not in destinations


def test_rook_captures_an_enemy_blocker_but_doesnt_pass_it():
    grid = _empty_grid(4, 4)
    rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    enemy = _piece(Color.BLACK, PieceKind.PAWN, Position(row=0, col=2))
    grid[0][0] = rook
    grid[0][2] = enemy
    board = Board(grid)

    destinations = RookRules().legal_destination(board, rook)

    assert Position(row=0, col=1) in destinations
    assert Position(row=0, col=2) in destinations
    assert Position(row=0, col=3) not in destinations


# ---------------------------------------------------------------------
# Bishop
# ---------------------------------------------------------------------


def test_bishop_moves_diagonally_and_not_straight():
    grid = _empty_grid(5, 5)
    bishop = _piece(Color.WHITE, PieceKind.BISHOP, Position(row=2, col=2))
    grid[2][2] = bishop
    board = Board(grid)

    destinations = BishopRules().legal_destination(board, bishop)

    assert Position(row=0, col=0) in destinations
    assert Position(row=4, col=4) in destinations
    assert Position(row=0, col=4) in destinations
    assert Position(row=4, col=0) in destinations
    assert Position(row=2, col=0) not in destinations
    assert Position(row=0, col=2) not in destinations


# ---------------------------------------------------------------------
# Queen
# ---------------------------------------------------------------------


def test_queen_combines_rook_and_bishop_movement():
    grid = _empty_grid(5, 5)
    queen = _piece(Color.WHITE, PieceKind.QUEEN, Position(row=2, col=2))
    grid[2][2] = queen
    board = Board(grid)

    destinations = QueenRules().legal_destination(board, queen)

    assert Position(row=2, col=0) in destinations
    assert Position(row=0, col=2) in destinations
    assert Position(row=0, col=0) in destinations
    assert Position(row=4, col=4) in destinations
    assert Position(row=0, col=1) not in destinations


# ---------------------------------------------------------------------
# Knight
# ---------------------------------------------------------------------


def test_knight_jumps_over_blockers():
    grid = _empty_grid(5, 5)
    knight = _piece(Color.WHITE, PieceKind.KNIGHT, Position(row=2, col=2))
    grid[2][2] = knight
    for row, col in [(1, 2), (3, 2), (2, 1), (2, 3), (1, 1), (1, 3), (3, 1), (3, 3)]:
        grid[row][col] = _piece(Color.WHITE, PieceKind.PAWN, Position(row=row, col=col))
    board = Board(grid)

    destinations = KnightRules().legal_destination(board, knight)

    expected = {
        Position(row=0, col=1), Position(row=0, col=3),
        Position(row=4, col=1), Position(row=4, col=3),
        Position(row=1, col=0), Position(row=1, col=4),
        Position(row=3, col=0), Position(row=3, col=4),
    }
    assert destinations == expected


# ---------------------------------------------------------------------
# King
# ---------------------------------------------------------------------


def test_king_moves_one_cell_only():
    grid = _empty_grid(5, 5)
    king = _piece(Color.WHITE, PieceKind.KING, Position(row=2, col=2))
    grid[2][2] = king
    board = Board(grid)

    destinations = KingRules().legal_destination(board, king)

    expected = {
        Position(row=1, col=1), Position(row=1, col=2), Position(row=1, col=3),
        Position(row=2, col=1), Position(row=2, col=3),
        Position(row=3, col=1), Position(row=3, col=2), Position(row=3, col=3),
    }
    assert destinations == expected


# ---------------------------------------------------------------------
# Pawn
# ---------------------------------------------------------------------


def test_pawn_moves_one_step_forward():
    grid = _empty_grid(5, 5)
    pawn = _piece(Color.WHITE, PieceKind.PAWN, Position(row=2, col=2))
    grid[2][2] = pawn
    board = Board(grid)

    destinations = PawnRules().legal_destination(board, pawn)

    assert Position(row=1, col=2) in destinations


def test_pawn_cannot_move_two_steps_except_from_start_row():
    grid = _empty_grid(5, 5)
    pawn = _piece(Color.WHITE, PieceKind.PAWN, Position(row=2, col=2))
    grid[2][2] = pawn
    board = Board(grid)
    destinations = PawnRules().legal_destination(board, pawn)
    assert Position(row=0, col=2) not in destinations

    grid_at_start = _empty_grid(5, 5)
    start_pawn = _piece(Color.WHITE, PieceKind.PAWN, Position(row=4, col=2))
    grid_at_start[4][2] = start_pawn
    board_at_start = Board(grid_at_start)
    destinations_at_start = PawnRules().legal_destination(board_at_start, start_pawn)
    assert Position(row=2, col=2) in destinations_at_start


def test_pawn_two_step_opening_blocked_by_intervening_piece():
    grid = _empty_grid(5, 5)
    pawn = _piece(Color.WHITE, PieceKind.PAWN, Position(row=4, col=2))
    blocker = _piece(Color.BLACK, PieceKind.PAWN, Position(row=3, col=2))
    grid[4][2] = pawn
    grid[3][2] = blocker
    board = Board(grid)

    destinations = PawnRules().legal_destination(board, pawn)

    assert Position(row=2, col=2) not in destinations
    assert Position(row=3, col=2) not in destinations


def test_pawn_captures_diagonally_forward_only_when_enemy_present():
    grid = _empty_grid(5, 5)
    pawn = _piece(Color.WHITE, PieceKind.PAWN, Position(row=2, col=2))
    enemy = _piece(Color.BLACK, PieceKind.PAWN, Position(row=1, col=3))
    grid[2][2] = pawn
    grid[1][3] = enemy
    board = Board(grid)

    destinations = PawnRules().legal_destination(board, pawn)

    assert Position(row=1, col=3) in destinations
    assert Position(row=1, col=1) not in destinations


def test_pawn_cannot_capture_straight_ahead():
    grid = _empty_grid(5, 5)
    pawn = _piece(Color.WHITE, PieceKind.PAWN, Position(row=2, col=2))
    enemy = _piece(Color.BLACK, PieceKind.PAWN, Position(row=1, col=2))
    grid[2][2] = pawn
    grid[1][2] = enemy
    board = Board(grid)

    destinations = PawnRules().legal_destination(board, pawn)

    assert Position(row=1, col=2) not in destinations


def test_pawn_black_moves_toward_increasing_row():
    grid = _empty_grid(5, 5)
    pawn = _piece(Color.BLACK, PieceKind.PAWN, Position(row=2, col=2))
    grid[2][2] = pawn
    board = Board(grid)

    destinations = PawnRules().legal_destination(board, pawn)

    assert Position(row=3, col=2) in destinations
    assert Position(row=1, col=2) not in destinations
