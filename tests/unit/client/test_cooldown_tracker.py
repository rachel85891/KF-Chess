from __future__ import annotations

from kungfu_chess.client.events.cooldown_tracker import CooldownTracker
from kungfu_chess.client.events.game_events import GameOver, MoveRejected, PieceArrived
from kungfu_chess.model.color import Color
from kungfu_chess.model.position import Position
from kungfu_chess.realtime.real_time_arbiter import COOLDOWN_MS

PIECE_ID = 7


def test_piece_never_arrived_returns_zero_ratio():
    tracker = CooldownTracker()

    assert tracker.remaining_ratio(PIECE_ID, current_clock_ms=12345) == 0.0


def test_ratio_is_one_immediately_after_a_real_piece_arrived_event():
    tracker = CooldownTracker()
    tracker.set_current_clock_ms(1000)

    tracker.on_event(PieceArrived(piece_id=PIECE_ID, cell=Position(row=0, col=0), captured_piece_id=None))

    assert tracker.remaining_ratio(PIECE_ID, current_clock_ms=1000) == 1.0


def test_ratio_is_partial_partway_through_cooldown_ms():
    tracker = CooldownTracker()
    tracker.set_current_clock_ms(1000)
    tracker.on_event(PieceArrived(piece_id=PIECE_ID, cell=Position(row=0, col=0), captured_piece_id=None))

    ratio = tracker.remaining_ratio(PIECE_ID, current_clock_ms=1000 + COOLDOWN_MS // 2)

    assert ratio == 0.5


def test_ratio_is_zero_once_cooldown_ms_has_fully_elapsed():
    tracker = CooldownTracker()
    tracker.set_current_clock_ms(1000)
    tracker.on_event(PieceArrived(piece_id=PIECE_ID, cell=Position(row=0, col=0), captured_piece_id=None))

    assert tracker.remaining_ratio(PIECE_ID, current_clock_ms=1000 + COOLDOWN_MS) == 0.0
    assert tracker.remaining_ratio(PIECE_ID, current_clock_ms=1000 + COOLDOWN_MS + 5000) == 0.0


def test_piece_arrived_without_captured_piece_id_still_starts_a_cooldown():
    # Every genuine arrival starts a cooldown, capture or not - re-
    # confirms this isn't accidentally gated on captured_piece_id.
    tracker = CooldownTracker()
    tracker.set_current_clock_ms(500)

    tracker.on_event(PieceArrived(piece_id=PIECE_ID, cell=Position(row=2, col=2), captured_piece_id=None))

    assert tracker.remaining_ratio(PIECE_ID, current_clock_ms=500) == 1.0


def test_irrelevant_event_types_do_not_start_a_cooldown():
    tracker = CooldownTracker()
    tracker.set_current_clock_ms(1000)

    tracker.on_event(MoveRejected(reason="cooldown_active"))
    tracker.on_event(GameOver(winner_color=Color.WHITE))

    assert tracker.remaining_ratio(PIECE_ID, current_clock_ms=1000) == 0.0


def test_set_current_clock_ms_affects_subsequently_recorded_arrivals_only():
    tracker = CooldownTracker()
    tracker.set_current_clock_ms(0)
    tracker.on_event(PieceArrived(piece_id=1, cell=Position(row=0, col=0), captured_piece_id=None))

    tracker.set_current_clock_ms(2000)
    tracker.on_event(PieceArrived(piece_id=2, cell=Position(row=1, col=1), captured_piece_id=None))

    # piece 1 started at clock 0, so by clock 2000 its cooldown (1000ms) is long over
    assert tracker.remaining_ratio(1, current_clock_ms=2000) == 0.0
    # piece 2 started at clock 2000, so at clock 2000 it is fresh
    assert tracker.remaining_ratio(2, current_clock_ms=2000) == 1.0
