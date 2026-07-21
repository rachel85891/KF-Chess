"""Bugfix tests for PieceAnimator: a JumpLanded event for this
animator's own piece_id must force a transition from MOVE/JUMP to
IDLE, unconditionally - the exact same parallel gap
tests/unit/client/test_piece_animator_arrival_transition.py's own
PieceArrived fix already closed for ordinary moves, now closed for jump
landings too (see piece_animator.py's own updated module docstring,
"PARALLEL GAP - JUMP LANDINGS NEVER PUBLISHED PieceArrived AT ALL"
section, for the full reasoning).

NEW, SEPARATE test file (not an edit to test_piece_animator.py or
test_piece_animator_arrival_transition.py) - mirrors that file's own
"zero edits to pre-existing test files" precedent exactly, applied to
this parallel fix.

ROOT CAUSE THIS FIXES: a JUMP's own landing (extra/jump.py's
JumpTracker, resolved inside ExtraEngine.wait) never creates a Motion
and never fires PieceArrived at all - it publishes the distinct
JumpLanded event instead (added in the earlier jump-cooldown-core
stage). Before this fix, PieceAnimator had no reaction to JumpLanded
whatsoever - the only way out of JUMP was advance()'s own frame-
exhaustion branch, exactly the same independent-timing-source problem
test_piece_animator_arrival_transition.py's own PieceArrived fix
already solved for MOVE. A JUMP StateConfig with is_loop=True (frame-
exhaustion NEVER fires on its own, by advance()'s own logic) would
therefore get stuck in JUMP forever on a real landing, with or without
any timing drift.
"""

from __future__ import annotations

from pathlib import Path

from kungfu_chess.client.animation.animation_state import AnimationState
from kungfu_chess.client.animation.piece_animator import PieceAnimator
from kungfu_chess.client.animation.state_config import GraphicsConfig, PhysicsConfig, StateConfig
from kungfu_chess.client.events.game_events import JumpAccepted, JumpLanded
from kungfu_chess.model.position import Position


def _make_state_config(
    frame_count: int, frames_per_sec: int, is_loop: bool, next_state: AnimationState
) -> StateConfig:
    sprite_paths = tuple(Path(f"sprite_{i}.png") for i in range(frame_count))
    return StateConfig(
        physics=PhysicsConfig(speed_m_per_sec=1.0, next_state_when_finished=next_state),
        graphics=GraphicsConfig(frames_per_sec=frames_per_sec, is_loop=is_loop),
        sprite_paths=sprite_paths,
    )


def _all_states(overrides: dict[AnimationState, StateConfig] | None = None) -> dict[AnimationState, StateConfig]:
    defaults = {state: _make_state_config(1, 1, True, AnimationState.IDLE) for state in AnimationState}
    defaults.update(overrides or {})
    return defaults


def _jump_accepted(piece_id: int) -> JumpAccepted:
    return JumpAccepted(piece_id=piece_id, from_cell=Position(row=0, col=0), to_cell=Position(row=0, col=0), duration_ms=625)


def _jump_landed(piece_id: int) -> JumpLanded:
    return JumpLanded(piece_id=piece_id, cell=Position(row=0, col=0))


def test_jump_landed_forces_jump_to_idle_even_though_jump_is_a_looping_animation():
    # is_loop=True: frame-exhaustion NEVER fires for this state - the
    # exact same premise test_piece_animator_arrival_transition.py's
    # own MOVE test establishes, applied here to JUMP instead.
    states = _all_states({AnimationState.JUMP: _make_state_config(4, 10, True, AnimationState.IDLE)})
    animator = PieceAnimator(piece_id=1, states=states)
    animator.on_event(_jump_accepted(1))
    assert animator.current_state == AnimationState.JUMP

    # A generous amount of simulated time passes - frame-exhaustion
    # alone would still never trigger a transition here, by design.
    animator.advance(50_000)
    assert animator.current_state == AnimationState.JUMP  # confirms the premise: still stuck

    animator.on_event(_jump_landed(1))

    assert animator.current_state == AnimationState.IDLE
    assert animator.current_frame_index == 0
    assert animator.elapsed_ms_in_state == 0


def test_jump_landed_forces_jump_to_idle_even_with_zero_advance_calls():
    # A very long, non-looping frame count - frame-exhaustion would
    # eventually fire on its own given enough advance() calls, but
    # JumpLanded must force the transition immediately, without needing
    # advance() to ever be called at all.
    states = _all_states({AnimationState.JUMP: _make_state_config(10_000, 10, False, AnimationState.SHORT_REST)})
    animator = PieceAnimator(piece_id=1, states=states)
    animator.on_event(_jump_accepted(1))
    assert animator.current_state == AnimationState.JUMP

    animator.on_event(_jump_landed(1))

    assert animator.current_state == AnimationState.IDLE
    assert animator.current_frame_index == 0
    assert animator.elapsed_ms_in_state == 0


def test_jump_landed_for_a_different_piece_id_does_not_affect_this_animator():
    states = _all_states({AnimationState.JUMP: _make_state_config(4, 10, True, AnimationState.IDLE)})
    animator = PieceAnimator(piece_id=1, states=states)
    animator.on_event(_jump_accepted(1))
    assert animator.current_state == AnimationState.JUMP

    animator.on_event(_jump_landed(999))  # a different piece entirely

    assert animator.current_state == AnimationState.JUMP  # unaffected


def test_jump_landed_from_idle_or_rest_states_is_a_no_op():
    """The exact decision mirrored from PieceArrived's own fix:
    JumpLanded forces IDLE ONLY when current_state is actually MOVE or
    JUMP - it leaves SHORT_REST/LONG_REST (and IDLE itself) alone, for
    the identical "purely visual, no corresponding game event" reasoning
    piece_animator.py's own docstring already documents for
    PieceArrived."""

    states = _all_states({AnimationState.SHORT_REST: _make_state_config(5, 10, False, AnimationState.LONG_REST)})
    animator = PieceAnimator(piece_id=1, states=states)
    animator._transition_to(AnimationState.SHORT_REST)
    animator.advance(123)  # some real progress into the rest animation
    assert animator.current_state == AnimationState.SHORT_REST

    animator.on_event(_jump_landed(1))

    assert animator.current_state == AnimationState.SHORT_REST  # untouched
    assert animator.elapsed_ms_in_state == 123  # not reset either - no transition happened at all


def test_jump_landed_does_not_affect_a_piece_currently_in_move():
    """A defensive-symmetry check: JumpLanded forces IDLE from MOVE
    too (the same tuple check PieceArrived already uses), even though
    in practice a piece can never genuinely be both mid-MOVE and
    mid-JUMP at once (request_move/request_jump's own mutual-exclusion
    guards) - this only proves the transition logic itself treats
    MOVE and JUMP symmetrically, not a claim about a real reachable
    game state."""

    states = _all_states({AnimationState.MOVE: _make_state_config(4, 10, True, AnimationState.IDLE)})
    animator = PieceAnimator(piece_id=1, states=states)
    animator._transition_to(AnimationState.MOVE)

    animator.on_event(_jump_landed(1))

    assert animator.current_state == AnimationState.IDLE
