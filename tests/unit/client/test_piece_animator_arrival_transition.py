"""Bugfix tests for PieceAnimator: a PieceArrived event for this
animator's own piece_id must force a transition from MOVE/JUMP to
IDLE, unconditionally - the real game engine's own authoritative
signal that a motion has finished, which must always override
whatever the animation's own independent frame-timing happens to be
doing at that moment.

NEW, SEPARATE test file (not an edit to the existing
tests/unit/client/test_piece_animator.py) - per this fix's own
requirement of zero edits to pre-existing test files. That existing
file's own test_irrelevant_event_types_for_own_piece_id_are_ignored
sends a PieceArrived to an animator that is still in its initial IDLE
state and asserts it stays IDLE - that assertion is STILL correct and
unmodified after this fix (see this file's own
test_piece_arrived_from_idle_or_rest_states_is_a_no_op below for why:
IDLE is one of the states this fix deliberately does NOT force a
transition FROM), even though that test's own name ("irrelevant event
types... are ignored") is now slightly imprecise - PieceArrived is no
longer irrelevant to this class in general, only when the current
state isn't MOVE/JUMP. Left as-is per the "zero edits" requirement;
noted here instead.

ROOT CAUSE THIS FIXES (see piece_animator.py's own updated module
docstring for the full reasoning): PieceAnimator previously had NO
reaction to PieceArrived at all - the only way out of MOVE/JUMP was
advance()'s own frame-exhaustion branch, an independent timing source
from the real motion's actual duration_ms. Confirmed via the real
vendored assets (assets/pieces/RW/states/move/config.json) that MOVE
is configured with is_loop=true - a looping state NEVER exhausts on
its own (see PieceAnimator.advance's own is_loop branch, which returns
before ever checking frame count against next_state_when_finished) -
so, prior to this fix, a piece's MOVE animation given the REAL
vendored assets could never end at all without this fix; this was not
a rare edge case.
"""

from __future__ import annotations

from pathlib import Path

from kungfu_chess.client.animation.animation_state import AnimationState
from kungfu_chess.client.animation.piece_animator import PieceAnimator
from kungfu_chess.client.animation.state_config import GraphicsConfig, PhysicsConfig, StateConfig
from kungfu_chess.client.events.game_events import JumpAccepted, MoveAccepted, PieceArrived
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


def _move_accepted(piece_id: int) -> MoveAccepted:
    return MoveAccepted(piece_id=piece_id, from_cell=Position(row=0, col=0), to_cell=Position(row=0, col=1), duration_ms=1000)


def _jump_accepted(piece_id: int) -> JumpAccepted:
    return JumpAccepted(piece_id=piece_id, from_cell=Position(row=0, col=0), to_cell=Position(row=0, col=0), duration_ms=625)


def _piece_arrived(piece_id: int) -> PieceArrived:
    return PieceArrived(piece_id=piece_id, cell=Position(row=0, col=1), captured_piece_id=None)


def test_piece_arrived_forces_move_to_idle_even_though_move_is_a_looping_animation():
    # is_loop=True: frame-exhaustion NEVER fires for this state (per
    # advance()'s own logic, re-verified directly) - the exact real
    # configuration assets/pieces/RW/states/move/config.json actually
    # uses. Before this fix, an animator stuck here would NEVER leave
    # MOVE on its own, no matter how much time advanced.
    states = _all_states({AnimationState.MOVE: _make_state_config(4, 10, True, AnimationState.IDLE)})
    animator = PieceAnimator(piece_id=1, states=states)
    animator.on_event(_move_accepted(1))
    assert animator.current_state == AnimationState.MOVE

    # A generous amount of simulated time passes - frame-exhaustion
    # alone would still never trigger a transition here, by design.
    animator.advance(50_000)
    assert animator.current_state == AnimationState.MOVE  # confirms the premise: still stuck

    animator.on_event(_piece_arrived(1))

    assert animator.current_state == AnimationState.IDLE
    assert animator.current_frame_index == 0
    assert animator.elapsed_ms_in_state == 0


def test_piece_arrived_forces_jump_to_idle_even_with_zero_advance_calls():
    # A very long, non-looping frame count - frame-exhaustion would
    # eventually fire on its own given enough advance() calls, but
    # PieceArrived must force the transition immediately, without
    # needing advance() to ever be called at all.
    states = _all_states({AnimationState.JUMP: _make_state_config(10_000, 10, False, AnimationState.SHORT_REST)})
    animator = PieceAnimator(piece_id=1, states=states)
    animator.on_event(_jump_accepted(1))
    assert animator.current_state == AnimationState.JUMP

    animator.on_event(_piece_arrived(1))

    assert animator.current_state == AnimationState.IDLE
    assert animator.current_frame_index == 0
    assert animator.elapsed_ms_in_state == 0


def test_piece_arrived_for_a_different_piece_id_does_not_affect_this_animator():
    states = _all_states({AnimationState.MOVE: _make_state_config(4, 10, True, AnimationState.IDLE)})
    animator = PieceAnimator(piece_id=1, states=states)
    animator.on_event(_move_accepted(1))
    assert animator.current_state == AnimationState.MOVE

    animator.on_event(_piece_arrived(999))  # a different piece entirely

    assert animator.current_state == AnimationState.MOVE  # unaffected


def test_piece_arrived_from_idle_or_rest_states_is_a_no_op():
    """The exact decision for requirement 3: PieceArrived forces IDLE
    ONLY when current_state is actually MOVE or JUMP - it leaves
    SHORT_REST/LONG_REST (and IDLE itself) alone. See
    piece_animator.py's own updated docstring for the full
    client_spec.md §5 / real-asset-config reasoning: SHORT_REST/
    LONG_REST are purely visual post-landing recovery states with no
    corresponding "it's over" game event of their own (the same
    category the fix's own requirements explicitly name for capture/
    hit-reaction animations) - a stray or late PieceArrived forcing
    IDLE mid-flourish would truncate a deliberate visual sequence that
    has nothing to do with the real motion, which has already
    completed by the time SHORT_REST/LONG_REST is even reached."""

    states = _all_states({AnimationState.SHORT_REST: _make_state_config(5, 10, False, AnimationState.LONG_REST)})
    animator = PieceAnimator(piece_id=1, states=states)
    animator._transition_to(AnimationState.SHORT_REST)
    animator.advance(123)  # some real progress into the rest animation
    assert animator.current_state == AnimationState.SHORT_REST

    animator.on_event(_piece_arrived(1))

    assert animator.current_state == AnimationState.SHORT_REST  # untouched
    assert animator.elapsed_ms_in_state == 123  # not reset either - no transition happened at all
