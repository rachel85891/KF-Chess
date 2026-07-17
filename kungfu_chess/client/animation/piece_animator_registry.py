"""PieceAnimatorRegistry: builds one PieceAnimator per piece on a
Board, and routes events to the right one by piece_id. Design
patterns: Observer (implements Stage 3's single-method Observer
protocol itself, per client_spec.md §6) + Registry (a piece_id ->
PieceAnimator lookup, per spec.md §4's pattern-vocabulary convention).

SRP: this class only builds and routes to PieceAnimators - it does not
decide animation timing/transition rules itself (that stays entirely
PieceAnimator's job; on_event/advance_all only forward calls), and it
does not draw anything (that's a future ImgSurface consumer's job,
Stage 10b, via animator_for().current_sprite_path()).

OCP: on_event's routing only asks "does this event have a piece_id,
and do I hold an animator for it" - it never branches on event TYPE or
AnimationState. A future 6th event type or 6th AnimationState needs
zero changes here.

DIP: from_board takes a Board (an existing abstraction); on_event/
advance_all/animator_for depend only on PieceAnimator's own public
interface (on_event, advance, current_sprite_path) - never on
GameEngine, GameEventPublisher, or ImgSurface.

WHY a SEPARATE per-combo StateConfig cache from ImgSurface's own
(rather than sharing one): these are two independent consumers of
Stage 4's load_piece_states with two different lifecycles - this
registry builds its cache once, at game start, from a fixed Board;
ImgSurface builds its cache lazily, per draw call, from a stream of
PieceSnapshots. Sharing one literal cache object between them would
force whoever constructs both to also wire a shared mutable resource
between two classes that otherwise have no relationship to each other
- an unwanted coupling for a modest one-time-per-combo saving. Reusing
ImgSurface's _kind_color_key/_idle_sprite_path directly isn't an
option anyway (they're private to that class) - the same small caching
PATTERN is independently reimplemented here, not the same cache
INSTANCE or code.

WHY captured pieces' PieceAnimators are kept, never removed: this
registry has no authority to decide a piece is "gone forever" just
because a PieceArrived happened to carry its id as captured_piece_id -
that decision (removing it from the board) already happened in
Board.remove_piece before the event was even published; this class
would be duplicating/second-guessing that authority if it also started
deleting entries based on inferring meaning from event fields. Kept
entries also mean a captured piece's animator is still there to
provide a final frame if a future consumer wants to render one (e.g. a
capture/fade animation), and any later stray event referencing that id
remains a normal, safe no-op rather than becoming a KeyError trap.
"""

from __future__ import annotations

from typing import Dict

from kungfu_chess.client.animation.animation_state import AnimationState
from kungfu_chess.client.animation.piece_animator import PieceAnimator
from kungfu_chess.client.animation.state_config import PIECES_ROOT, StateConfig, load_piece_states
from kungfu_chess.model.board import Board
from kungfu_chess.model.position import Position


class PieceAnimatorRegistryError(Exception):
    """Base class for PieceAnimatorRegistry errors, matching the same
    one-class-per-failure-mode convention used throughout this
    codebase."""


class UnknownPieceIdError(PieceAnimatorRegistryError):
    """animator_for() was asked about a piece_id this registry never
    built a PieceAnimator for.

    Deliberately a distinct type from Stage 8's
    kungfu_chess.client.events.piece_registry.PieceRegistry's own,
    identically-named UnknownPieceIdError, not a reuse of it: the two
    registries are unrelated (different data, different exception
    base, different callers), and their failures mean different things
    - "no kind/color known for this id" there, vs. "no PieceAnimator
    built for this id" here. Catching one specific type must not be
    ambiguous about which registry actually failed, which sharing one
    class across both would make it - a caller would have to inspect
    the message text to tell them apart, defeating the point of a
    named exception in the first place.
    """


class PieceAnimatorRegistry:
    def __init__(self, animators_by_id: Dict[int, PieceAnimator]) -> None:
        """Wrap an already-built id -> PieceAnimator mapping. Most
        callers should use from_board() instead - exposed mainly for
        tests that want precise, hand-built control over exactly which
        animators exist."""

        self._animators_by_id = animators_by_id

    @classmethod
    def from_board(cls, board: Board) -> "PieceAnimatorRegistry":
        """Build one PieceAnimator per piece currently on `board`.

        Args:
            board: The Board to enumerate. Walked via board.piece_at
                over every (row, col) - the same enumeration idiom
                Stage 8's PieceRegistry.from_board already uses, so
                this doesn't invent a second way to walk a Board.

        Returns:
            A new PieceAnimatorRegistry holding one PieceAnimator per
            piece found, keyed by piece.id. Pieces sharing a
            kind+color combo share the same underlying
            Dict[AnimationState, StateConfig] instance (loaded once
            per combo, not once per piece) - see module docstring for
            why this cache is independent of ImgSurface's own.

        Raises:
            A StateConfigError subclass (kungfu_chess.client.animation.
            state_config): propagated as-is, unwrapped, if a piece's
            kind+color combo has no usable assets/pieces/<KIND><COLOR>
            data. Unlike ImgSurface (which pre-checks the directory's
            existence and raises its own UnknownPieceAssetError, since
            it processes a continuous stream of arbitrary
            PieceSnapshots where an unknown combo is a normal,
            expected condition), from_board runs once against a fixed,
            known Board - a piece here needing assets that don't exist
            among the 12 vendored combos is a vendoring/deployment bug,
            and Stage 4's own exception (e.g. ConfigFileNotFoundError)
            already names the exact missing path precisely; wrapping
            it would only obscure that actionable detail.
        """

        states_cache: Dict[str, Dict[AnimationState, StateConfig]] = {}
        animators_by_id: Dict[int, PieceAnimator] = {}

        for row in range(board.height):
            for col in range(board.width):
                piece = board.piece_at(Position(row=row, col=col))
                if piece is None:
                    continue

                key = f"{piece.kind.value}{piece.color.value.upper()}"
                if key not in states_cache:
                    states_cache[key] = load_piece_states(PIECES_ROOT / key)

                animators_by_id[piece.id] = PieceAnimator(piece_id=piece.id, states=states_cache[key])

        return cls(animators_by_id)

    def on_event(self, event: object) -> None:
        """Observer callback: forward `event` to the ONE PieceAnimator
        whose piece_id matches, never to all of them - routing is this
        registry's entire job, reimplementing PieceAnimator's own
        transition logic here would duplicate it in exactly the way
        SRP says not to.

        Args:
            event: Any published client-layer event
                (kungfu_chess/client/events/game_events.py).

        Returns:
            None.

        Two cases are both safe, silent no-ops, not errors: an event
        with no piece_id field at all (MoveRejected, GameOver - re-
        checked directly against game_events.py, neither carries one),
        and an event whose piece_id this registry never built an
        animator for (e.g. this event belongs to a piece that was
        never on the Board this registry was snapshotted from - a
        normal condition, not a data-integrity problem the way Stage
        8's registry treats an unknown id, since nothing here promises
        completeness the way that registry's board snapshot does).
        """

        piece_id = getattr(event, "piece_id", None)
        if piece_id is None:
            return

        animator = self._animators_by_id.get(piece_id)
        if animator is None:
            return

        animator.on_event(event)

    def advance_all(self, delta_ms: int) -> None:
        """Advance every held PieceAnimator by delta_ms.

        Args:
            delta_ms: Milliseconds of logical time to advance,
                forwarded as-is to each PieceAnimator.advance().

        Returns:
            None.

        Order does NOT affect correctness here (confirmed by re-
        reading PieceAnimator.advance: it only ever reads/mutates its
        own instance fields - elapsed_ms_in_state, current_state,
        current_frame_index - and its states dict is read-only from
        advance()'s perspective; nothing about advancing one
        PieceAnimator can influence another's outcome). Iteration is
        still done in a fixed, stable order (sorted by piece_id) purely
        for deterministic, reproducible test/debug behavior across
        runs - not because correctness requires it, unlike Stage 3's
        EventOrderingPolicy, where processing order genuinely can
        change which piece "wins" a same-tick conflict.
        """

        for piece_id in sorted(self._animators_by_id):
            self._animators_by_id[piece_id].advance(delta_ms)

    def animator_for(self, piece_id: int) -> PieceAnimator:
        """Look up the PieceAnimator for a specific piece - the query
        a future ImgSurface (Stage 10b) uses to get a live
        current_sprite_path() per piece, replacing the static idle-
        sprite lookup ImgSurface currently falls back to.

        Args:
            piece_id: The Piece.id to look up.

        Returns:
            That piece's PieceAnimator - including for a captured
            piece (see module docstring for why captured pieces'
            animators are never removed).

        Raises:
            UnknownPieceIdError: If piece_id was never built into this
                registry (see this class's own docstring for why this
                is a distinct type from Stage 8's PieceRegistry's
                identically-named exception).
        """

        try:
            return self._animators_by_id[piece_id]
        except KeyError as exc:
            raise UnknownPieceIdError(f"piece_id={piece_id} has no PieceAnimator in this registry") from exc
