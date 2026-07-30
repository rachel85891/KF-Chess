"""board_delta_wire_format.py: bidirectional conversion between a real
BOARD_DELTA payload (a seq number plus a sparse map of changed cells)
and a single-line wire text - the G4 lean-wire-protocol stage's own
replacement for resending BoardPrinter's full board text on every
event. See server/application/game_server.py's own "STAGE G4" docstring
section for the full design this message belongs to.

WIRE SHAPE - "BOARD_DELTA:<seq>:<cell>:<token>,<cell>:<token>,...":
  - Top level (":", bounded to the first two occurrences via
    `split(":", 2)`) separates MESSAGE, seq, and the whole encoded
    cell-list as one trailing field - mirrors game_state_snapshot_wire_
    format.py's own "STATE" message shape (MESSAGE, then scalar fields,
    then one trailing variable-length field).
  - "," separates individual changed cells from each other within that
    trailing field.
  - ":" (reused at this second, unambiguous nesting level, exactly like
    game_state_snapshot_wire_format.py's own three-level shape) separates
    one cell's own square from its token.
None of these can ever appear inside a real field value: seq is plain
decimal digits, an algebraic square (position_to_algebraic) is always
exactly 2 characters from a-h/1-8, and a BoardPrinter token
(piece_to_token) is always exactly 2 characters (a color letter + a kind
letter) or the single "." empty marker - none contain ':' or ','.

REUSES, DOES NOT DUPLICATE: `position_to_algebraic`/`algebraic_to_
position` (kungfu_chess/notation/algebraic_notation.py) for the square
half, and `BoardPrinter.piece_to_token` for the FORMAT-direction token
half - see that method's own "STAGE G4" docstring section for why it was
made public for exactly this reuse. The PARSE direction deliberately
does NOT go through BoardParser: a BOARD_DELTA cell is occupancy only
(a bare (Color, PieceKind) tuple, or None for empty), never a real,
identity-bearing Piece object - constructing one here would hand out a
process-local Piece.id nothing should ever read, and would invite exactly
the kind of accidental piece-identity leakage kungfu_chess/client/loop/
network_game_loop_runner.py's own "PROBLEM 1"/"PROBLEM 2" docstring
sections already warn against. The parse direction instead builds the
tuple straight from the same two single-character enum values
BoardParser._token_to_piece already relies on (PieceKind(letter),
Color(letter)) - the identical primitives, not a second lookup table.

ONE ERROR TYPE for every malformed reason
(MalformedBoardDeltaWireFormatError), mirroring every other wire-format
module in this project's own established convention.
"""

from __future__ import annotations

from typing import Dict, Optional, Tuple

from kungfu_chess.io.board_printer import BoardPrinter
from kungfu_chess.model.board import Board
from kungfu_chess.model.color import Color
from kungfu_chess.model.piece import PieceKind
from kungfu_chess.model.position import Position
from kungfu_chess.notation.algebraic_notation import (
    InvalidSquareError,
    algebraic_to_position,
    position_to_algebraic,
)

BOARD_DELTA_MESSAGE_PREFIX = "BOARD_DELTA:"

_MESSAGE_MARKER = "BOARD_DELTA"
_TOP_LEVEL_SEP = ":"
_CELL_SEP = ","
_CELL_TOKEN_SEP = ":"
_EMPTY_TOKEN = "."
_TOP_LEVEL_SPLIT_LIMIT = 2  # MESSAGE, seq, cells-blob - see module docstring's "WIRE SHAPE" section.

BoardOccupancy = Dict[Position, Optional[Tuple[Color, PieceKind]]]

_board_printer = BoardPrinter()


class BoardDeltaWireFormatError(ValueError):
    """Base class for this module's own errors - mirrors every other
    wire-format module's own ValueError-subclassing convention."""


class MalformedBoardDeltaWireFormatError(BoardDeltaWireFormatError):
    """Raised by parse_board_delta for any text that isn't a valid
    BOARD_DELTA wire message."""


def board_to_occupancy(board: Board) -> BoardOccupancy:
    """Snapshot a real Board's own current occupancy into the plain
    BoardOccupancy shape this module's own format_board_delta/
    parse_board_delta and server/application/board_delta.py's own
    compute_board_delta all share - every cell on the board is given an
    explicit entry (None for empty), never a sparse/partial dict.

    LIVES HERE, NOT IN server/application/board_delta.py (where the
    diff itself, compute_board_delta, lives): this is a plain Board ->
    dict conversion with no opinion about matches, connections, or
    diffing - and, critically, BOTH the server (to compute
    match.last_board_snapshot's own next value) AND the CLIENT
    (kungfu_chess/client/loop/network_game_loop_runner.py, to (re)seed
    its own persistent occupancy-comparison grid from a full board-text
    broadcast) need it. A client must never import from server/ (see
    kungfu_chess/notation/algebraic_notation.py's own docstring for this
    project's established reasoning) - keeping this here, in
    kungfu_chess/notation/, alongside the wire format that already
    shares its exact data shape, is what lets both sides reuse the SAME
    function instead of each maintaining their own copy.

    Args:
        board: The real Board to snapshot.

    Returns:
        A fresh dict - a snapshot, never a live view; later board
        mutations never retroactively change an already-taken snapshot.
    """

    occupancy: BoardOccupancy = {}
    for row in range(board.height):
        for col in range(board.width):
            cell = Position(row=row, col=col)
            piece = board.piece_at(cell)
            occupancy[cell] = None if piece is None else (piece.color, piece.kind)
    return occupancy


def format_board_delta(seq: int, changed_cells: BoardOccupancy) -> str:
    """Format one BOARD_DELTA message - see module docstring's "WIRE
    SHAPE" section.

    Args:
        seq: This match's own current broadcast sequence number.
        changed_cells: Only the cells whose occupancy actually changed
            (e.g. server/application/board_delta.py's own
            compute_board_delta output) - may be empty, producing a
            valid (if pointless to actually send - see
            server/application/game_server.py's own "STAGE G4" docstring
            section for why `_broadcast_event` skips sending in that
            case) message with an empty trailing field.

    Returns:
        The single-line wire text. Cells are emitted in a deterministic
        (row, then column) order regardless of `changed_cells`'s own
        iteration order, so the same logical delta always produces
        byte-identical wire text.
    """

    ordered_cells = sorted(changed_cells.items(), key=lambda item: (item[0].row, item[0].col))
    cell_tokens = [
        f"{position_to_algebraic(cell)}{_CELL_TOKEN_SEP}{_token_for(value)}" for cell, value in ordered_cells
    ]
    return _TOP_LEVEL_SEP.join([_MESSAGE_MARKER, str(seq), _CELL_SEP.join(cell_tokens)])


def _token_for(value: Optional[Tuple[Color, PieceKind]]) -> str:
    if value is None:
        return _board_printer.piece_to_token(None)
    color, kind = value
    return color.value + kind.value


def parse_board_delta(text: str) -> Tuple[int, BoardOccupancy]:
    """Parse one raw BOARD_DELTA message back into (seq, changed_cells)
    - the exact inverse of format_board_delta.

    Args:
        text: The raw message text - a caller should already know this
            starts with BOARD_DELTA_MESSAGE_PREFIX (mirroring
            game_state_snapshot_wire_format.py's own
            STATE_SNAPSHOT_MESSAGE_PREFIX dispatch convention) via a
            plain `text.startswith(BOARD_DELTA_MESSAGE_PREFIX)` check
            before ever calling this function; guarded here too
            regardless.

    Returns:
        (seq, changed_cells) - changed_cells maps each changed Position
        to its new (Color, PieceKind) value, or None for now-empty.

    Raises:
        MalformedBoardDeltaWireFormatError: If `text` doesn't start with
            the "BOARD_DELTA" marker, has a non-integer seq field, or any
            cell/token pair within it is malformed.
    """

    fields = text.split(_TOP_LEVEL_SEP, _TOP_LEVEL_SPLIT_LIMIT)
    if len(fields) != _TOP_LEVEL_SPLIT_LIMIT + 1 or fields[0] != _MESSAGE_MARKER:
        raise MalformedBoardDeltaWireFormatError(f"not a board-delta wire message: {text!r}")

    try:
        seq = int(fields[1])
    except ValueError as exc:
        raise MalformedBoardDeltaWireFormatError(f"malformed seq field in {text!r}: {exc}") from None

    changed_cells: BoardOccupancy = {}
    cells_blob = fields[2]
    for cell_token_text in cells_blob.split(_CELL_SEP):
        if not cell_token_text:
            continue
        cell, value = _parse_cell_token(cell_token_text, text)
        changed_cells[cell] = value

    return seq, changed_cells


def _parse_cell_token(cell_token_text: str, original_text: str) -> Tuple[Position, Optional[Tuple[Color, PieceKind]]]:
    parts = cell_token_text.split(_CELL_TOKEN_SEP, 1)
    if len(parts) != 2:
        raise MalformedBoardDeltaWireFormatError(f"malformed cell entry {cell_token_text!r} in {original_text!r}")

    square_text, token_text = parts
    try:
        cell = algebraic_to_position(square_text)
    except InvalidSquareError as exc:
        raise MalformedBoardDeltaWireFormatError(f"malformed square in {original_text!r}: {exc}") from None

    if token_text == _EMPTY_TOKEN:
        return cell, None

    if len(token_text) != 2:
        raise MalformedBoardDeltaWireFormatError(f"malformed token {token_text!r} in {original_text!r}")

    try:
        value = (Color(token_text[0]), PieceKind(token_text[1]))
    except ValueError as exc:
        raise MalformedBoardDeltaWireFormatError(f"malformed token {token_text!r} in {original_text!r}: {exc}") from None

    return cell, value
