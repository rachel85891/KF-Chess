from __future__ import annotations

from kungfu_chess.engine.game_engine import GameEngine
from kungfu_chess.extra.extra_engine import ExtraEngine
from kungfu_chess.extra.jump import JUMP_COOLDOWN_MS, JumpLandingEvent
from kungfu_chess.model.board import Board
from kungfu_chess.model.color import Color
from kungfu_chess.model.piece import Piece, PieceKind, PieceState
from kungfu_chess.model.position import Position
from kungfu_chess.realtime.real_time_arbiter import COOLDOWN_MS
from kungfu_chess.texttests.script_parser import CommandKind, ScriptParser


def _empty_grid(rows: int, cols: int) -> list[list[None]]:
    return [[None for _ in range(cols)] for _ in range(rows)]


def _piece(color: Color, kind: PieceKind, cell: Position) -> Piece:
    return Piece(color=color, kind=kind, cell=cell)


def test_request_jump_marks_piece_airborne_without_moving_it():
    grid = _empty_grid(3, 3)
    rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    grid[0][0] = rook
    engine = GameEngine(Board(grid))
    extra_engine = ExtraEngine(engine)

    accepted = extra_engine.request_jump(Position(row=0, col=0))

    assert accepted is True
    assert extra_engine.jumps.is_airborne(rook.id) is True
    assert rook.cell == Position(row=0, col=0)


def test_enemy_move_targeting_airborne_cell_results_in_attacker_destroyed_defender_untouched():
    grid = _empty_grid(4, 4)
    defender = _piece(Color.WHITE, PieceKind.PAWN, Position(row=0, col=0))
    attacker = _piece(Color.BLACK, PieceKind.ROOK, Position(row=0, col=3))
    grid[0][0] = defender
    grid[0][3] = attacker
    board = Board(grid)
    engine = GameEngine(board)
    extra_engine = ExtraEngine(engine)

    extra_engine.request_jump(Position(row=0, col=0))
    result = engine.request_move(Position(row=0, col=3), Position(row=0, col=0))
    assert result.is_accepted is True

    extra_engine.wait(1000)

    assert board.piece_at(Position(row=0, col=0)) is defender
    assert board.piece_at(Position(row=0, col=3)) is None
    assert attacker.state is PieceState.CAPTURED
    assert engine.arbiter.has_active_motion() is False


def test_attacker_arriving_while_target_airborne_is_destroyed_even_if_move_started_before_jump():
    grid = _empty_grid(1, 2)
    attacker = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    defender = _piece(Color.BLACK, PieceKind.ROOK, Position(row=0, col=1))
    grid[0][0] = attacker
    grid[0][1] = defender
    board = Board(grid)
    engine = GameEngine(board)
    extra_engine = ExtraEngine(engine)

    result = engine.request_move(Position(row=0, col=0), Position(row=0, col=1))
    assert result.is_accepted is True

    extra_engine.wait(100)
    extra_engine.request_jump(Position(row=0, col=1))

    extra_engine.wait(900)

    assert board.piece_at(Position(row=0, col=1)) is defender
    assert board.piece_at(Position(row=0, col=0)) is None
    assert attacker.state is PieceState.CAPTURED


def test_jump_with_no_interception_ends_normally_after_duration():
    grid = _empty_grid(3, 3)
    rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    grid[0][0] = rook
    engine = GameEngine(Board(grid))
    extra_engine = ExtraEngine(engine)

    extra_engine.request_jump(Position(row=0, col=0))
    assert extra_engine.jumps.is_airborne(rook.id) is True

    extra_engine.wait(1000)

    assert extra_engine.jumps.is_airborne(rook.id) is False
    assert rook.cell == Position(row=0, col=0)


def test_core_script_parser_still_recognizes_exactly_three_commands():
    parser = ScriptParser()

    assert parser.parse_line("click 10 20").kind is CommandKind.CLICK
    assert parser.parse_line("wait 500").kind is CommandKind.WAIT
    assert parser.parse_line("print board").kind is CommandKind.PRINT_BOARD
    assert parser.parse_line("jump 10 20") is None
    assert set(CommandKind) == {CommandKind.CLICK, CommandKind.WAIT, CommandKind.PRINT_BOARD}


def test_jump_landing_sets_available_at_ms_to_land_time_plus_jump_cooldown():
    grid = _empty_grid(3, 3)
    rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    grid[0][0] = rook
    engine = GameEngine(Board(grid))
    extra_engine = ExtraEngine(engine)

    extra_engine.request_jump(Position(row=0, col=0))
    extra_engine.wait(1000)

    assert JUMP_COOLDOWN_MS != COOLDOWN_MS
    assert rook.available_at_ms == 1000 + JUMP_COOLDOWN_MS


def test_jump_landing_via_interception_also_sets_available_at_ms_on_defender():
    grid = _empty_grid(4, 4)
    defender = _piece(Color.WHITE, PieceKind.PAWN, Position(row=0, col=0))
    attacker = _piece(Color.BLACK, PieceKind.ROOK, Position(row=0, col=3))
    grid[0][0] = defender
    grid[0][3] = attacker
    board = Board(grid)
    engine = GameEngine(board)
    extra_engine = ExtraEngine(engine)

    extra_engine.request_jump(Position(row=0, col=0))
    engine.request_move(Position(row=0, col=3), Position(row=0, col=0))

    extra_engine.wait(1000)

    assert attacker.state is PieceState.CAPTURED
    assert defender.available_at_ms == 1000 + JUMP_COOLDOWN_MS


def test_request_move_rejected_during_jump_cooldown_and_accepted_after():
    grid = _empty_grid(3, 3)
    rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    grid[0][0] = rook
    board = Board(grid)
    engine = GameEngine(board)
    extra_engine = ExtraEngine(engine)

    extra_engine.request_jump(Position(row=0, col=0))
    extra_engine.wait(1000)

    result = engine.request_move(Position(row=0, col=0), Position(row=0, col=1))
    assert result.is_accepted is False
    assert result.reason == "cooldown_active"

    extra_engine.wait(JUMP_COOLDOWN_MS)
    result = engine.request_move(Position(row=0, col=0), Position(row=0, col=1))

    assert result.is_accepted is True


def test_wait_returns_a_landing_event_when_a_jump_lands_with_no_interception():
    grid = _empty_grid(3, 3)
    rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    grid[0][0] = rook
    engine = GameEngine(Board(grid))
    extra_engine = ExtraEngine(engine)

    extra_engine.request_jump(Position(row=0, col=0))
    _interception_events, landing_events, _arrival_events, _promoted = extra_engine.wait(1000)

    assert landing_events == [JumpLandingEvent(piece=rook, cell=Position(row=0, col=0))]


def test_wait_returns_a_landing_event_for_the_defender_when_a_jump_lands_via_interception():
    grid = _empty_grid(4, 4)
    defender = _piece(Color.WHITE, PieceKind.PAWN, Position(row=0, col=0))
    attacker = _piece(Color.BLACK, PieceKind.ROOK, Position(row=0, col=3))
    grid[0][0] = defender
    grid[0][3] = attacker
    board = Board(grid)
    engine = GameEngine(board)
    extra_engine = ExtraEngine(engine)

    extra_engine.request_jump(Position(row=0, col=0))
    engine.request_move(Position(row=0, col=3), Position(row=0, col=0))

    _interception_events, landing_events, _arrival_events, _promoted = extra_engine.wait(1000)

    assert landing_events == [JumpLandingEvent(piece=defender, cell=Position(row=0, col=0))]


def test_wait_returns_no_landing_events_when_no_jump_is_airborne():
    grid = _empty_grid(3, 3)
    rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    grid[0][0] = rook
    engine = GameEngine(Board(grid))
    extra_engine = ExtraEngine(engine)

    engine.request_move(Position(row=0, col=0), Position(row=0, col=1))
    _interception_events, landing_events, _arrival_events, _promoted = extra_engine.wait(1000)

    assert landing_events == []


def test_request_jump_rejected_during_post_landing_cooldown_and_accepted_after():
    grid = _empty_grid(3, 3)
    rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    grid[0][0] = rook
    engine = GameEngine(Board(grid))
    extra_engine = ExtraEngine(engine)

    extra_engine.request_jump(Position(row=0, col=0))
    extra_engine.wait(1000)
    assert extra_engine.jumps.is_airborne(rook.id) is False

    accepted = extra_engine.request_jump(Position(row=0, col=0))
    assert accepted is False

    extra_engine.wait(JUMP_COOLDOWN_MS)
    accepted = extra_engine.request_jump(Position(row=0, col=0))

    assert accepted is True
