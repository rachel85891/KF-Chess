from __future__ import annotations

from kungfu_chess.engine.game_engine import GameEngine
from kungfu_chess.input.controller import Controller
from kungfu_chess.model.board import Board
from kungfu_chess.model.color import Color
from kungfu_chess.model.piece import Piece, PieceKind
from kungfu_chess.model.position import Position
from kungfu_chess.rules.rule_engine import RuleEngine


def _empty_grid(rows: int, cols: int) -> list[list[None]]:
    return [[None for _ in range(cols)] for _ in range(rows)]


def _piece(color: Color, kind: PieceKind, cell: Position) -> Piece:
    return Piece(color=color, kind=kind, cell=cell)


def test_selecting_a_piece_by_clicking_its_cell():
    grid = _empty_grid(3, 3)
    rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    grid[0][0] = rook
    engine = GameEngine(Board(grid))
    controller = Controller(engine)

    controller.click(0, 0)

    assert controller.selected == Position(row=0, col=0)


def test_clicking_empty_cell_with_nothing_selected_does_nothing():
    engine = GameEngine(Board(_empty_grid(3, 3)))
    controller = Controller(engine)

    controller.click(0, 0)

    assert controller.selected is None


def test_clicking_outside_board_with_nothing_selected_is_ignored():
    engine = GameEngine(Board(_empty_grid(3, 3)))
    controller = Controller(engine)

    controller.click(1000, 1000)

    assert controller.selected is None


def test_clicking_outside_board_while_selected_cancels_selection():
    grid = _empty_grid(3, 3)
    rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    grid[0][0] = rook
    engine = GameEngine(Board(grid))
    controller = Controller(engine)
    controller.click(0, 0)

    controller.click(1000, 1000)

    assert controller.selected is None
    assert engine.arbiter.has_active_motion() is False


def test_clicking_different_friendly_piece_while_selected_replaces_selection():
    grid = _empty_grid(3, 3)
    rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    knight = _piece(Color.WHITE, PieceKind.KNIGHT, Position(row=0, col=1))
    grid[0][0] = rook
    grid[0][1] = knight
    engine = GameEngine(Board(grid))
    controller = Controller(engine)
    controller.click(0, 0)

    controller.click(100, 0)

    assert controller.selected == Position(row=0, col=1)
    assert engine.arbiter.has_active_motion() is False


def test_clicking_same_selected_cell_reselects_as_noop():
    grid = _empty_grid(3, 3)
    rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    grid[0][0] = rook
    engine = GameEngine(Board(grid))
    controller = Controller(engine)
    controller.click(0, 0)

    controller.click(0, 0)

    assert controller.selected == Position(row=0, col=0)
    assert engine.arbiter.has_active_motion() is False


def test_clicking_empty_destination_while_selected_calls_request_move_and_clears_selection():
    grid = _empty_grid(3, 3)
    rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    grid[0][0] = rook
    engine = GameEngine(Board(grid))
    controller = Controller(engine)
    controller.click(0, 0)

    controller.click(200, 0)

    assert controller.selected is None
    assert engine.arbiter.has_active_motion() is True


def test_clicking_enemy_piece_while_selected_calls_request_move_as_capture_attempt_and_clears_selection():
    grid = _empty_grid(3, 3)
    rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    enemy = _piece(Color.BLACK, PieceKind.PAWN, Position(row=0, col=2))
    grid[0][0] = rook
    grid[0][2] = enemy
    engine = GameEngine(Board(grid))
    controller = Controller(engine)
    controller.click(0, 0)

    controller.click(200, 0)

    assert controller.selected is None
    assert engine.arbiter.has_active_motion() is True


def test_clicking_illegal_destination_still_clears_selection():
    grid = _empty_grid(3, 3)
    rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    grid[0][0] = rook
    engine = GameEngine(Board(grid))
    controller = Controller(engine)
    controller.click(0, 0)

    controller.click(100, 100)

    assert controller.selected is None
    assert engine.arbiter.has_active_motion() is False


def test_controller_holds_no_rule_engine_reference():
    engine = GameEngine(Board(_empty_grid(3, 3)))
    controller = Controller(engine)

    assert not any(isinstance(value, RuleEngine) for value in vars(controller).values())


def test_stale_selection_is_cleared_gracefully_if_piece_no_longer_present():
    grid = _empty_grid(3, 3)
    rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    grid[0][0] = rook
    engine = GameEngine(Board(grid))
    controller = Controller(engine)
    controller.click(0, 0)
    assert controller.selected == Position(row=0, col=0)

    engine.board.remove_piece(Position(row=0, col=0))

    controller.click(200, 0)

    assert controller.selected is None
