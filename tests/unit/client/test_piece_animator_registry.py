from __future__ import annotations

import pytest

import kungfu_chess.client.animation.piece_animator_registry as registry_module
from kungfu_chess.client.animation.animation_state import AnimationState
from kungfu_chess.client.animation.piece_animator_registry import PieceAnimatorRegistry, UnknownPieceIdError
from kungfu_chess.client.events.game_events import GameOver, MoveAccepted, MoveRejected, PieceArrived
from kungfu_chess.model.board import Board
from kungfu_chess.model.color import Color
from kungfu_chess.model.piece import Piece, PieceKind
from kungfu_chess.model.position import Position


def _empty_grid(rows: int, cols: int) -> list[list[None]]:
    return [[None for _ in range(cols)] for _ in range(rows)]


def _piece(color: Color, kind: PieceKind, cell: Position) -> Piece:
    return Piece(color=color, kind=kind, cell=cell)


def _small_board():
    grid = _empty_grid(3, 3)
    pawn1 = _piece(Color.WHITE, PieceKind.PAWN, Position(row=0, col=0))
    pawn2 = _piece(Color.WHITE, PieceKind.PAWN, Position(row=0, col=1))
    rook = _piece(Color.BLACK, PieceKind.ROOK, Position(row=2, col=2))
    grid[0][0] = pawn1
    grid[0][1] = pawn2
    grid[2][2] = rook
    board = Board(grid)
    return board, pawn1, pawn2, rook


def test_from_board_builds_one_animator_per_piece_and_shares_states_per_combo(monkeypatch):
    board, pawn1, pawn2, rook = _small_board()
    original_load = registry_module.load_piece_states
    calls = []

    def counting_load(piece_dir):
        calls.append(piece_dir)
        return original_load(piece_dir)

    monkeypatch.setattr(registry_module, "load_piece_states", counting_load)

    registry = PieceAnimatorRegistry.from_board(board)

    assert registry.animator_for(pawn1.id) is not None
    assert registry.animator_for(pawn2.id) is not None
    assert registry.animator_for(rook.id) is not None

    # same kind+color (both white pawns) -> the exact same states dict object
    assert registry.animator_for(pawn1.id).states is registry.animator_for(pawn2.id).states
    # different kind+color -> a different states dict object
    assert registry.animator_for(pawn1.id).states is not registry.animator_for(rook.id).states

    # loaded once per distinct combo (PW, RB) - not once per piece (3 pieces, 2 combos)
    assert len(calls) == 2


def test_on_event_move_accepted_transitions_only_the_matching_animator():
    board, pawn1, pawn2, rook = _small_board()
    registry = PieceAnimatorRegistry.from_board(board)

    registry.on_event(
        MoveAccepted(
            piece_id=pawn1.id, from_cell=Position(row=0, col=0), to_cell=Position(row=0, col=2), duration_ms=1000
        )
    )

    assert registry.animator_for(pawn1.id).current_state == AnimationState.MOVE
    assert registry.animator_for(pawn2.id).current_state == AnimationState.IDLE
    assert registry.animator_for(rook.id).current_state == AnimationState.IDLE


def test_on_event_with_unknown_piece_id_is_a_safe_no_op():
    board, pawn1, _, _ = _small_board()
    registry = PieceAnimatorRegistry.from_board(board)

    registry.on_event(
        MoveAccepted(piece_id=999999, from_cell=Position(row=0, col=0), to_cell=Position(row=0, col=1), duration_ms=1000)
    )  # no exception == success

    assert registry.animator_for(pawn1.id).current_state == AnimationState.IDLE


def test_on_event_with_move_rejected_and_game_over_is_a_safe_no_op():
    board, pawn1, _, _ = _small_board()
    registry = PieceAnimatorRegistry.from_board(board)

    registry.on_event(MoveRejected(reason="cooldown_active"))
    registry.on_event(GameOver(winner_color=Color.WHITE))

    assert registry.animator_for(pawn1.id).current_state == AnimationState.IDLE


def test_advance_all_advances_every_held_animator():
    board, pawn1, pawn2, rook = _small_board()
    registry = PieceAnimatorRegistry.from_board(board)

    registry.advance_all(500)

    for piece_id in (pawn1.id, pawn2.id, rook.id):
        assert registry.animator_for(piece_id).elapsed_ms_in_state == 500


def test_animator_for_raises_unknown_piece_id_error_naming_the_id():
    board, _, _, _ = _small_board()
    registry = PieceAnimatorRegistry.from_board(board)

    with pytest.raises(UnknownPieceIdError) as exc_info:
        registry.animator_for(424242)

    assert "424242" in str(exc_info.value)


def test_animator_for_still_returns_the_animator_of_a_captured_piece():
    board, pawn1, pawn2, rook = _small_board()
    registry = PieceAnimatorRegistry.from_board(board)

    registry.on_event(PieceArrived(piece_id=rook.id, cell=Position(row=0, col=0), captured_piece_id=pawn1.id))

    animator = registry.animator_for(pawn1.id)
    assert animator is not None
    assert animator.piece_id == pawn1.id
