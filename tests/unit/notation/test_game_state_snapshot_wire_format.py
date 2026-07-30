"""Unit tests for kungfu_chess/notation/game_state_snapshot_wire_format.py
- round-trip (ScoreSnapshot, MovesLogSnapshot, clock_ms -> wire text ->
reconstructed triple) coverage, mirroring
tests/unit/notation/test_game_event_wire_format.py's own structure.
Pure, no networking, no server/ import - this module has none of
either dependency.
"""

from __future__ import annotations

import pytest

from kungfu_chess.client.events.observers import CaptureLogEntry, MoveLogEntry, MovesLogSnapshot, ScoreSnapshot
from kungfu_chess.model.color import Color
from kungfu_chess.model.piece import PieceKind
from kungfu_chess.model.position import Position
from kungfu_chess.notation.game_state_snapshot_wire_format import (
    LOG_DELTA_MESSAGE_PREFIX,
    STATE_SNAPSHOT_MESSAGE_PREFIX,
    MalformedGameStateSnapshotWireFormatError,
    format_game_state_snapshot,
    format_log_delta,
    parse_game_state_snapshot,
    parse_log_delta,
)


def test_round_trips_zero_zero_score_with_an_empty_log():
    score = ScoreSnapshot(score_by_color={Color.WHITE: 0, Color.BLACK: 0})
    log = MovesLogSnapshot(entries=())

    text = format_game_state_snapshot(score, log, clock_ms=0)
    parsed_score, parsed_log, parsed_clock_ms = parse_game_state_snapshot(text)

    assert parsed_score == score
    assert parsed_log == log
    assert parsed_clock_ms == 0


def test_round_trips_nonzero_scores_for_both_colors():
    score = ScoreSnapshot(score_by_color={Color.WHITE: 9, Color.BLACK: 3})
    log = MovesLogSnapshot(entries=())

    text = format_game_state_snapshot(score, log, clock_ms=12345)
    parsed_score, parsed_log, parsed_clock_ms = parse_game_state_snapshot(text)

    assert parsed_score == score
    assert parsed_clock_ms == 12345


def test_round_trips_a_single_move_log_entry():
    entry = MoveLogEntry(
        piece_kind=PieceKind.PAWN,
        piece_color=Color.WHITE,
        from_cell=Position(row=6, col=4),
        to_cell=Position(row=4, col=4),
        is_jump=False,
        recorded_at_clock_ms=1000,
    )
    score = ScoreSnapshot(score_by_color={Color.WHITE: 0, Color.BLACK: 0})
    log = MovesLogSnapshot(entries=(entry,))

    text = format_game_state_snapshot(score, log, clock_ms=1000)
    _parsed_score, parsed_log, _parsed_clock_ms = parse_game_state_snapshot(text)

    assert parsed_log == log


def test_round_trips_a_single_jump_move_log_entry():
    entry = MoveLogEntry(
        piece_kind=PieceKind.ROOK,
        piece_color=Color.BLACK,
        from_cell=Position(row=0, col=0),
        to_cell=Position(row=0, col=0),
        is_jump=True,
        recorded_at_clock_ms=500,
    )
    score = ScoreSnapshot(score_by_color={Color.WHITE: 0, Color.BLACK: 0})
    log = MovesLogSnapshot(entries=(entry,))

    text = format_game_state_snapshot(score, log, clock_ms=500)
    _parsed_score, parsed_log, _parsed_clock_ms = parse_game_state_snapshot(text)

    assert parsed_log == log


def test_round_trips_a_single_capture_log_entry():
    entry = CaptureLogEntry(
        piece_kind=PieceKind.QUEEN,
        piece_color=Color.BLACK,
        cell=Position(row=4, col=4),
        captured_piece_kind=PieceKind.KNIGHT,
        captured_piece_color=Color.WHITE,
        recorded_at_clock_ms=2000,
    )
    score = ScoreSnapshot(score_by_color={Color.WHITE: 0, Color.BLACK: 3})
    log = MovesLogSnapshot(entries=(entry,))

    text = format_game_state_snapshot(score, log, clock_ms=2000)
    parsed_score, parsed_log, parsed_clock_ms = parse_game_state_snapshot(text)

    assert parsed_score == score
    assert parsed_log == log
    assert parsed_clock_ms == 2000


def test_round_trips_a_multi_entry_log_mixing_move_and_capture_entries():
    move_entry = MoveLogEntry(
        piece_kind=PieceKind.PAWN,
        piece_color=Color.WHITE,
        from_cell=Position(row=6, col=4),
        to_cell=Position(row=4, col=4),
        is_jump=False,
        recorded_at_clock_ms=1000,
    )
    capture_entry = CaptureLogEntry(
        piece_kind=PieceKind.QUEEN,
        piece_color=Color.BLACK,
        cell=Position(row=4, col=4),
        captured_piece_kind=PieceKind.PAWN,
        captured_piece_color=Color.WHITE,
        recorded_at_clock_ms=3000,
    )
    score = ScoreSnapshot(score_by_color={Color.WHITE: 0, Color.BLACK: 1})
    log = MovesLogSnapshot(entries=(move_entry, capture_entry))

    text = format_game_state_snapshot(score, log, clock_ms=3000)
    parsed_score, parsed_log, parsed_clock_ms = parse_game_state_snapshot(text)

    assert parsed_score == score
    assert parsed_log == log
    assert parsed_clock_ms == 3000


def test_wire_text_is_a_single_line_starting_with_the_distinct_prefix():
    score = ScoreSnapshot(score_by_color={Color.WHITE: 0, Color.BLACK: 0})
    log = MovesLogSnapshot(entries=())

    text = format_game_state_snapshot(score, log, clock_ms=0)

    assert "\n" not in text
    assert text.startswith(STATE_SNAPSHOT_MESSAGE_PREFIX)


@pytest.mark.parametrize(
    "bad_text",
    [
        "not a wire message at all",
        "STATE:0:0",  # missing clock_ms and entries fields
        "STATE:0:0:0:extra:field",  # too many top-level fields
        "STATE:not_an_int:0:0:",  # non-integer white_score
        "STATE:0:0:not_an_int:",  # non-integer clock_ms
        "STATE:0:0:0:X,P,W,e2,e4,0,1000",  # unrecognized entry tag
        "STATE:0:0:0:M,P,W,e2,e4,0",  # missing recorded_at_clock_ms field
        "STATE:0:0:0:M,P,W,e2,e4,0,1000,extra",  # too many entry fields
        "STATE:0:0:0:M,P,W,zz,e4,0,1000",  # invalid algebraic square
        "STATE:0:0:0:M,X,W,e2,e4,0,1000",  # invalid piece-kind letter
        "STATE:0:0:0:M,P,X,e2,e4,0,1000",  # invalid color letter
        "STATE:0:0:0:C,Q,B,e4,N,W",  # missing recorded_at_clock_ms field (capture)
    ],
)
def test_parse_game_state_snapshot_raises_for_malformed_or_unrecognized_text(bad_text):
    with pytest.raises(MalformedGameStateSnapshotWireFormatError):
        parse_game_state_snapshot(bad_text)


# --- Stage G4 (feature/g4-lean-wire-protocol) - format_log_delta/parse_log_delta ---


def test_log_delta_round_trips_a_move_entry():
    entry = MoveLogEntry(
        piece_kind=PieceKind.PAWN,
        piece_color=Color.WHITE,
        from_cell=Position(row=6, col=4),
        to_cell=Position(row=4, col=4),
        is_jump=False,
        recorded_at_clock_ms=1000,
    )
    score = ScoreSnapshot(score_by_color={Color.WHITE: 0, Color.BLACK: 0})

    text = format_log_delta(seq=1, score=score, entry=entry, clock_ms=1000)
    seq, parsed_score, parsed_entry, parsed_clock_ms = parse_log_delta(text)

    assert seq == 1
    assert parsed_score == score
    assert parsed_entry == entry
    assert parsed_clock_ms == 1000


def test_log_delta_round_trips_a_capture_entry():
    entry = CaptureLogEntry(
        piece_kind=PieceKind.QUEEN,
        piece_color=Color.BLACK,
        cell=Position(row=4, col=4),
        captured_piece_kind=PieceKind.KNIGHT,
        captured_piece_color=Color.WHITE,
        recorded_at_clock_ms=2000,
    )
    score = ScoreSnapshot(score_by_color={Color.WHITE: 0, Color.BLACK: 3})

    text = format_log_delta(seq=2, score=score, entry=entry, clock_ms=2000)
    seq, parsed_score, parsed_entry, parsed_clock_ms = parse_log_delta(text)

    assert seq == 2
    assert parsed_score == score
    assert parsed_entry == entry
    assert parsed_clock_ms == 2000


def test_log_delta_wire_text_is_a_single_line_starting_with_the_distinct_prefix():
    entry = MoveLogEntry(
        piece_kind=PieceKind.PAWN, piece_color=Color.WHITE,
        from_cell=Position(row=6, col=4), to_cell=Position(row=4, col=4),
        is_jump=False, recorded_at_clock_ms=0,
    )
    score = ScoreSnapshot(score_by_color={Color.WHITE: 0, Color.BLACK: 0})

    text = format_log_delta(seq=1, score=score, entry=entry, clock_ms=0)

    assert "\n" not in text
    assert text.startswith(LOG_DELTA_MESSAGE_PREFIX)


def test_log_delta_message_size_stays_constant_as_the_match_length_grows_unlike_state():
    """The one test that directly proves the quadratic-growth problem
    G4 (feature/g4-lean-wire-protocol) fixes is gone: a "STATE:" full
    snapshot's own wire length keeps growing with every entry the match
    has ever accumulated (the old per-event broadcast), while a
    "LOG_DELTA:" message - built from only the single newest entry,
    regardless of how many entries came before it - stays exactly the
    same size no matter how long the match already is."""

    score = ScoreSnapshot(score_by_color={Color.WHITE: 0, Color.BLACK: 0})

    def filler_entry(col: int) -> MoveLogEntry:
        return MoveLogEntry(
            piece_kind=PieceKind.PAWN, piece_color=Color.WHITE,
            from_cell=Position(row=6, col=col % 8), to_cell=Position(row=4, col=col % 8),
            is_jump=False, recorded_at_clock_ms=col * 1000,
        )

    # The SAME newest entry, appended after a short vs. a long run of
    # preceding filler entries - isolates the real claim (message size
    # is independent of how many entries came BEFORE the newest one),
    # not confounded by seq/clock_ms/entry content simply differing in
    # decimal-digit length between the two cases.
    newest_entry = MoveLogEntry(
        piece_kind=PieceKind.QUEEN, piece_color=Color.BLACK,
        from_cell=Position(row=0, col=0), to_cell=Position(row=0, col=0),
        is_jump=True, recorded_at_clock_ms=9000,
    )
    short_log = MovesLogSnapshot(entries=tuple(filler_entry(i) for i in range(2)) + (newest_entry,))
    long_log = MovesLogSnapshot(entries=tuple(filler_entry(i) for i in range(50)) + (newest_entry,))

    # The OLD per-event broadcast shape: a full "STATE:" snapshot really
    # does grow with the match's own length - this is the exact problem
    # this stage exists to fix, re-confirmed here as the "before" half
    # of the comparison, not merely assumed.
    short_state_text = format_game_state_snapshot(score, short_log, clock_ms=9000)
    long_state_text = format_game_state_snapshot(score, long_log, clock_ms=9000)
    assert len(long_state_text) > len(short_state_text)

    # The NEW per-event message: LOG_DELTA is built from only the single
    # newest entry - its own wire length is identical whether that SAME
    # entry came after a short or a long run of earlier ones.
    short_delta_text = format_log_delta(seq=99, score=score, entry=short_log.entries[-1], clock_ms=9000)
    long_delta_text = format_log_delta(seq=99, score=score, entry=long_log.entries[-1], clock_ms=9000)
    assert len(long_delta_text) == len(short_delta_text)
    assert short_log.entries[-1] == long_log.entries[-1] == newest_entry


@pytest.mark.parametrize(
    "bad_text",
    [
        "not a wire message at all",
        "LOG_DELTA:1:0:0",  # missing clock_ms and entry fields
        "LOG_DELTA:1:0:0:0:M,P,W,e2,e4,0,1000:extra",  # too many top-level fields
        "LOG_DELTA:not_an_int:0:0:0:M,P,W,e2,e4,0,1000",  # non-integer seq
        "LOG_DELTA:1:not_an_int:0:0:M,P,W,e2,e4,0,1000",  # non-integer white_score
        "LOG_DELTA:1:0:0:not_an_int:M,P,W,e2,e4,0,1000",  # non-integer clock_ms
        "LOG_DELTA:1:0:0:0:X,P,W,e2,e4,0,1000",  # unrecognized entry tag
    ],
)
def test_parse_log_delta_raises_for_malformed_or_unrecognized_text(bad_text):
    with pytest.raises(MalformedGameStateSnapshotWireFormatError):
        parse_log_delta(bad_text)
