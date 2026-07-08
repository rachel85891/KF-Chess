"""MoveResolver: what happens when a scheduled move or jump-landing
becomes due, plus the instant-royal-capture shortcut requested straight
from a click. Mutates the board and publishes domain events; never
decides who wins or when a pawn promotes - that's WinCondition's and
PromotionService's job, reacting to the events published here.
"""

from kungfu_chess.domain.board import Board
from kungfu_chess.domain.events import PieceCaptured, PieceIntercepted, PieceMoved
from kungfu_chess.domain.piece import Piece
from kungfu_chess.services.event_bus import EventBus
from kungfu_chess.services.move_legality_service import is_move_allowed
from kungfu_chess.services.move_scheduler import MoveScheduler, ScheduledLanding, ScheduledMove

Cell = tuple[int, int]


def resolve_move(move: ScheduledMove, board: Board, scheduler: MoveScheduler, event_bus: EventBus) -> None:
    if not is_move_allowed(board, move.from_cell, move.to_cell):
        # The board changed since this move was requested and it is no
        # longer legal - it fails silently, the piece stays put.
        return

    if scheduler.is_airborne(*move.to_cell):
        # Air capture: the destination piece is currently jumping and
        # defends itself by simply not being "landed" yet - the
        # ARRIVING piece is destroyed instead. The airborne defender is
        # untouched and stays marked airborne until its own landing.
        # Deliberately does not publish PieceCaptured/PieceMoved: the
        # original engine never treats this as a win-ending capture
        # (even if the arriving piece was a king) and never promotes
        # the arriving piece, so no listener should react to it either.
        board.set_piece(*move.from_cell, None)
        return

    captured = board.get_piece(*move.to_cell)
    board.set_piece(*move.to_cell, move.piece)
    board.set_piece(*move.from_cell, None)

    if captured is not None:
        event_bus.publish(PieceCaptured(cell=move.to_cell, captured_piece=captured, capturing_piece=move.piece))

    event_bus.publish(PieceMoved(from_cell=move.from_cell, to_cell=move.to_cell, piece=move.piece))


def resolve_landing(landing: ScheduledLanding, board: Board, scheduler: MoveScheduler, event_bus: EventBus) -> None:
    for move in scheduler.pending_moves():
        attacked_while_airborne = (
            move.to_cell == landing.cell
            and move.piece.color != landing.piece.color
            and move.requested_at >= landing.start_time
        )
        if attacked_while_airborne:
            board.set_piece(*move.from_cell, None)
            scheduler.remove_move(move)
            event_bus.publish(
                PieceIntercepted(origin_cell=move.from_cell, attacker_piece=move.piece, defender_cell=landing.cell)
            )
            break  # only one attacker can be intercepted per landing

    scheduler.remove_landing(landing)


def resolve_due_events(scheduler: MoveScheduler, board: Board, clock_ms: int, event_bus: EventBus) -> None:
    """Settle everything due at clock_ms, in the scheduler's exact
    tie-break order. A move due at the same instant a landing is
    processed may already have been consumed by that landing's
    interception (see resolve_landing) - has_move guards against
    double-processing a move that is no longer pending."""
    for kind, obj in scheduler.due_events(clock_ms):
        if kind == "land":
            resolve_landing(obj, board, scheduler, event_bus)
        elif scheduler.has_move(obj):
            resolve_move(obj, board, scheduler, event_bus)
            scheduler.remove_move(obj)


def resolve_instant_royal_capture(mover: Piece, from_cell: Cell, to_cell: Cell, board: Board, event_bus: EventBus) -> None:
    """Capturing a royal piece bypasses scheduling entirely - no transit
    delay, direct board mutation. Deliberately does not publish
    PieceMoved (so PromotionService never sees it): the original engine
    never promotes on an instant capture, even if the mover lands on
    what would be its promotion row.
    """
    captured = board.get_piece(*to_cell)
    board.set_piece(*to_cell, mover)
    board.set_piece(*from_cell, None)

    if captured is not None:
        event_bus.publish(PieceCaptured(cell=to_cell, captured_piece=captured, capturing_piece=mover))
