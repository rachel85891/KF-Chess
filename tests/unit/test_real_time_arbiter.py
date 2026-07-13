from __future__ import annotations

from kungfu_chess.model.board import Board
from kungfu_chess.model.color import Color
from kungfu_chess.model.piece import Piece, PieceKind, PieceState
from kungfu_chess.model.position import Position
from kungfu_chess.realtime.real_time_arbiter import RealTimeArbiter


def _empty_grid(rows: int, cols: int) -> list[list[None]]:
    return [[None for _ in range(cols)] for _ in range(rows)]


def _piece(color: Color, kind: PieceKind, cell: Position) -> Piece:
    return Piece(color=color, kind=kind, cell=cell)


def test_one_square_move_takes_1000ms():
    grid = _empty_grid(3, 3)
    rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    grid[0][0] = rook
    board = Board(grid)
    arbiter = RealTimeArbiter()

    arbiter.start_motion(rook, Position(row=0, col=1), start_time=0, board=board)

    events, cancellations, collisions = arbiter.advance_time(board, 999)
    assert events == []
    assert cancellations == []
    assert collisions == []
    assert board.piece_at(Position(row=0, col=1)) is None

    events, cancellations, collisions = arbiter.advance_time(board, 1000)

    assert len(events) == 1
    assert board.piece_at(Position(row=0, col=1)) is rook


def test_n_square_move_takes_n_times_1000ms():
    grid = _empty_grid(3, 5)
    rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    grid[0][0] = rook
    board = Board(grid)
    arbiter = RealTimeArbiter()

    arbiter.start_motion(rook, Position(row=0, col=3), start_time=0, board=board)

    events, cancellations, collisions = arbiter.advance_time(board, 2999)
    assert events == []
    assert cancellations == []
    assert collisions == []
    events, cancellations, collisions = arbiter.advance_time(board, 3000)
    assert len(events) == 1
    assert board.piece_at(Position(row=0, col=3)) is rook


def test_diagonal_move_uses_chebyshev_distance_not_euclidean():
    grid = _empty_grid(5, 5)
    bishop = _piece(Color.WHITE, PieceKind.BISHOP, Position(row=0, col=0))
    grid[0][0] = bishop
    board = Board(grid)
    arbiter = RealTimeArbiter()

    arbiter.start_motion(bishop, Position(row=3, col=3), start_time=0, board=board)

    events, cancellations, collisions = arbiter.advance_time(board, 2999)
    assert events == []
    assert cancellations == []
    assert collisions == []
    events, cancellations, collisions = arbiter.advance_time(board, 3000)
    assert len(events) == 1
    assert board.piece_at(Position(row=3, col=3)) is bishop


def test_arrival_clears_source_and_occupies_destination():
    grid = _empty_grid(3, 3)
    rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    grid[0][0] = rook
    board = Board(grid)
    arbiter = RealTimeArbiter()

    arbiter.start_motion(rook, Position(row=0, col=2), start_time=0, board=board)
    arbiter.advance_time(board, 2000)

    assert board.piece_at(Position(row=0, col=0)) is None
    assert board.piece_at(Position(row=0, col=2)) is rook


def test_arrival_captures_occupying_piece():
    grid = _empty_grid(3, 3)
    rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    enemy = _piece(Color.BLACK, PieceKind.PAWN, Position(row=0, col=1))
    grid[0][0] = rook
    grid[0][1] = enemy
    board = Board(grid)
    arbiter = RealTimeArbiter()

    arbiter.start_motion(rook, Position(row=0, col=1), start_time=0, board=board)
    events, cancellations, collisions = arbiter.advance_time(board, 1000)

    assert board.piece_at(Position(row=0, col=1)) is rook
    assert events[0].captured_piece is enemy
    assert cancellations == []
    assert collisions == []


def test_arrival_capturing_king_flags_king_captured():
    grid = _empty_grid(3, 3)
    rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    king = _piece(Color.BLACK, PieceKind.KING, Position(row=0, col=1))
    grid[0][0] = rook
    grid[0][1] = king
    board = Board(grid)
    arbiter = RealTimeArbiter()

    arbiter.start_motion(rook, Position(row=0, col=1), start_time=0, board=board)
    events, cancellations, collisions = arbiter.advance_time(board, 1000)

    assert events[0].king_captured is True


def test_arrival_capturing_non_king_does_not_flag_king_captured():
    grid = _empty_grid(3, 3)
    rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    enemy = _piece(Color.BLACK, PieceKind.PAWN, Position(row=0, col=1))
    grid[0][0] = rook
    grid[0][1] = enemy
    board = Board(grid)
    arbiter = RealTimeArbiter()

    arbiter.start_motion(rook, Position(row=0, col=1), start_time=0, board=board)
    events, cancellations, collisions = arbiter.advance_time(board, 1000)

    assert events[0].king_captured is False


def test_advance_time_before_arrival_does_nothing():
    grid = _empty_grid(3, 3)
    rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    grid[0][0] = rook
    board = Board(grid)
    arbiter = RealTimeArbiter()

    arbiter.start_motion(rook, Position(row=0, col=2), start_time=0, board=board)
    events, cancellations, collisions = arbiter.advance_time(board, 500)

    assert events == []
    assert cancellations == []
    assert collisions == []
    assert board.piece_at(Position(row=0, col=0)) is rook
    assert board.piece_at(Position(row=0, col=2)) is None


def test_start_motion_sets_piece_state_to_moving():
    grid = _empty_grid(3, 3)
    rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    grid[0][0] = rook
    board = Board(grid)
    arbiter = RealTimeArbiter()

    arbiter.start_motion(rook, Position(row=0, col=1), start_time=0, board=board)

    assert rook.state is PieceState.MOVING


def test_arrival_sets_moved_piece_state_to_idle_and_captured_piece_state_to_captured():
    grid = _empty_grid(3, 3)
    rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    enemy = _piece(Color.BLACK, PieceKind.PAWN, Position(row=0, col=1))
    grid[0][0] = rook
    grid[0][1] = enemy
    board = Board(grid)
    arbiter = RealTimeArbiter()

    arbiter.start_motion(rook, Position(row=0, col=1), start_time=0, board=board)
    arbiter.advance_time(board, 1000)

    assert rook.state is PieceState.IDLE
    assert enemy.state is PieceState.CAPTURED


def test_has_active_motion_reflects_active_and_settled_motions():
    grid = _empty_grid(3, 3)
    rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    grid[0][0] = rook
    board = Board(grid)
    arbiter = RealTimeArbiter()

    assert arbiter.has_active_motion() is False

    arbiter.start_motion(rook, Position(row=0, col=1), start_time=0, board=board)
    assert arbiter.has_active_motion() is True


def test_active_motions_reflects_active_and_settled_motions():
    grid = _empty_grid(3, 3)
    rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    grid[0][0] = rook
    board = Board(grid)
    arbiter = RealTimeArbiter()

    assert arbiter.active_motions() == ()

    motion = arbiter.start_motion(rook, Position(row=0, col=1), start_time=0, board=board)
    assert arbiter.active_motions() == (motion,)

    arbiter.advance_time(board, 1000)
    assert arbiter.active_motions() == ()

    arbiter.advance_time(board, 1000)
    assert arbiter.has_active_motion() is False


def test_cancel_motion_removes_it_without_resolving():
    grid = _empty_grid(3, 3)
    rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    grid[0][0] = rook
    board = Board(grid)
    arbiter = RealTimeArbiter()
    motion = arbiter.start_motion(rook, Position(row=0, col=1), start_time=0, board=board)

    cancelled = arbiter.cancel_motion(motion)

    assert cancelled is True
    assert arbiter.has_active_motion() is False
    events, cancellations, collisions = arbiter.advance_time(board, 1000)
    assert events == []
    assert cancellations == []
    assert collisions == []
    assert board.piece_at(Position(row=0, col=0)) is rook
    assert board.piece_at(Position(row=0, col=1)) is None


def test_cancel_motion_returns_false_for_unknown_motion():
    grid = _empty_grid(3, 3)
    rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    grid[0][0] = rook
    board = Board(grid)
    arbiter = RealTimeArbiter()
    motion = arbiter.start_motion(rook, Position(row=0, col=1), start_time=0, board=board)
    arbiter.advance_time(board, 1000)

    assert arbiter.cancel_motion(motion) is False


def test_is_piece_moving_false_when_no_motion_active():
    grid = _empty_grid(3, 3)
    rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    grid[0][0] = rook
    board = Board(grid)
    arbiter = RealTimeArbiter()

    assert arbiter.is_piece_moving(rook) is False


def test_is_piece_moving_true_for_the_moving_piece():
    grid = _empty_grid(3, 3)
    rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    grid[0][0] = rook
    board = Board(grid)
    arbiter = RealTimeArbiter()

    arbiter.start_motion(rook, Position(row=0, col=1), start_time=0, board=board)

    assert arbiter.is_piece_moving(rook) is True


def test_is_piece_moving_false_for_a_different_piece_while_one_is_moving():
    grid = _empty_grid(3, 3)
    rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    bishop = _piece(Color.WHITE, PieceKind.BISHOP, Position(row=2, col=2))
    grid[0][0] = rook
    grid[2][2] = bishop
    board = Board(grid)
    arbiter = RealTimeArbiter()

    arbiter.start_motion(rook, Position(row=0, col=1), start_time=0, board=board)

    assert arbiter.is_piece_moving(bishop) is False


def test_is_piece_moving_false_after_arrival_settles():
    grid = _empty_grid(3, 3)
    rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    grid[0][0] = rook
    board = Board(grid)
    arbiter = RealTimeArbiter()

    arbiter.start_motion(rook, Position(row=0, col=1), start_time=0, board=board)
    arbiter.advance_time(board, 1000)

    assert arbiter.is_piece_moving(rook) is False


def test_start_motion_sets_target_to_piece_at_destination():
    grid = _empty_grid(3, 3)
    rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    enemy = _piece(Color.BLACK, PieceKind.PAWN, Position(row=0, col=1))
    grid[0][0] = rook
    grid[0][1] = enemy
    board = Board(grid)
    arbiter = RealTimeArbiter()

    motion = arbiter.start_motion(rook, Position(row=0, col=1), start_time=0, board=board)

    assert motion.target is enemy


def test_start_motion_sets_target_to_none_when_destination_empty():
    grid = _empty_grid(3, 3)
    rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    grid[0][0] = rook
    board = Board(grid)
    arbiter = RealTimeArbiter()

    motion = arbiter.start_motion(rook, Position(row=0, col=1), start_time=0, board=board)

    assert motion.target is None


def test_advance_time_cancels_motion_whose_target_is_captured_by_another_arrival():
    grid = _empty_grid(3, 4)
    mover = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    target = _piece(Color.BLACK, PieceKind.ROOK, Position(row=0, col=2))
    assassin = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=3))
    grid[0][0] = mover
    grid[0][2] = target
    grid[0][3] = assassin
    board = Board(grid)
    arbiter = RealTimeArbiter()

    mover_motion = arbiter.start_motion(mover, Position(row=0, col=2), start_time=0, board=board)
    arbiter.start_motion(assassin, Position(row=0, col=2), start_time=0, board=board)

    arbiter.advance_time(board, 1000)

    assert mover_motion not in arbiter.active_motions()
    assert mover.state is PieceState.IDLE
    assert board.piece_at(Position(row=0, col=0)) is mover


def test_advance_time_reports_cancellation_event_with_piece_source_destination_and_target():
    grid = _empty_grid(3, 4)
    mover = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    target = _piece(Color.BLACK, PieceKind.ROOK, Position(row=0, col=2))
    assassin = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=3))
    grid[0][0] = mover
    grid[0][2] = target
    grid[0][3] = assassin
    board = Board(grid)
    arbiter = RealTimeArbiter()

    arbiter.start_motion(mover, Position(row=0, col=2), start_time=0, board=board)
    arbiter.start_motion(assassin, Position(row=0, col=2), start_time=0, board=board)

    events, cancellations, collisions = arbiter.advance_time(board, 1000)

    assert len(cancellations) == 1
    cancellation = cancellations[0]
    assert cancellation.piece is mover
    assert cancellation.source == Position(row=0, col=0)
    assert cancellation.destination == Position(row=0, col=2)
    assert cancellation.target is target


def test_advance_time_does_not_cancel_motion_whose_target_survives():
    grid = _empty_grid(3, 3)
    rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    enemy = _piece(Color.BLACK, PieceKind.PAWN, Position(row=0, col=1))
    grid[0][0] = rook
    grid[0][1] = enemy
    board = Board(grid)
    arbiter = RealTimeArbiter()

    arbiter.start_motion(rook, Position(row=0, col=1), start_time=0, board=board)
    events, cancellations, collisions = arbiter.advance_time(board, 1000)

    assert len(events) == 1
    assert events[0].captured_piece is enemy
    assert cancellations == []


def test_advance_time_does_not_cancel_when_target_relocates_without_being_captured():
    grid = _empty_grid(3, 4)
    mover = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    target = _piece(Color.BLACK, PieceKind.ROOK, Position(row=0, col=2))
    grid[0][0] = mover
    grid[0][2] = target
    board = Board(grid)
    arbiter = RealTimeArbiter()

    arbiter.start_motion(mover, Position(row=0, col=2), start_time=0, board=board)
    arbiter.start_motion(target, Position(row=0, col=3), start_time=0, board=board)

    events, cancellations, collisions = arbiter.advance_time(board, 1000)
    assert cancellations == []
    assert board.piece_at(Position(row=0, col=3)) is target

    events, cancellations, collisions = arbiter.advance_time(board, 2000)

    assert cancellations == []
    assert len(events) == 1
    assert events[0].captured_piece is None
    assert board.piece_at(Position(row=0, col=2)) is mover


def test_advance_time_cancels_motion_due_in_the_same_batch_as_the_capturing_arrival():
    grid = _empty_grid(3, 4)
    mover = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    target = _piece(Color.BLACK, PieceKind.ROOK, Position(row=0, col=2))
    assassin = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=3))
    grid[0][0] = mover
    grid[0][2] = target
    grid[0][3] = assassin
    board = Board(grid)
    arbiter = RealTimeArbiter()

    arbiter.start_motion(mover, Position(row=0, col=2), start_time=0, board=board)
    arbiter.start_motion(assassin, Position(row=0, col=2), start_time=0, board=board)

    events, cancellations, collisions = arbiter.advance_time(board, 2000)

    assert len(events) == 1
    assert events[0].piece is assassin
    assert len(cancellations) == 1
    assert cancellations[0].piece is mover
    assert board.piece_at(Position(row=0, col=0)) is mover
    assert board.piece_at(Position(row=0, col=2)) is assassin


def test_advance_time_cancellation_ignores_new_occupant_after_target_gone():
    grid = _empty_grid(3, 5)
    mover = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    target = _piece(Color.BLACK, PieceKind.ROOK, Position(row=0, col=2))
    assassin = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=3))
    newcomer = _piece(Color.BLACK, PieceKind.ROOK, Position(row=0, col=4))
    grid[0][0] = mover
    grid[0][2] = target
    grid[0][3] = assassin
    grid[0][4] = newcomer
    board = Board(grid)
    arbiter = RealTimeArbiter()

    arbiter.start_motion(mover, Position(row=0, col=2), start_time=0, board=board)
    arbiter.start_motion(assassin, Position(row=0, col=2), start_time=0, board=board)
    arbiter.advance_time(board, 1000)

    arbiter.start_motion(newcomer, Position(row=0, col=2), start_time=1000, board=board)
    events, cancellations, collisions = arbiter.advance_time(board, 3000)

    assert cancellations == []
    assert len(events) == 1
    assert events[0].piece is newcomer
    assert events[0].captured_piece is assassin
    assert board.piece_at(Position(row=0, col=0)) is mover
    assert board.piece_at(Position(row=0, col=2)) is newcomer


def test_cancel_motion_resets_piece_state_to_idle():
    grid = _empty_grid(3, 3)
    rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    grid[0][0] = rook
    board = Board(grid)
    arbiter = RealTimeArbiter()
    motion = arbiter.start_motion(rook, Position(row=0, col=1), start_time=0, board=board)

    arbiter.cancel_motion(motion)

    assert rook.state is PieceState.IDLE


def test_advance_time_cancels_both_motions_on_genuine_mid_path_crossing():
    grid = _empty_grid(5, 5)
    slider = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    crosser = _piece(Color.BLACK, PieceKind.ROOK, Position(row=2, col=2))
    grid[0][0] = slider
    grid[2][2] = crosser
    board = Board(grid)
    arbiter = RealTimeArbiter()

    slider_motion = arbiter.start_motion(slider, Position(row=0, col=4), start_time=0, board=board)
    crosser_motion = arbiter.start_motion(crosser, Position(row=0, col=2), start_time=0, board=board)

    arbiter.advance_time(board, 1000)

    assert slider_motion not in arbiter.active_motions()
    assert crosser_motion not in arbiter.active_motions()
    assert slider.state is PieceState.IDLE
    assert crosser.state is PieceState.IDLE
    assert board.piece_at(Position(row=0, col=0)) is slider
    assert board.piece_at(Position(row=2, col=2)) is crosser


def test_advance_time_reports_collision_event_with_both_pieces_and_cell():
    grid = _empty_grid(5, 5)
    slider = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    crosser = _piece(Color.BLACK, PieceKind.ROOK, Position(row=2, col=2))
    grid[0][0] = slider
    grid[2][2] = crosser
    board = Board(grid)
    arbiter = RealTimeArbiter()

    arbiter.start_motion(slider, Position(row=0, col=4), start_time=0, board=board)
    arbiter.start_motion(crosser, Position(row=0, col=2), start_time=0, board=board)

    events, cancellations, collisions = arbiter.advance_time(board, 1000)

    assert events == []
    assert cancellations == []
    assert len(collisions) == 1
    collision = collisions[0]
    assert collision.piece_a is slider
    assert collision.piece_b is crosser
    assert collision.cell == Position(row=0, col=2)
    assert collision.time == 1000


def test_advance_time_mutually_cancels_race_to_shared_empty_destination():
    grid = _empty_grid(3, 5)
    mover_a = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    mover_b = _piece(Color.BLACK, PieceKind.ROOK, Position(row=0, col=4))
    grid[0][0] = mover_a
    grid[0][4] = mover_b
    board = Board(grid)
    arbiter = RealTimeArbiter()

    arbiter.start_motion(mover_a, Position(row=0, col=2), start_time=0, board=board)
    arbiter.start_motion(mover_b, Position(row=0, col=2), start_time=0, board=board)

    events, cancellations, collisions = arbiter.advance_time(board, 1000)

    assert events == []
    assert len(collisions) == 1
    assert board.piece_at(Position(row=0, col=0)) is mover_a
    assert board.piece_at(Position(row=0, col=4)) is mover_b
    assert board.piece_at(Position(row=0, col=2)) is None


def test_advance_time_collision_is_color_blind():
    grid = _empty_grid(3, 5)
    mover_a = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    mover_b = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=4))
    grid[0][0] = mover_a
    grid[0][4] = mover_b
    board = Board(grid)
    arbiter = RealTimeArbiter()

    arbiter.start_motion(mover_a, Position(row=0, col=2), start_time=0, board=board)
    arbiter.start_motion(mover_b, Position(row=0, col=2), start_time=0, board=board)

    events, cancellations, collisions = arbiter.advance_time(board, 1000)

    assert len(collisions) == 1
    assert board.piece_at(Position(row=0, col=2)) is None


def test_advance_time_does_not_collide_when_paths_never_share_a_cell():
    grid = _empty_grid(4, 4)
    rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    bishop = _piece(Color.BLACK, PieceKind.BISHOP, Position(row=3, col=3))
    grid[0][0] = rook
    grid[3][3] = bishop
    board = Board(grid)
    arbiter = RealTimeArbiter()

    arbiter.start_motion(rook, Position(row=0, col=2), start_time=0, board=board)
    arbiter.start_motion(bishop, Position(row=1, col=1), start_time=0, board=board)

    events, cancellations, collisions = arbiter.advance_time(board, 2000)

    assert collisions == []
    assert cancellations == []
    assert len(events) == 2
    assert board.piece_at(Position(row=0, col=2)) is rook
    assert board.piece_at(Position(row=1, col=1)) is bishop


def test_advance_time_target_captured_cancellation_still_takes_priority_over_collision_when_no_overlap():
    grid = _empty_grid(3, 4)
    mover = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    target = _piece(Color.BLACK, PieceKind.ROOK, Position(row=0, col=2))
    assassin = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=3))
    grid[0][0] = mover
    grid[0][2] = target
    grid[0][3] = assassin
    board = Board(grid)
    arbiter = RealTimeArbiter()

    arbiter.start_motion(mover, Position(row=0, col=2), start_time=0, board=board)
    arbiter.start_motion(assassin, Position(row=0, col=2), start_time=0, board=board)

    events, cancellations, collisions = arbiter.advance_time(board, 1000)

    assert collisions == []
    assert len(events) == 1
    assert events[0].piece is assassin
    assert events[0].captured_piece is target
    assert len(cancellations) == 1
    assert cancellations[0].piece is mover


def test_advance_time_knight_motion_participates_in_shared_destination_collision():
    grid = _empty_grid(3, 3)
    knight = _piece(Color.WHITE, PieceKind.KNIGHT, Position(row=0, col=0))
    rook = _piece(Color.BLACK, PieceKind.ROOK, Position(row=2, col=2))
    grid[0][0] = knight
    grid[2][2] = rook
    board = Board(grid)
    arbiter = RealTimeArbiter()

    arbiter.start_motion(knight, Position(row=2, col=1), start_time=0, board=board)
    arbiter.start_motion(rook, Position(row=2, col=1), start_time=0, board=board)

    events, cancellations, collisions = arbiter.advance_time(board, 1000)

    assert events == []
    assert len(collisions) == 1
    assert board.piece_at(Position(row=0, col=0)) is knight
    assert board.piece_at(Position(row=2, col=2)) is rook
    assert board.piece_at(Position(row=2, col=1)) is None


def test_advance_time_knight_motion_is_exempt_from_intermediate_path_collision():
    grid = _empty_grid(3, 4)
    knight = _piece(Color.WHITE, PieceKind.KNIGHT, Position(row=0, col=0))
    rook = _piece(Color.BLACK, PieceKind.ROOK, Position(row=1, col=1))
    grid[0][0] = knight
    grid[1][1] = rook
    board = Board(grid)
    arbiter = RealTimeArbiter()

    arbiter.start_motion(knight, Position(row=2, col=1), start_time=0, board=board)
    arbiter.start_motion(rook, Position(row=1, col=3), start_time=0, board=board)

    events, cancellations, collisions = arbiter.advance_time(board, 2000)

    assert collisions == []
    assert len(events) == 2
    assert board.piece_at(Position(row=2, col=1)) is knight
    assert board.piece_at(Position(row=1, col=3)) is rook


def test_advance_time_collision_detection_runs_before_arrival_resolution_in_the_same_call():
    grid = _empty_grid(5, 5)
    slider = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    crosser = _piece(Color.BLACK, PieceKind.ROOK, Position(row=2, col=2))
    grid[0][0] = slider
    grid[2][2] = crosser
    board = Board(grid)
    arbiter = RealTimeArbiter()

    arbiter.start_motion(slider, Position(row=0, col=4), start_time=0, board=board)
    arbiter.start_motion(crosser, Position(row=0, col=2), start_time=0, board=board)

    events, cancellations, collisions = arbiter.advance_time(board, 4000)

    assert events == []
    assert len(collisions) == 1
    assert board.piece_at(Position(row=0, col=0)) is slider
    assert board.piece_at(Position(row=2, col=2)) is crosser


def test_advance_time_three_way_overlap_resolves_deterministically():
    grid = _empty_grid(3, 5)
    first = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    second = _piece(Color.BLACK, PieceKind.ROOK, Position(row=0, col=4))
    third = _piece(Color.WHITE, PieceKind.BISHOP, Position(row=2, col=0))
    grid[0][0] = first
    grid[0][4] = second
    grid[2][0] = third
    board = Board(grid)
    arbiter = RealTimeArbiter()

    arbiter.start_motion(first, Position(row=0, col=2), start_time=0, board=board)
    arbiter.start_motion(second, Position(row=0, col=2), start_time=0, board=board)
    arbiter.start_motion(third, Position(row=0, col=2), start_time=0, board=board)

    events, cancellations, collisions = arbiter.advance_time(board, 2000)

    assert len(collisions) == 1
    assert board.piece_at(Position(row=0, col=0)) is first
    assert board.piece_at(Position(row=0, col=4)) is second
    assert len(events) == 1
    assert events[0].piece is third
    assert board.piece_at(Position(row=0, col=2)) is third


def test_advance_time_no_collisions_or_cancellations_on_ordinary_single_motion_arrival():
    grid = _empty_grid(3, 3)
    rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    grid[0][0] = rook
    board = Board(grid)
    arbiter = RealTimeArbiter()

    arbiter.start_motion(rook, Position(row=0, col=1), start_time=0, board=board)
    events, cancellations, collisions = arbiter.advance_time(board, 1000)

    assert len(events) == 1
    assert cancellations == []
    assert collisions == []
