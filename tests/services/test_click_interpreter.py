from kungfu_chess.config.piece_registry import PieceTypeRegistry
from kungfu_chess.domain.board import Board
from kungfu_chess.domain.color import Color
from kungfu_chess.domain.piece import Piece
from kungfu_chess.services.click_interpreter import ClickIntentKind, interpret_click
from kungfu_chess.services.move_scheduler import MoveScheduler

REGISTRY = PieceTypeRegistry.standard_chess()


def _piece(letter, color):
    return Piece(color=color, piece_type=REGISTRY.get(letter))


def test_clicking_empty_cell_with_nothing_selected_is_ignored():
    board = Board.from_grid([[None]])
    scheduler = MoveScheduler()
    intent = interpret_click(None, (0, 0), board, scheduler)
    assert intent.kind == ClickIntentKind.IGNORE


def test_clicking_idle_piece_with_nothing_selected_selects_it():
    board = Board.from_grid([[_piece("R", Color.WHITE)]])
    scheduler = MoveScheduler()
    intent = interpret_click(None, (0, 0), board, scheduler)
    assert intent.kind == ClickIntentKind.SELECT
    assert intent.cell == (0, 0)


def test_clicking_piece_with_pending_move_is_not_selectable():
    board = Board.from_grid([[_piece("R", Color.WHITE), None]])
    scheduler = MoveScheduler()
    scheduler.schedule_move((0, 0), (0, 1), board.get_piece(0, 0), requested_at=0, arrival=1000)

    intent = interpret_click(None, (0, 0), board, scheduler)
    assert intent.kind == ClickIntentKind.IGNORE


def test_clicking_airborne_piece_is_not_selectable():
    board = Board.from_grid([[_piece("R", Color.WHITE)]])
    scheduler = MoveScheduler()
    scheduler.schedule_landing((0, 0), board.get_piece(0, 0), start_time=0, land_time=1000)

    intent = interpret_click(None, (0, 0), board, scheduler)
    assert intent.kind == ClickIntentKind.IGNORE


def test_clicking_idle_friendly_piece_while_selected_reselects():
    board = Board.from_grid([[_piece("R", Color.WHITE), _piece("N", Color.WHITE)]])
    scheduler = MoveScheduler()
    intent = interpret_click((0, 0), (0, 1), board, scheduler)
    assert intent.kind == ClickIntentKind.SELECT
    assert intent.cell == (0, 1)


def test_clicking_busy_friendly_piece_while_selected_is_ignored_and_keeps_selection():
    board = Board.from_grid([[_piece("R", Color.WHITE), _piece("N", Color.WHITE)]])
    scheduler = MoveScheduler()
    scheduler.schedule_move((0, 1), (1, 1), board.get_piece(0, 1), requested_at=0, arrival=1000)

    intent = interpret_click((0, 0), (0, 1), board, scheduler)
    assert intent.kind == ClickIntentKind.IGNORE


def test_clicking_enemy_piece_while_selected_is_a_move_request():
    board = Board.from_grid([[_piece("R", Color.WHITE), _piece("R", Color.BLACK)]])
    scheduler = MoveScheduler()
    intent = interpret_click((0, 0), (0, 1), board, scheduler)
    assert intent.kind == ClickIntentKind.MOVE_REQUEST
    assert intent.from_cell == (0, 0)
    assert intent.to_cell == (0, 1)


def test_clicking_empty_cell_while_selected_is_a_move_request():
    board = Board.from_grid([[_piece("R", Color.WHITE), None]])
    scheduler = MoveScheduler()
    intent = interpret_click((0, 0), (0, 1), board, scheduler)
    assert intent.kind == ClickIntentKind.MOVE_REQUEST
