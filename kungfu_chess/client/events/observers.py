"""ScoreObserver, MovesLogObserver: Observer protocol implementations
(kungfu_chess/client/events/event_publisher.py's Observer, Stage 3),
per client_spec.md §6.

Both take a PieceRegistry via constructor injection (DIP) rather than
constructing one or reaching into Board/GameEngine themselves - the
registry is the one thing both need to turn a bare piece_id back into
a kind/color, and building one is a wiring-root concern (client_spec.md
§3: GameLoopRunner is "the only high-level component that knows all
the others"), not something either Observer should do on its own.

Both match on the specific event types they care about and silently
ignore everything else (isinstance checks, no exhaustive if/elif/else)
rather than branching over every possible event type - a future 6th
event type neither Observer has any reason to react to therefore needs
zero changes here (OCP).

Neither wraps UnknownPieceIdError raised by PieceRegistry.info_for: a
piece_id an event references but the registry never saw is a genuine
data-integrity bug upstream (the registry's whole premise - a complete
snapshot of every piece that will ever appear in an event - would be
violated), not a normal condition either Observer should quietly
handle. Letting the registry's own specific, already-named exception
propagate as-is surfaces that loudly at the real point of failure,
rather than hiding it behind a second, less-informative wrapper type.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple, Union

from kungfu_chess.client.events.game_events import JumpAccepted, MoveAccepted, PieceArrived
from kungfu_chess.client.events.piece_registry import PieceRegistry
from kungfu_chess.client.ui.score_table import PIECE_VALUES
from kungfu_chess.model.color import Color
from kungfu_chess.model.piece import PieceKind
from kungfu_chess.model.position import Position


@dataclass(frozen=True)
class ScoreSnapshot:
    """Read-only point-in-time copy of ScoreObserver's running totals
    - see ScoreObserver.snapshot() for why this is a copy, not a live
    view."""

    score_by_color: Dict[Color, int]


class ScoreObserver:
    def __init__(self, registry: PieceRegistry) -> None:
        """Score starts at 0-0 for both colors (not "absent until a
        first capture") so snapshot() always has a well-defined value
        for both colors from the very first frame, with nothing extra
        for a HudRenderer to special-case."""

        self._registry = registry
        self._score_by_color: Dict[Color, int] = {Color.WHITE: 0, Color.BLACK: 0}

    def on_event(self, event: object) -> None:
        """Only a PieceArrived carrying a real capture affects score -
        every other event (including a capture-less PieceArrived) is a
        no-op."""

        if isinstance(event, PieceArrived) and event.captured_piece_id is not None:
            self._apply_capture(event.captured_piece_id)

    def _apply_capture(self, captured_piece_id: int) -> None:
        """The CAPTURED piece's color loses nothing here (this class
        tracks points scored, not material remaining) - the OPPONENT
        of that color gains the captured piece's value, per standard
        chess scoring: your score is the sum of your opponent's piece
        values you have captured, not your own remaining material."""

        captured_info = self._registry.info_for(captured_piece_id)
        capturing_color = captured_info.color.opposite
        self._score_by_color[capturing_color] += PIECE_VALUES[captured_info.kind]

    def snapshot(self) -> ScoreSnapshot:
        """Returns a copy of the internal score dict, not the dict
        itself - a caller mutating the returned mapping must not be
        able to corrupt this Observer's own running total (the same
        read-only-snapshot guarantee GameSnapshot/StateConfig etc.
        already give elsewhere in this codebase)."""

        return ScoreSnapshot(score_by_color=dict(self._score_by_color))


@dataclass(frozen=True)
class MoveLogEntry:
    """One MoveAccepted/JumpAccepted."""

    piece_kind: PieceKind
    piece_color: Color
    from_cell: Position
    to_cell: Position
    is_jump: bool


@dataclass(frozen=True)
class CaptureLogEntry:
    """One PieceArrived that included a capture.

    A separate entry type, appended to the same log, rather than
    updating the MoveLogEntry that started the motion: a move is
    accepted at one moment, and whether it results in a capture is
    only known later, at arrival - often well after real travel time
    (duration_ms) - so these are genuinely two separate events in
    time, not one record with a field filled in belatedly. Log entries
    are also frozen (matching every other snapshot type in this
    codebase), so "updating" one in place isn't actually an option
    without replacing it in the log by index - appending a second,
    clearly-ordered entry for what is a second real event is simpler
    and just as informative when read as a chronological log.
    """

    piece_kind: PieceKind
    piece_color: Color
    cell: Position
    captured_piece_kind: PieceKind
    captured_piece_color: Color


MovesLogEntry = Union[MoveLogEntry, CaptureLogEntry]


@dataclass(frozen=True)
class MovesLogSnapshot:
    """Read-only point-in-time copy of MovesLogObserver's log - see
    MovesLogObserver.snapshot() for why this is a tuple copy, not a
    live view."""

    entries: Tuple[MovesLogEntry, ...]


class MovesLogObserver:
    def __init__(self, registry: PieceRegistry) -> None:
        """registry is injected (DIP), for the same reason as
        ScoreObserver.__init__ - see this module's own docstring."""

        self._registry = registry
        self._entries: List[MovesLogEntry] = []

    def on_event(self, event: object) -> None:
        """MoveRejected/GameOver are deliberately ignored: client_spec.md
        §6 does not describe this Observer reacting to either, and a
        rejected move never actually happened (nothing moved, nothing
        was captured) - there is nothing for a MOVE log to record."""

        if isinstance(event, (MoveAccepted, JumpAccepted)):
            self._record_move(event)
        elif isinstance(event, PieceArrived) and event.captured_piece_id is not None:
            self._record_capture(event)

    def _record_move(self, event: Union[MoveAccepted, JumpAccepted]) -> None:
        """Builds one MoveLogEntry from a MoveAccepted or JumpAccepted
        - is_jump distinguishes the two using isinstance rather than a
        separate method per event type, since the resulting entry
        shape is otherwise identical."""

        info = self._registry.info_for(event.piece_id)
        self._entries.append(
            MoveLogEntry(
                piece_kind=info.kind,
                piece_color=info.color,
                from_cell=event.from_cell,
                to_cell=event.to_cell,
                is_jump=isinstance(event, JumpAccepted),
            )
        )

    def _record_capture(self, event: PieceArrived) -> None:
        """Builds one CaptureLogEntry - see CaptureLogEntry's own
        docstring for why this is a separate entry, not an update to
        the move that started the motion."""

        mover_info = self._registry.info_for(event.piece_id)
        captured_info = self._registry.info_for(event.captured_piece_id)
        self._entries.append(
            CaptureLogEntry(
                piece_kind=mover_info.kind,
                piece_color=mover_info.color,
                cell=event.cell,
                captured_piece_kind=captured_info.kind,
                captured_piece_color=captured_info.color,
            )
        )

    def snapshot(self) -> MovesLogSnapshot:
        """A tuple, not the live list - same read-only-copy guarantee
        as ScoreObserver.snapshot()."""

        return MovesLogSnapshot(entries=tuple(self._entries))
