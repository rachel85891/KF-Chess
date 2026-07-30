"""board_delta.py: pure, independently-testable helpers behind the G4
lean-wire-protocol stage's own BOARD_DELTA message - mirrors
elo_rating.py's own "pure, in-memory, no I/O, no GameServer/GameSession
knowledge" convention (see that module's own docstring for the precedent
this follows): every function here is a plain function of plain data,
independently unit-testable without a running server or a real
websockets connection.

OCCUPANCY SHAPE - Dict[Position, Optional[Tuple[Color, PieceKind]]]:
`None` means "this cell is empty", kept as an explicit value rather than
simply an absent key, since a diff must be able to represent "a piece
that used to be here is now gone" as a real, present change - not merely
a key that stopped existing (both `previous` and `current`, as built by
`board_to_occupancy`, always carry every cell on the board, occupied or
not, so a missing key never has to be special-cased by
`compute_board_delta` itself - `.get(cell)` still defaults to None for
the one caller that legitimately starts from an empty dict, a brand-new
`_Match.last_board_snapshot` before it has ever been seeded).

WHY A SEPARATE MODULE, NOT A METHOD ON _Match/GameServer: see
server/application/game_server.py's own "STAGE G4" docstring section for
the full reasoning behind this stage's two-different-delta-strategies
design - the short version is that this diff is a pure function of two
occupancy snapshots, with no opinion about matches, connections, or the
wire format BOARD_DELTA itself uses (that formatting lives in
server/presentation/protocol_handler.py, per this project's own
established PRESENTATION/APPLICATION split) - keeping it here, separate
from both, makes it testable in complete isolation, exactly like
elo_rating.py's own compute_new_ratings.

`BoardOccupancy`/`board_to_occupancy` THEMSELVES LIVE IN
kungfu_chess/notation/board_delta_wire_format.py, NOT HERE, AND ARE
RE-EXPORTED BELOW FOR CONVENIENCE: both the server (this module's own
`compute_board_delta`) and the CLIENT (kungfu_chess/client/loop/
network_game_loop_runner.py, which must never import from server/ - see
that shared module's own docstring) need the identical Board -> dict
conversion; only `compute_board_delta` itself - the diff, never called
client-side - is genuinely server-only.
"""

from __future__ import annotations

from kungfu_chess.notation.board_delta_wire_format import BoardOccupancy, board_to_occupancy

__all__ = ["BoardOccupancy", "board_to_occupancy", "compute_board_delta"]


def compute_board_delta(previous: BoardOccupancy, current: BoardOccupancy) -> BoardOccupancy:
    """The minimal set of cells whose occupancy differs between
    `previous` and `current` - the BOARD_DELTA payload's own real
    content, computed as a pure function of the two snapshots.

    Args:
        previous: The last occupancy the recipient is already assumed to
            know (e.g. `_Match.last_board_snapshot`) - may be a partial
            or empty dict (a cell absent here is treated identically to
            one explicitly mapped to None).
        current: The real, current occupancy (e.g. freshly built via
            `board_to_occupancy`).

    Returns:
        A dict containing ONLY the cells whose value actually changed,
        each mapped to its NEW value from `current` - empty if nothing
        changed at all (see server/application/game_server.py's own
        "STAGE G4" docstring section for why an empty result means
        `_broadcast_event` skips sending BOARD_DELTA entirely for that
        event, a deliberate, documented decision, not an oversight).
    """

    changed: BoardOccupancy = {}
    for cell in previous.keys() | current.keys():
        if previous.get(cell) != current.get(cell):
            changed[cell] = current.get(cell)
    return changed
