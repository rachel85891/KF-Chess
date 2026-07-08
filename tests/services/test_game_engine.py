"""GameEngine integration tests, mirroring tests/fixtures/*.txt scenarios
but driven directly through the (row, col) Python API instead of the
text/pixel protocol - a belt-and-suspenders check that the composed
engine reproduces the original engine's behavior before it is ever
wired to the CLI."""

from kungfu_chess.config.game_rules import DEFAULT_GAME_RULES
from kungfu_chess.config.piece_registry import PieceTypeRegistry
from kungfu_chess.domain.board import Board
from kungfu_chess.domain.color import Color
from kungfu_chess.domain.piece import Piece
from kungfu_chess.services.game_engine import GameEngine

REGISTRY = PieceTypeRegistry.standard_chess()


def _piece(letter, color):
    return Piece(color=color, piece_type=REGISTRY.get(letter))


def _engine(grid):
    board = Board.from_grid(grid)
    return GameEngine(board, DEFAULT_GAME_RULES)


def _letters(board):
    return [
        [board.get_piece(r, c).letter if board.get_piece(r, c) else "." for c in range(board.num_cols)]
        for r in range(board.num_rows)
    ]


def test_instant_king_capture_ends_game_with_no_transit_delay():
    engine = _engine([
        [_piece("K", Color.BLACK), None, None],
        [None, None, None],
        [_piece("R", Color.WHITE), None, None],
    ])
    engine.handle_click(2, 0)
    engine.handle_click(0, 0)

    assert engine.game_over is True
    assert engine.board.get_piece(0, 0).letter == "R"
    assert engine.board.get_piece(2, 0) is None


def test_scheduled_move_settles_at_exact_arrival_not_before():
    engine = _engine([[None, None], [_piece("P", Color.WHITE), None]])
    engine.handle_click(1, 0)
    engine.handle_click(0, 0)

    engine.handle_wait(999)
    assert engine.board.get_piece(1, 0) is not None  # still mid-flight

    engine.handle_wait(1)
    assert engine.board.get_piece(1, 0) is None
    assert engine.board.get_piece(0, 0) is not None


def test_jump_interception_destroys_attacker_arriving_after_landing():
    engine = _engine([[_piece("R", Color.WHITE), None, None, None, _piece("R", Color.BLACK)]])
    engine.handle_jump(0, 4)
    engine.handle_click(0, 0)
    engine.handle_click(0, 4)

    engine.handle_wait(1000)
    assert engine.board.get_piece(0, 0) is None
    assert engine.board.get_piece(0, 4) is not None


def test_air_capture_when_move_settles_before_landing():
    engine = _engine([[_piece("R", Color.WHITE), _piece("R", Color.BLACK)]])
    engine.handle_click(0, 0)
    engine.handle_click(0, 1)
    engine.handle_wait(100)
    engine.handle_jump(0, 1)

    engine.handle_wait(900)  # clock=1000, move settles, defender not yet landed
    assert engine.board.get_piece(0, 0) is None
    assert engine.board.get_piece(0, 1) is not None


def test_three_way_tie_both_attackers_self_destruct_via_air_capture():
    engine = _engine([
        [None, None, None, _piece("R", Color.WHITE), _piece("R", Color.BLACK)],
        [None, None, None, _piece("B", Color.WHITE), None],
    ])
    engine.handle_jump(0, 4)
    engine.handle_click(0, 3)
    engine.handle_click(0, 4)
    engine.handle_click(1, 3)
    engine.handle_click(0, 4)

    engine.handle_wait(1000)

    assert engine.board.get_piece(0, 3) is None
    assert engine.board.get_piece(1, 3) is None
    assert engine.board.get_piece(0, 4) is not None


def test_promotion_on_double_step_landing_directly_on_promotion_row():
    engine = _engine([
        [_piece("P", Color.BLACK), None],
        [None, None],
        [None, _piece("P", Color.WHITE)],
    ])
    engine.handle_click(2, 1)
    engine.handle_click(0, 1)
    engine.handle_wait(2000)

    assert engine.board.get_piece(0, 1).letter == "Q"

    engine.handle_click(0, 0)
    engine.handle_click(2, 0)
    engine.handle_wait(2000)

    assert engine.board.get_piece(2, 0).letter == "Q"


def test_pawn_double_step_rejected_off_start_row():
    engine = _engine([[None], [None], [_piece("P", Color.WHITE)], [None]])
    engine.handle_click(2, 0)
    engine.handle_click(0, 0)

    assert engine.board.get_piece(2, 0) is not None
    assert engine.board.get_piece(0, 0) is None


def test_opposing_color_move_in_flight_is_rejected_same_color_parallel_allowed():
    engine = _engine([[_piece("R", Color.WHITE), None, _piece("R", Color.BLACK)]])
    engine.handle_click(0, 0)
    engine.handle_click(0, 1)  # white move scheduled
    engine.handle_click(0, 2)
    engine.handle_click(0, 1)  # black move request rejected (opposing in flight)

    engine.handle_wait(1000)

    assert engine.board.get_piece(0, 1).letter == "R"
    assert engine.board.get_piece(0, 1).color == Color.WHITE
    assert engine.board.get_piece(0, 2) is not None  # black rook never moved


def test_out_of_bounds_click_and_jump_are_ignored():
    engine = _engine([[_piece("K", Color.WHITE)]])
    engine.handle_click(50, 50)
    engine.handle_jump(50, 50)

    assert engine.selected is None
    assert engine.board.get_piece(0, 0) is not None


def test_game_over_blocks_further_clicks_and_jumps():
    engine = _engine([
        [_piece("K", Color.BLACK), None],
        [_piece("R", Color.WHITE), None],
    ])
    engine.handle_click(1, 0)
    engine.handle_click(0, 0)
    assert engine.game_over is True

    engine.handle_click(0, 0)  # should be a no-op now
    assert engine.selected is None
