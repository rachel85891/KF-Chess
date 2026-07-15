"""PieceAnimator: per-piece animation state machine, per client_spec.md
§5. Design pattern: State Machine (per spec.md §4's pattern vocabulary
convention).

PieceAnimator is an Observer (Stage 3's single-method
kungfu_chess.client.events.event_publisher.Observer protocol) of
GameEventPublisher: it transitions directly into MOVE/JUMP upon
receiving the matching accepted-event for its own piece_id, rather
than polling "did this piece start moving" every frame (client_spec.md
§5). It does NOT subscribe itself anywhere - a future composition
root (GameLoopRunner) does that; this class only implements on_event.

Explicit non-dependencies (per spec.md §5's convention of stating
fields + what a class deliberately does NOT depend on):
- Does not load or construct StateConfig/AnimationState data itself -
  `states` is injected fully-built (Stage 4's load_piece_states), so
  PieceAnimator has no filesystem/JSON knowledge at all.
- Does not import, construct, or call GameEventPublisher or GameEngine
  - it only reacts to whatever event object on_event receives.
- Does not know about ImgSurface, cv2, or how/where a sprite is
  actually drawn - current_sprite_path() only exposes a Path.
- Holds no class-level or module-level mutable state: every field
  below is a per-instance attribute, set in __init__.

Fields (per spec.md §5's convention of stating fields for every
class):
- piece_id: int - identifies which Piece this animator tracks;
  on_event ignores any event for a different piece_id.
- states: dict[AnimationState, StateConfig] - the full 5-entry config
  set for this piece's <KIND><COLOR>, injected at construction.
- current_state: AnimationState - which of the 5 states is active now.
- elapsed_ms_in_state: int - logical time accumulated since the last
  transition into current_state (simulated time via advance(), never
  a real clock - matching RealTimeArbiter's own convention elsewhere
  in this codebase).
- current_frame_index: int - the sprite frame to display right now,
  recomputed from elapsed_ms_in_state on every advance() call (see
  advance()'s own docstring for why it is recomputed rather than
  incremented).
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict

from kungfu_chess.client.animation.animation_state import AnimationState
from kungfu_chess.client.animation.state_config import StateConfig
from kungfu_chess.client.events.game_events import JumpAccepted, MoveAccepted


class PieceAnimatorError(Exception):
    """Base class for all PieceAnimator errors, matching the same
    one-class-per-failure-mode convention as BoardError/StateConfigError/
    GameEventPublisherError/ScreenToImageMapperError elsewhere in this
    codebase: catchable via this one base, or via a specific subclass
    below."""


class IncompleteAnimationStatesError(PieceAnimatorError):
    """The `states` dict given to PieceAnimator's constructor does not
    contain all 5 AnimationState keys."""


class UnknownTransitionTargetError(PieceAnimatorError):
    """A transition (event-driven or via next_state_when_finished)
    points to an AnimationState absent from this instance's `states`
    dict."""


class InvalidAdvanceDurationError(PieceAnimatorError):
    """advance() was called with a negative delta_ms."""


class EmptyStateSpritesError(PieceAnimatorError):
    """One or more of the `states` dict's StateConfig entries has an
    empty sprite_paths tuple. Unlike UnknownTransitionTargetError's
    already-guarded, structurally-unreachable case, this one is a real
    possibility: Stage 4's _sprite_paths_for
    (kungfu_chess/client/animation/state_config.py) only guarantees
    the sprites/ directory exists, not that it is non-empty - a
    malformed asset set (an emptied-out sprites/ folder) would
    otherwise reach advance()'s modulo-by-frame_count or
    current_sprite_path()'s indexing and crash with a bare
    ZeroDivisionError/IndexError far from the actual bad data."""


class PieceAnimator:
    """Per-piece animation state machine: tracks which of the 5
    AnimationStates a single piece is currently displaying, advances
    its frame index over logical time, and reacts to MoveAccepted/
    JumpAccepted events for its own piece_id.
    """

    def __init__(
        self,
        piece_id: int,
        states: Dict[AnimationState, StateConfig],
        initial_state: AnimationState = AnimationState.IDLE,
    ) -> None:
        """Construct a PieceAnimator for one piece.

        Args:
            piece_id: The Piece.id (kungfu_chess/model/piece.py) this
                animator tracks. on_event ignores events carrying any
                other piece_id.
            states: The complete 5-entry {AnimationState: StateConfig}
                mapping for this piece's <KIND><COLOR> (built by Stage
                4's load_piece_states, or an equivalent hand-built
                dict in tests) - injected, never loaded here (see
                module docstring's non-dependencies).
            initial_state: Which AnimationState to start in.
                client_spec.md §5 does not state an explicit default,
                so AnimationState.IDLE is this constructor's own
                reasonable choice (a piece that hasn't moved yet is
                idle) rather than a spec-mandated value.

        Raises:
            IncompleteAnimationStatesError: If `states` is missing one
                or more of the 5 AnimationState keys - checked eagerly
                here (rather than failing later, mid-animation, the
                first time a missing state is actually needed) so a
                caller learns about a bad asset set immediately at
                construction, not at some arbitrary later frame.
            EmptyStateSpritesError: If any present StateConfig has an
                empty sprite_paths tuple - checked eagerly here for
                the same reason as IncompleteAnimationStatesError
                above, and specifically because Stage 4's
                _sprite_paths_for only guarantees the sprites/
                directory exists, not that it is non-empty, so this is
                a real, reachable malformed-asset case, not a
                theoretical one.
        """

        missing = [state for state in AnimationState if state not in states]
        if missing:
            missing_names = [state.value for state in missing]
            raise IncompleteAnimationStatesError(
                f"piece_id={piece_id}: states dict is missing required AnimationState(s) {missing_names}"
            )

        empty = [state for state in AnimationState if len(states[state].sprite_paths) == 0]
        if empty:
            empty_names = [state.value for state in empty]
            raise EmptyStateSpritesError(
                f"piece_id={piece_id}: states with empty sprite_paths {empty_names}"
            )

        self.piece_id = piece_id
        self.states = states
        self.current_state = initial_state
        self.elapsed_ms_in_state = 0
        self.current_frame_index = 0

    def _transition_to(self, target_state: AnimationState) -> None:
        """Switch current_state to target_state, resetting elapsed
        time and frame index to 0 for the new state.

        Args:
            target_state: The AnimationState to switch into.

        Returns:
            None.

        Raises:
            UnknownTransitionTargetError: If target_state is absent
                from self.states. Believed unreachable in practice:
                __init__'s IncompleteAnimationStatesError check
                already guarantees all 5 AnimationState members are
                present in self.states, and every caller of this
                method (on_event's MOVE/JUMP, advance()'s
                next_state_when_finished) only ever passes an
                AnimationState value - so target_state is always one
                of those same 5 members. Guarded anyway (rather than
                trusting the invariant silently) so a future bug that
                somehow violates it fails loudly with a named
                exception instead of a bare KeyError deep inside
                current_sprite_path() on some later frame.
        """

        if target_state not in self.states:
            raise UnknownTransitionTargetError(
                f"piece_id={self.piece_id}: transition target {target_state} is not in this animator's states"
            )

        self.current_state = target_state
        self.elapsed_ms_in_state = 0
        self.current_frame_index = 0

    def on_event(self, event: object) -> None:
        """Observer callback (Stage 3's Observer protocol): react to
        MoveAccepted/JumpAccepted events carrying this instance's own
        piece_id by transitioning into MOVE/JUMP; ignore everything
        else.

        Args:
            event: Any published client-layer event
                (kungfu_chess/client/events/game_events.py). Events
                for a different piece_id, and event types this
                animator has no reaction to (PieceArrived, GameOver,
                MoveRejected, MoveRequested, or any future type), are
                silently no-ops - not an error, just normal operation
                for an Observer that only cares about a subset of
                events (ISP, client_spec.md §6).

        Returns:
            None.
        """

        if getattr(event, "piece_id", None) != self.piece_id:
            return

        if isinstance(event, MoveAccepted):
            self._transition_to(AnimationState.MOVE)
        elif isinstance(event, JumpAccepted):
            self._transition_to(AnimationState.JUMP)

    def advance(self, delta_ms: int) -> None:
        """Advance this animator's logical clock by delta_ms, and
        recompute current_frame_index from the total elapsed time in
        the current state - or auto-transition to
        physics.next_state_when_finished if a non-looping state's
        frames are exhausted.

        Args:
            delta_ms: Milliseconds of logical time to advance (e.g.
                the game loop's measured frame delta, client_spec.md
                §4/§8). Must be >= 0.

        Returns:
            None.

        Raises:
            InvalidAdvanceDurationError: If delta_ms is negative.
            UnknownTransitionTargetError: See _transition_to.

        Frame index is recomputed from total elapsed_ms_in_state on
        every call (frames_elapsed = elapsed_ms_in_state *
        frames_per_sec / 1000), not incremented by a fixed amount per
        call - this is what makes it robust to variable-size deltas
        across calls (client_spec.md §5/§8's ~30 FPS loop does not
        guarantee a constant delta_ms), and is also what makes this
        method OCP-safe: it only ever reads the current StateConfig's
        own frames_per_sec/is_loop/next_state_when_finished/
        sprite_paths, with no branching on which specific
        AnimationState is active - a future 6th state needs zero
        changes here.

        A non-looping state's exhaustion transition discards any
        leftover time rather than carrying it into the new state (the
        new state always starts at elapsed_ms_in_state=0): chaining
        multiple transitions within one advance() call for a
        pathologically large delta_ms is not described anywhere in
        client_spec.md §5, and the ~30 FPS loop it recommends (§8)
        keeps delta_ms small in practice, so this only matters for
        contrived inputs, not normal operation.
        """

        if delta_ms < 0:
            raise InvalidAdvanceDurationError(
                f"piece_id={self.piece_id}: delta_ms must be >= 0, got {delta_ms}"
            )

        self.elapsed_ms_in_state += delta_ms

        config = self.states[self.current_state]
        frame_count = len(config.sprite_paths)
        frames_elapsed = int(self.elapsed_ms_in_state * config.graphics.frames_per_sec / 1000)

        if config.graphics.is_loop:
            self.current_frame_index = frames_elapsed % frame_count
            return

        if frames_elapsed >= frame_count:
            self._transition_to(config.physics.next_state_when_finished)
            return

        self.current_frame_index = frames_elapsed

    def current_sprite_path(self) -> Path:
        """Return the sprite image Path for the current state and
        frame index - a pure, read-only lookup with no side effects.

        Returns:
            The Path at self.states[self.current_state].sprite_paths[
            self.current_frame_index]. This class has no knowledge of
            how/where that Path is actually drawn (see module
            docstring's non-dependencies) - a future ImgSurface/
            AssetCache is responsible for turning it into pixels.
        """

        return self.states[self.current_state].sprite_paths[self.current_frame_index]
