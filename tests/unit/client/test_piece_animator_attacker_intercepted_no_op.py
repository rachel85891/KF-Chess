"""Regression/decision tests for PieceAnimator: an AttackerIntercepted
event for this animator's own piece_id must NOT force any transition -
the piece is being destroyed, not merely idle, and the correct
treatment (investigated and documented in piece_animator.py's own
module docstring, "PART B DECISION" section) mirrors how an ordinary
move's own CAPTURED piece is already handled: no special animator
reaction at all, with the piece's actual disappearance achieved purely
via Board-level removal, never an AnimationState transition.

NEW, SEPARATE test file (not an edit to test_piece_animator.py,
test_piece_animator_arrival_transition.py, or
test_piece_animator_jump_landed_transition.py) - matches this
codebase's own established "new behavior gets a new test file"
convention, applied here to a new *investigated no-op decision* rather
than a bugfix, but the same "zero edits to pre-existing test files"
principle.
"""

from __future__ import annotations

from pathlib import Path

from kungfu_chess.client.animation.animation_state import AnimationState
from kungfu_chess.client.animation.piece_animator import PieceAnimator
from kungfu_chess.client.animation.state_config import GraphicsConfig, PhysicsConfig, StateConfig
from kungfu_chess.client.events.game_events import AttackerIntercepted, JumpAccepted, MoveAccepted
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


def _attacker_intercepted(piece_id: int) -> AttackerIntercepted:
    return AttackerIntercepted(piece_id=piece_id, cell=Position(row=0, col=0), defender_piece_id=999)


def test_attacker_intercepted_does_not_transition_a_piece_mid_move():
    states = _all_states({AnimationState.MOVE: _make_state_config(4, 10, True, AnimationState.IDLE)})
    animator = PieceAnimator(piece_id=1, states=states)
    animator.on_event(
        MoveAccepted(piece_id=1, from_cell=Position(row=0, col=0), to_cell=Position(row=0, col=1), duration_ms=1000)
    )
    assert animator.current_state == AnimationState.MOVE

    animator.on_event(_attacker_intercepted(1))

    # NOT forced to IDLE - unlike PieceArrived/JumpLanded, this event
    # produces no transition at all, by deliberate design (see
    # piece_animator.py's own "PART B DECISION" docstring section).
    assert animator.current_state == AnimationState.MOVE


def test_attacker_intercepted_does_not_transition_a_piece_mid_jump():
    states = _all_states({AnimationState.JUMP: _make_state_config(4, 10, True, AnimationState.IDLE)})
    animator = PieceAnimator(piece_id=1, states=states)
    animator.on_event(
        JumpAccepted(piece_id=1, from_cell=Position(row=0, col=0), to_cell=Position(row=0, col=0), duration_ms=625)
    )
    assert animator.current_state == AnimationState.JUMP

    animator.on_event(_attacker_intercepted(1))

    assert animator.current_state == AnimationState.JUMP


def test_attacker_intercepted_from_idle_is_a_no_op():
    animator = PieceAnimator(piece_id=1, states=_all_states())
    assert animator.current_state == AnimationState.IDLE

    animator.on_event(_attacker_intercepted(1))

    assert animator.current_state == AnimationState.IDLE
    assert animator.current_frame_index == 0
    assert animator.elapsed_ms_in_state == 0


def test_attacker_intercepted_for_a_different_piece_id_does_not_affect_this_animator():
    states = _all_states({AnimationState.MOVE: _make_state_config(4, 10, True, AnimationState.IDLE)})
    animator = PieceAnimator(piece_id=1, states=states)
    animator.on_event(
        MoveAccepted(piece_id=1, from_cell=Position(row=0, col=0), to_cell=Position(row=0, col=1), duration_ms=1000)
    )
    assert animator.current_state == AnimationState.MOVE

    animator.on_event(_attacker_intercepted(999))  # a different piece entirely

    assert animator.current_state == AnimationState.MOVE
