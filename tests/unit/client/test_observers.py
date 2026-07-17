from __future__ import annotations

from kungfu_chess.client.events.game_events import GameOver, JumpAccepted, MoveAccepted, MoveRejected, PieceArrived
from kungfu_chess.client.events.observers import CaptureLogEntry, MoveLogEntry, MovesLogObserver, ScoreObserver
from kungfu_chess.client.events.piece_registry import PieceInfo, PieceRegistry
from kungfu_chess.model.color import Color
from kungfu_chess.model.piece import PieceKind
from kungfu_chess.model.position import Position

WHITE_QUEEN_ID = 1
WHITE_PAWN_ID = 2
BLACK_ROOK_ID = 3
BLACK_PAWN_ID = 4


def _registry() -> PieceRegistry:
    return PieceRegistry(
        {
            WHITE_QUEEN_ID: PieceInfo(kind=PieceKind.QUEEN, color=Color.WHITE),
            WHITE_PAWN_ID: PieceInfo(kind=PieceKind.PAWN, color=Color.WHITE),
            BLACK_ROOK_ID: PieceInfo(kind=PieceKind.ROOK, color=Color.BLACK),
            BLACK_PAWN_ID: PieceInfo(kind=PieceKind.PAWN, color=Color.BLACK),
        }
    )


def test_score_observer_capturing_a_rook_adds_its_value_to_the_capturing_color():
    observer = ScoreObserver(_registry())

    observer.on_event(
        PieceArrived(piece_id=WHITE_QUEEN_ID, cell=Position(row=0, col=0), captured_piece_id=BLACK_ROOK_ID)
    )

    snapshot = observer.snapshot()
    assert snapshot.score_by_color[Color.WHITE] == 5
    assert snapshot.score_by_color[Color.BLACK] == 0


def test_score_observer_piece_arrived_without_capture_changes_nothing():
    observer = ScoreObserver(_registry())

    observer.on_event(PieceArrived(piece_id=WHITE_QUEEN_ID, cell=Position(row=0, col=0), captured_piece_id=None))

    snapshot = observer.snapshot()
    assert snapshot.score_by_color[Color.WHITE] == 0
    assert snapshot.score_by_color[Color.BLACK] == 0


def test_score_observer_accumulates_multiple_captures_per_color():
    observer = ScoreObserver(_registry())

    observer.on_event(
        PieceArrived(piece_id=BLACK_PAWN_ID, cell=Position(row=1, col=1), captured_piece_id=WHITE_PAWN_ID)
    )
    observer.on_event(
        PieceArrived(piece_id=WHITE_QUEEN_ID, cell=Position(row=2, col=2), captured_piece_id=BLACK_ROOK_ID)
    )

    snapshot = observer.snapshot()
    assert snapshot.score_by_color[Color.WHITE] == 5
    assert snapshot.score_by_color[Color.BLACK] == 1


def test_moves_log_observer_records_move_accepted_entry():
    observer = MovesLogObserver(_registry())

    observer.on_event(
        MoveAccepted(
            piece_id=WHITE_QUEEN_ID,
            from_cell=Position(row=0, col=0),
            to_cell=Position(row=0, col=3),
            duration_ms=1000,
        )
    )

    entries = observer.snapshot().entries
    assert entries == (
        MoveLogEntry(
            piece_kind=PieceKind.QUEEN,
            piece_color=Color.WHITE,
            from_cell=Position(row=0, col=0),
            to_cell=Position(row=0, col=3),
            is_jump=False,
        ),
    )


def test_moves_log_observer_records_jump_accepted_entry_with_is_jump_true():
    observer = MovesLogObserver(_registry())

    observer.on_event(
        JumpAccepted(
            piece_id=BLACK_ROOK_ID,
            from_cell=Position(row=2, col=2),
            to_cell=Position(row=2, col=2),
            duration_ms=625,
        )
    )

    entries = observer.snapshot().entries
    assert len(entries) == 1
    assert entries[0].is_jump is True
    assert entries[0].piece_kind == PieceKind.ROOK
    assert entries[0].piece_color == Color.BLACK


def test_moves_log_observer_records_capture_entry_on_piece_arrived():
    observer = MovesLogObserver(_registry())

    observer.on_event(
        PieceArrived(piece_id=WHITE_QUEEN_ID, cell=Position(row=0, col=3), captured_piece_id=BLACK_ROOK_ID)
    )

    entries = observer.snapshot().entries
    assert entries == (
        CaptureLogEntry(
            piece_kind=PieceKind.QUEEN,
            piece_color=Color.WHITE,
            cell=Position(row=0, col=3),
            captured_piece_kind=PieceKind.ROOK,
            captured_piece_color=Color.BLACK,
        ),
    )


def test_moves_log_observer_ignores_move_rejected_and_game_over():
    observer = MovesLogObserver(_registry())

    observer.on_event(MoveRejected(reason="cooldown_active"))
    observer.on_event(GameOver(winner_color=Color.WHITE))

    assert observer.snapshot().entries == ()


def test_moves_log_observer_full_move_then_capture_sequence():
    observer = MovesLogObserver(_registry())

    observer.on_event(
        MoveAccepted(
            piece_id=WHITE_QUEEN_ID,
            from_cell=Position(row=0, col=0),
            to_cell=Position(row=0, col=3),
            duration_ms=1000,
        )
    )
    observer.on_event(
        PieceArrived(piece_id=WHITE_QUEEN_ID, cell=Position(row=0, col=3), captured_piece_id=BLACK_ROOK_ID)
    )

    entries = observer.snapshot().entries
    assert len(entries) == 2
    assert isinstance(entries[0], MoveLogEntry)
    assert isinstance(entries[1], CaptureLogEntry)
