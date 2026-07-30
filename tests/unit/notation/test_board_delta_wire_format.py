"""Unit tests for kungfu_chess/notation/board_delta_wire_format.py -
round-trip (seq, changed_cells -> wire text -> reconstructed pair)
coverage, mirroring tests/unit/notation/test_game_state_snapshot_wire_format.py's
own structure. Pure, no networking, no server/ import - this module has
none of either dependency.
"""

from __future__ import annotations

import pytest

from kungfu_chess.model.color import Color
from kungfu_chess.model.piece import PieceKind
from kungfu_chess.model.position import Position
from kungfu_chess.notation.board_delta_wire_format import (
    BOARD_DELTA_MESSAGE_PREFIX,
    MalformedBoardDeltaWireFormatError,
    format_board_delta,
    parse_board_delta,
)


def test_round_trips_a_single_changed_cell():
    changed = {Position(row=6, col=4): None}

    text = format_board_delta(seq=1, changed_cells=changed)
    seq, parsed = parse_board_delta(text)

    assert seq == 1
    assert parsed == changed


def test_round_trips_multiple_changed_cells_including_an_occupied_one():
    changed = {
        Position(row=6, col=4): None,
        Position(row=4, col=4): (Color.WHITE, PieceKind.PAWN),
    }

    text = format_board_delta(seq=7, changed_cells=changed)
    seq, parsed = parse_board_delta(text)

    assert seq == 7
    assert parsed == changed


def test_round_trips_an_empty_delta():
    text = format_board_delta(seq=3, changed_cells={})
    seq, parsed = parse_board_delta(text)

    assert seq == 3
    assert parsed == {}


def test_wire_text_is_a_single_line_starting_with_the_distinct_prefix():
    text = format_board_delta(seq=1, changed_cells={Position(row=0, col=0): None})

    assert "\n" not in text
    assert text.startswith(BOARD_DELTA_MESSAGE_PREFIX)


def test_format_uses_the_same_token_convention_boardprinter_uses():
    changed = {Position(row=0, col=0): (Color.BLACK, PieceKind.ROOK)}

    text = format_board_delta(seq=1, changed_cells=changed)

    assert "a8:bR" in text


def test_cell_order_is_deterministic_regardless_of_dict_insertion_order():
    a2 = Position(row=6, col=0)
    a8 = Position(row=0, col=0)

    text_ascending = format_board_delta(seq=1, changed_cells={a8: None, a2: None})
    text_descending = format_board_delta(seq=1, changed_cells={a2: None, a8: None})

    assert text_ascending == text_descending


@pytest.mark.parametrize(
    "bad_text",
    [
        "not a wire message at all",
        "BOARD_DELTA:not_an_int:e2:.",  # non-integer seq
        "BOARD_DELTA:1:e2",  # malformed cell entry (no token)
        "BOARD_DELTA:1:zz:wP",  # invalid algebraic square
        "BOARD_DELTA:1:e2:xx",  # invalid color/kind letters
        "BOARD_DELTA:1:e2:w",  # token too short
    ],
)
def test_parse_board_delta_raises_for_malformed_or_unrecognized_text(bad_text):
    with pytest.raises(MalformedBoardDeltaWireFormatError):
        parse_board_delta(bad_text)
