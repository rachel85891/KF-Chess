"""JumpTracker: JUMP as an optional extra, per spec.md §2. Sourced from
the legacy kungfu_chess/services/{game_engine,move_scheduler,
move_resolver}.py's handle_jump/schedule_landing/is_airborne/
resolve_landing/resolve_move semantics, reimplemented against model
types: a piece becomes airborne AT ITS OWN CELL for a fixed duration -
it never moves. If an enemy motion targets that cell while the piece
is airborne, the ATTACKER is destroyed instead of landing (a parry,
not a movement variant).

Kept entirely independent of the core "one motion system-wide" rule
(spec.md §2): an active jump never blocks GameEngine.request_move, and
an active core motion never blocks a jump request - RealTimeArbiter's
_motions and this tracker's airborne registry are two unrelated
collections. Mixing them would re-entangle exactly the complexity
spec.md §2 defers by calling this an independent "additional optional"
rule rather than a variant of the core movement model.

Piece.state is deliberately left untouched by a jump (stays IDLE) -
"airborne" isn't one of spec.md §5.2's three states, and nothing about
this mechanic functionally requires the core Piece.state to reflect
it; airborne-ness lives only in this tracker's own registry. This
keeps model/piece.py completely unmodified.

Interception must be checked when the JUMP's own duration elapses, not
only when the attacker's motion would otherwise arrive - the legacy
resolve_landing cancels an already-in-flight attacker the moment the
jump resolves, regardless of how much travel time that attacker has
left. Reproducing this required one small additive hook on
RealTimeArbiter, cancel_motion(motion) - see its docstring for why it
was unavoidable; nothing else about RealTimeArbiter's timing/
resolution logic changed.
"""

from __future__ import annotations

from dataclasses import dataclass

from kungfu_chess.model.board import Board
from kungfu_chess.model.piece import Piece, PieceState
from kungfu_chess.model.position import Position
from kungfu_chess.realtime.real_time_arbiter import MS_PER_SQUARE, RealTimeArbiter

JUMP_DURATION_MS = MS_PER_SQUARE


@dataclass(frozen=True)
class _AirborneEntry:
    piece: Piece
    start_time: int
    land_time: int


@dataclass(frozen=True)
class InterceptionEvent:
    attacker: Piece
    defender: Piece
    cell: Position


class JumpTracker:
    def __init__(self):
        self._airborne: dict[int, _AirborneEntry] = {}

    def is_airborne(self, piece_id: int) -> bool:
        return piece_id in self._airborne

    def start_jump(self, piece: Piece, clock_ms: int) -> None:
        self._airborne[piece.id] = _AirborneEntry(
            piece=piece, start_time=clock_ms, land_time=clock_ms + JUMP_DURATION_MS
        )

    def resolve_due(self, clock_ms: int, arbiter: RealTimeArbiter, board: Board) -> list[InterceptionEvent]:
        events: list[InterceptionEvent] = []

        for piece_id, entry in list(self._airborne.items()):
            if entry.land_time > clock_ms:
                continue

            attacking_motion = next(
                (
                    motion
                    for motion in arbiter.active_motions()
                    if motion.destination == entry.piece.cell
                    and motion.piece.color != entry.piece.color
                    and motion.start_time >= entry.start_time
                ),
                None,
            )

            if attacking_motion is not None:
                arbiter.cancel_motion(attacking_motion)
                board.remove_piece(attacking_motion.piece.cell)
                attacking_motion.piece.state = PieceState.CAPTURED
                events.append(
                    InterceptionEvent(attacker=attacking_motion.piece, defender=entry.piece, cell=entry.piece.cell)
                )

            del self._airborne[piece_id]

        return events
