"""game_state_snapshot_wire_format.py: bidirectional conversion between
a real (ScoreSnapshot, MovesLogSnapshot, elapsed clock_ms) triple and a
single-line wire text format - the server-authoritative score/move-log/
timer broadcast a future client-side stage needs to render a real side
panel, captured-pieces display, and running game timer.

DOES NOT MODIFY ScoreObserver/MovesLogObserver/ScoreSnapshot/
MovesLogSnapshot/MoveLogEntry/CaptureLogEntry IN ANY WAY (per this
stage's own explicit requirement, re-verified directly against
kungfu_chess/client/events/observers.py before writing this) - this
module only ever READS their already-existing public fields to build
wire text, and only ever CONSTRUCTS them via their existing public
constructors when parsing text back.

WHY A NEW, SIBLING MODULE, NOT APPENDED TO game_event_wire_format.py:
that module serializes ONE MOTION EVENT at a time (MoveAccepted/
JumpAccepted/PieceArrived/JumpLanded) - a single, flat record, always
the same handful of fields per tag. This module serializes a full
point-in-time SNAPSHOT of aggregate state instead: two running scores,
a variable-length list of two DIFFERENTLY-shaped log entry types, and
the elapsed clock - a structurally different kind of data (nested,
variable-length, heterogeneous vs. a single flat record) that would
force a third, unrelated shape/field-count convention into a module
whose entire existing contract is "one flat tag, one fixed field count
per tag, no lists." Keeping this as its own module keeps SRP intact per
module: one module per DISTINCT DATA SHAPE being serialized, not one
module per "anything GameEventPublisher/EventBus ever produces."

WHY A NEW, DISTINCT MESSAGE PREFIX ("STATE:"), unambiguous against both
existing message shapes: like "EVT:" (game_event_wire_format.py's own
marker) and the plain multi-line board-text broadcast, "STATE:" can
never be produced by BoardPrinter (never a single line, no colons in
its own tokens) and is trivially distinguishable from "EVT:" itself by
a plain string-prefix check - the same "distinct leading marker,
unambiguous by construction" principle every wire message in this
project already uses (see game_event_wire_format.py's own "WHY A
DISTINCT SINGLE-LINE PREFIX" section, and jump_command.py's own "J"
marker for the identical reasoning applied a third time).

WIRE SHAPE - THREE DELIMITER LEVELS, NOT ONE (a genuine, deliberate
departure from every other wire-format module in this project, which
all get by with a single ":" level, since none of them has ever needed
to represent a variable-length list of heterogeneous records before):
  - Level 1 (":") separates this message's own top-level fields -
    "STATE", white_score, black_score, clock_ms, and finally the WHOLE
    encoded entries list as one single trailing field.
  - Level 2 ("|") separates individual log entries from each other
    within that trailing field.
  - Level 3 (",") separates one entry's OWN internal fields from each
    other.
None of these three characters can ever appear inside a real field
value, so splitting each level in turn can never misparse a real value
as a delimiter or vice versa: score/clock_ms/is_jump are plain decimal
digits, and piece-kind/color letters and algebraic squares (reusing
kungfu_chess.notation.algebraic_notation's position_to_algebraic/
algebraic_to_position directly, per this stage's own DRY requirement -
not a second square serialization) are all short, fixed-alphabet ASCII
tokens with no ':', '|', or ',' in their possible character sets.

ENTRY ENCODING - "M,..." (MoveLogEntry) or "C,..." (CaptureLogEntry),
mirroring "EVT:"'s own tag-then-fields convention at one smaller,
per-entry scale:
  - "M,<piece_kind letter>,<piece_color letter>,<from square>,
    <to square>,<is_jump 0|1>,<recorded_at_clock_ms>"
  - "C,<piece_kind letter>,<piece_color letter>,<cell square>,
    <captured_piece_kind letter>,<captured_piece_color letter>,
    <recorded_at_clock_ms>"
Piece-kind letters reuse PieceKind.value (already the correct
board-notation letter - kungfu_chess/io/board_parser.py and
kungfu_chess/notation/move_command_format.py already rely on this same
fact) and color letters reuse Color.name[0] ('W'/'B'), the exact two
conventions server/move_command.py's parser and
kungfu_chess/notation/move_command_format.py's formatter already use -
no new letter-mapping table is introduced. Case-SENSITIVE parsing
throughout (unlike move_command.py/jump_command.py's own deliberately
case-INsensitive grammars): this message, like "EVT:", is exclusively
machine-generated (server -> client only) and never hand-typed by a
tester over a raw socket, so there is no real-world case-variance to
tolerate - matching "EVT:"'s own precedent exactly, not move/jump
command's.

SRP: this module ONLY converts between (ScoreSnapshot, MovesLogSnapshot,
clock_ms) and text - no networking, no broadcasting logic of its own
(that stays in server/game_server.py, reusing its existing
_broadcast/_broadcast_event mechanism), and no piece_id/Board/
PieceRegistry lookups of any kind: unlike server/game_server.py's own
per-motion-event broadcaster, there is no piece_id TRANSLATION concern
here at all - MoveLogEntry/CaptureLogEntry already carry
piece_kind/piece_color directly (MovesLogObserver's own job, using a
PieceRegistry, already did that lookup once when the entry was first
recorded), so nothing in this module ever needs a Board or registry
reference.

ONE ERROR TYPE for every malformed reason
(MalformedGameStateSnapshotWireFormatError) - mirrors every other
wire-format module in this project's own "ONE ERROR TYPE" convention:
a caller only ever needs to catch this one type to know "ignore this
message", regardless of which of the three delimiter levels or which
specific field was wrong.
"""

from __future__ import annotations

from typing import Tuple

from kungfu_chess.client.events.observers import (
    CaptureLogEntry,
    MoveLogEntry,
    MovesLogEntry,
    MovesLogSnapshot,
    ScoreSnapshot,
)
from kungfu_chess.model.color import Color
from kungfu_chess.model.piece import PieceKind
from kungfu_chess.notation.algebraic_notation import algebraic_to_position, position_to_algebraic

STATE_SNAPSHOT_MESSAGE_PREFIX = "STATE:"

_MESSAGE_MARKER = "STATE"
_TOP_LEVEL_SEP = ":"
_ENTRY_SEP = "|"
_ENTRY_FIELD_SEP = ","

_MOVE_ENTRY_TAG = "M"
_CAPTURE_ENTRY_TAG = "C"

# STATE, white_score, black_score, clock_ms, entries (one field, itself
# further encoded - see module docstring's "WIRE SHAPE" section).
_TOP_LEVEL_FIELD_COUNT = 5
_MOVE_ENTRY_FIELD_COUNT = 7  # M, kind, color, from, to, is_jump, recorded_at_clock_ms
_CAPTURE_ENTRY_FIELD_COUNT = 7  # C, kind, color, cell, captured_kind, captured_color, recorded_at_clock_ms


class GameStateSnapshotWireFormatError(ValueError):
    """Base class for this module's own errors - mirrors every other
    wire-format module's own ValueError-subclassing convention."""


class MalformedGameStateSnapshotWireFormatError(GameStateSnapshotWireFormatError):
    """Raised by parse_game_state_snapshot for any text that isn't a
    valid wire message in this module's format - see module
    docstring's "ONE ERROR TYPE" section."""


def _format_entry(entry: MovesLogEntry) -> str:
    """Encode one MoveLogEntry/CaptureLogEntry as its own
    ","-separated field group - see module docstring's "ENTRY ENCODING"
    section."""

    if isinstance(entry, CaptureLogEntry):
        return _ENTRY_FIELD_SEP.join(
            [
                _CAPTURE_ENTRY_TAG,
                entry.piece_kind.value,
                entry.piece_color.name[0],
                position_to_algebraic(entry.cell),
                entry.captured_piece_kind.value,
                entry.captured_piece_color.name[0],
                str(entry.recorded_at_clock_ms),
            ]
        )

    return _ENTRY_FIELD_SEP.join(
        [
            _MOVE_ENTRY_TAG,
            entry.piece_kind.value,
            entry.piece_color.name[0],
            position_to_algebraic(entry.from_cell),
            position_to_algebraic(entry.to_cell),
            "1" if entry.is_jump else "0",
            str(entry.recorded_at_clock_ms),
        ]
    )


def format_game_state_snapshot(score: ScoreSnapshot, log: MovesLogSnapshot, clock_ms: int) -> str:
    """Format a real (ScoreSnapshot, MovesLogSnapshot, clock_ms) triple
    as wire text.

    Args:
        score: The current ScoreSnapshot (kungfu_chess/client/events/
            observers.py's ScoreObserver.snapshot()).
        log: The current MovesLogSnapshot (that same module's
            MovesLogObserver.snapshot()).
        clock_ms: The elapsed logical game time (GameEngine.state.
            clock_ms - re-verified directly: starts at 0, only ever
            advances via wait(), so this value already IS "how much
            logical time has elapsed since this session was created,"
            with no separate wall-clock concept needed).

    Returns:
        The single-line wire text - see module docstring's "WIRE SHAPE"
        section for the exact three-delimiter-level encoding.

    Raises:
        InvalidPositionError: Propagated from position_to_algebraic if
            any entry's cell/from_cell/to_cell falls outside the 8x8
            board - believed unreachable in practice, mirroring
            game_event_wire_format.py's own identical, already-accepted
            assumption (every Position here originates from a real
            Board/GameEngine).
    """

    white_score = score.score_by_color.get(Color.WHITE, 0)
    black_score = score.score_by_color.get(Color.BLACK, 0)
    entries_text = _ENTRY_SEP.join(_format_entry(entry) for entry in log.entries)

    return _TOP_LEVEL_SEP.join([_MESSAGE_MARKER, str(white_score), str(black_score), str(clock_ms), entries_text])


def _parse_entry(text: str) -> MovesLogEntry:
    """Decode one ","-separated entry field group back into a real
    MoveLogEntry or CaptureLogEntry - the exact inverse of
    _format_entry."""

    fields = text.split(_ENTRY_FIELD_SEP)
    tag = fields[0] if fields else ""

    try:
        if tag == _MOVE_ENTRY_TAG:
            if len(fields) != _MOVE_ENTRY_FIELD_COUNT:
                raise MalformedGameStateSnapshotWireFormatError(
                    f"expected {_MOVE_ENTRY_FIELD_COUNT} fields for a move log entry, got {len(fields)}: {text!r}"
                )
            return MoveLogEntry(
                piece_kind=PieceKind(fields[1]),
                piece_color=Color(fields[2].lower()),
                from_cell=algebraic_to_position(fields[3]),
                to_cell=algebraic_to_position(fields[4]),
                is_jump=fields[5] == "1",
                recorded_at_clock_ms=int(fields[6]),
            )

        if tag == _CAPTURE_ENTRY_TAG:
            if len(fields) != _CAPTURE_ENTRY_FIELD_COUNT:
                raise MalformedGameStateSnapshotWireFormatError(
                    f"expected {_CAPTURE_ENTRY_FIELD_COUNT} fields for a capture log entry, got {len(fields)}: {text!r}"
                )
            return CaptureLogEntry(
                piece_kind=PieceKind(fields[1]),
                piece_color=Color(fields[2].lower()),
                cell=algebraic_to_position(fields[3]),
                captured_piece_kind=PieceKind(fields[4]),
                captured_piece_color=Color(fields[5].lower()),
                recorded_at_clock_ms=int(fields[6]),
            )
    except MalformedGameStateSnapshotWireFormatError:
        raise
    except ValueError as exc:
        raise MalformedGameStateSnapshotWireFormatError(f"malformed field in log entry {text!r}: {exc}") from None

    raise MalformedGameStateSnapshotWireFormatError(f"unrecognized log entry tag {tag!r} in {text!r}")


def parse_game_state_snapshot(text: str) -> Tuple[ScoreSnapshot, MovesLogSnapshot, int]:
    """Parse one raw wire message back into a real (ScoreSnapshot,
    MovesLogSnapshot, clock_ms) triple - the exact inverse of
    format_game_state_snapshot.

    Args:
        text: The raw message text - a caller should already know this
            starts with STATE_SNAPSHOT_MESSAGE_PREFIX (mirroring
            game_event_wire_format.py's own EVENT_MESSAGE_PREFIX
            dispatch convention) via a plain
            `text.startswith(STATE_SNAPSHOT_MESSAGE_PREFIX)` check
            before ever calling this function; guarded here too
            regardless.

    Returns:
        (score, log, clock_ms), each equal to whatever
        format_game_state_snapshot was originally given.

    Raises:
        MalformedGameStateSnapshotWireFormatError: If `text` doesn't
            start with the "STATE" marker, has the wrong number of
            top-level fields, has a non-integer score/clock_ms field,
            or any entry within it is malformed (wrong entry-level
            field count, unrecognized entry tag, non-integer
            is_jump/recorded_at_clock_ms, invalid piece-kind/color
            letter, or invalid algebraic square).
    """

    fields = text.split(_TOP_LEVEL_SEP)
    if len(fields) != _TOP_LEVEL_FIELD_COUNT or fields[0] != _MESSAGE_MARKER:
        raise MalformedGameStateSnapshotWireFormatError(f"not a game-state-snapshot wire message: {text!r}")

    try:
        white_score = int(fields[1])
        black_score = int(fields[2])
        clock_ms = int(fields[3])
    except ValueError as exc:
        raise MalformedGameStateSnapshotWireFormatError(f"malformed score/clock field in {text!r}: {exc}") from None

    entries_text = fields[4]
    entries = tuple(_parse_entry(entry_text) for entry_text in entries_text.split(_ENTRY_SEP) if entry_text)

    score = ScoreSnapshot(score_by_color={Color.WHITE: white_score, Color.BLACK: black_score})
    log = MovesLogSnapshot(entries=entries)
    return score, log, clock_ms
