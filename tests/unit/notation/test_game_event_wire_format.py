"""Unit tests for kungfu_chess/notation/game_event_wire_format.py -
round-trip (event -> wire text -> reconstructed event) coverage for
MoveAccepted/JumpAccepted/PieceArrived, plus format_game_event's None
return for non-motion events and parse_game_event's malformed-input
handling. Pure, no networking - see that module's own docstring for
the full wire-format/error-policy reasoning.
"""

from __future__ import annotations

import pytest

from kungfu_chess.client.events.game_events import (
    GameOver,
    JumpAccepted,
    JumpLanded,
    MoveAccepted,
    MoveRejected,
    PieceArrived,
)
from kungfu_chess.model.color import Color
from kungfu_chess.model.position import Position
from kungfu_chess.notation.game_event_wire_format import (
    EVENT_MESSAGE_PREFIX,
    MalformedGameEventWireFormatError,
    format_game_event,
    parse_game_event,
)


def test_move_accepted_round_trips():
    event = MoveAccepted(piece_id=7, from_cell=Position(row=6, col=4), to_cell=Position(row=4, col=4), duration_ms=2000)

    text = format_game_event(event)
    reconstructed = parse_game_event(text)

    assert reconstructed == event


def test_jump_accepted_round_trips():
    event = JumpAccepted(piece_id=3, from_cell=Position(row=2, col=1), to_cell=Position(row=2, col=1), duration_ms=625)

    text = format_game_event(event)
    reconstructed = parse_game_event(text)

    assert reconstructed == event


def test_piece_arrived_round_trips_with_a_real_captured_piece_id():
    event = PieceArrived(piece_id=12, cell=Position(row=3, col=3), captured_piece_id=0)

    text = format_game_event(event)
    reconstructed = parse_game_event(text)

    assert reconstructed == event


def test_piece_arrived_round_trips_with_captured_piece_id_none():
    event = PieceArrived(piece_id=12, cell=Position(row=3, col=3), captured_piece_id=None)

    text = format_game_event(event)
    reconstructed = parse_game_event(text)

    assert reconstructed == event


def test_jump_landed_round_trips():
    event = JumpLanded(piece_id=5, cell=Position(row=2, col=1))

    text = format_game_event(event)
    reconstructed = parse_game_event(text)

    assert reconstructed == event


def test_wire_text_is_a_single_line_starting_with_the_distinct_prefix():
    text = format_game_event(MoveAccepted(piece_id=1, from_cell=Position(row=0, col=0), to_cell=Position(row=0, col=1), duration_ms=1000))

    assert "\n" not in text
    assert text.startswith(EVENT_MESSAGE_PREFIX)


def test_format_game_event_returns_none_for_non_motion_events():
    assert format_game_event(MoveRejected(reason="illegal_piece_move")) is None
    assert format_game_event(GameOver(winner_color=Color.WHITE)) is None
    assert format_game_event(object()) is None


@pytest.mark.parametrize(
    "bad_text",
    [
        "not a wire message at all",
        "EVT:MOVE:1:e2:e4",  # missing duration_ms field
        "EVT:MOVE:1:e2:e4:1000:extra",  # too many fields
        "EVT:NONSENSE:1:e2:e4:1000",  # unrecognized tag
        "EVT:MOVE:not_an_int:e2:e4:1000",  # non-integer piece_id
        "EVT:MOVE:1:zz:e4:1000",  # invalid algebraic square
        "EVT:ARRIVED:1:e2:not_none_or_int",  # bad captured_piece_id token
        "EVT:ARRIVED:1:e2",  # missing captured_piece_id field
        "EVT:LANDED:1",  # missing cell field
        "EVT:LANDED:1:e2:extra",  # too many fields
        "EVT:LANDED:not_an_int:e2",  # non-integer piece_id
        "EVT:LANDED:1:zz",  # invalid algebraic square
    ],
)
def test_parse_game_event_raises_for_malformed_or_unrecognized_text(bad_text):
    with pytest.raises(MalformedGameEventWireFormatError):
        parse_game_event(bad_text)
