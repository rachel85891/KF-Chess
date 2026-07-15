from __future__ import annotations

from pathlib import Path

import pytest

from kungfu_chess.client.animation.animation_state import AnimationState
from kungfu_chess.client.animation.piece_animator import (
    EmptyStateSpritesError,
    IncompleteAnimationStatesError,
    InvalidAdvanceDurationError,
    PieceAnimator,
    UnknownTransitionTargetError,
)
from kungfu_chess.client.animation.state_config import (
    PIECES_ROOT,
    GraphicsConfig,
    PhysicsConfig,
    StateConfig,
    load_piece_states,
)
from kungfu_chess.client.events.game_events import GameOver, JumpAccepted, MoveAccepted, MoveRejected, PieceArrived
from kungfu_chess.model.color import Color
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
    defaults = {
        state: _make_state_config(1, 1, True, AnimationState.IDLE) for state in AnimationState
    }
    defaults.update(overrides or {})
    return defaults


def test_initial_state_defaults_to_idle_frame_zero_elapsed_zero():
    animator = PieceAnimator(piece_id=1, states=_all_states())

    assert animator.current_state == AnimationState.IDLE
    assert animator.current_frame_index == 0
    assert animator.elapsed_ms_in_state == 0


def test_move_accepted_for_own_piece_transitions_to_move_and_resets():
    animator = PieceAnimator(piece_id=1, states=_all_states())
    animator.advance(500)

    animator.on_event(
        MoveAccepted(piece_id=1, from_cell=Position(row=0, col=0), to_cell=Position(row=0, col=1), duration_ms=1000)
    )

    assert animator.current_state == AnimationState.MOVE
    assert animator.current_frame_index == 0
    assert animator.elapsed_ms_in_state == 0


def test_jump_accepted_for_own_piece_transitions_to_jump_and_resets():
    animator = PieceAnimator(piece_id=1, states=_all_states())
    animator.advance(500)

    animator.on_event(
        JumpAccepted(piece_id=1, from_cell=Position(row=0, col=0), to_cell=Position(row=0, col=0), duration_ms=625)
    )

    assert animator.current_state == AnimationState.JUMP
    assert animator.current_frame_index == 0
    assert animator.elapsed_ms_in_state == 0


def test_event_for_different_piece_id_is_ignored():
    animator = PieceAnimator(piece_id=1, states=_all_states())

    animator.on_event(
        MoveAccepted(piece_id=999, from_cell=Position(row=0, col=0), to_cell=Position(row=0, col=1), duration_ms=1000)
    )

    assert animator.current_state == AnimationState.IDLE
    assert animator.current_frame_index == 0
    assert animator.elapsed_ms_in_state == 0


def test_irrelevant_event_types_for_own_piece_id_are_ignored():
    animator = PieceAnimator(piece_id=1, states=_all_states())

    animator.on_event(PieceArrived(piece_id=1, cell=Position(row=0, col=0), captured_piece_id=None))
    animator.on_event(GameOver(winner_color=Color.WHITE))
    animator.on_event(MoveRejected(reason="cooldown_active"))

    assert animator.current_state == AnimationState.IDLE
    assert animator.current_frame_index == 0
    assert animator.elapsed_ms_in_state == 0


def test_advance_progresses_frame_index_across_varying_deltas():
    # frames_per_sec=10 -> 100ms per frame.
    states = _all_states({AnimationState.MOVE: _make_state_config(5, 10, True, AnimationState.IDLE)})
    animator = PieceAnimator(piece_id=1, states=states, initial_state=AnimationState.MOVE)

    animator.advance(30)  # elapsed=30 -> frame 0
    assert animator.current_frame_index == 0

    animator.advance(90)  # elapsed=120 -> frame 1
    assert animator.current_frame_index == 1

    animator.advance(85)  # elapsed=205 -> frame 2
    assert animator.current_frame_index == 2


def test_looping_state_wraps_frame_index_instead_of_transitioning():
    # frames_per_sec=10, 3 frames -> 300ms full cycle.
    states = _all_states({AnimationState.MOVE: _make_state_config(3, 10, True, AnimationState.IDLE)})
    animator = PieceAnimator(piece_id=1, states=states, initial_state=AnimationState.MOVE)

    animator.advance(250)  # elapsed=250 -> frames_elapsed=2 -> frame 2
    assert animator.current_state == AnimationState.MOVE
    assert animator.current_frame_index == 2

    animator.advance(100)  # elapsed=350 -> frames_elapsed=3 -> wraps to frame 0
    assert animator.current_state == AnimationState.MOVE
    assert animator.current_frame_index == 0


def test_non_looping_state_auto_transitions_when_exhausted():
    # frames_per_sec=10, 3 frames, not looping -> 300ms total duration.
    states = _all_states({AnimationState.MOVE: _make_state_config(3, 10, False, AnimationState.IDLE)})
    animator = PieceAnimator(piece_id=1, states=states, initial_state=AnimationState.MOVE)

    animator.advance(250)  # elapsed=250 -> frames_elapsed=2 < 3, still MOVE
    assert animator.current_state == AnimationState.MOVE
    assert animator.current_frame_index == 2

    animator.advance(60)  # elapsed=310 -> frames_elapsed=3 >= 3, exhausted
    assert animator.current_state == AnimationState.IDLE
    assert animator.current_frame_index == 0
    assert animator.elapsed_ms_in_state == 0


def test_current_sprite_path_returns_a_path_present_in_the_current_states_sprites():
    states = _all_states({AnimationState.MOVE: _make_state_config(4, 10, True, AnimationState.IDLE)})
    animator = PieceAnimator(piece_id=1, states=states, initial_state=AnimationState.MOVE)

    animator.advance(120)  # frames_elapsed=1 -> frame 1

    sprite_path = animator.current_sprite_path()

    assert sprite_path in states[AnimationState.MOVE].sprite_paths
    assert sprite_path == states[AnimationState.MOVE].sprite_paths[1]


def test_constructor_raises_incomplete_animation_states_error_naming_missing_states():
    incomplete_states = _all_states()
    del incomplete_states[AnimationState.JUMP]
    del incomplete_states[AnimationState.SHORT_REST]

    with pytest.raises(IncompleteAnimationStatesError) as exc_info:
        PieceAnimator(piece_id=7, states=incomplete_states)

    message = str(exc_info.value)
    assert "piece_id=7" in message
    assert "jump" in message
    assert "short_rest" in message


def test_constructor_raises_empty_state_sprites_error_naming_the_offending_state():
    states = _all_states({AnimationState.MOVE: _make_state_config(0, 10, True, AnimationState.IDLE)})

    with pytest.raises(EmptyStateSpritesError) as exc_info:
        PieceAnimator(piece_id=9, states=states)

    message = str(exc_info.value)
    assert "piece_id=9" in message
    assert "move" in message


def test_advance_raises_invalid_advance_duration_error_for_negative_delta():
    animator = PieceAnimator(piece_id=3, states=_all_states())

    with pytest.raises(InvalidAdvanceDurationError) as exc_info:
        animator.advance(-1)

    message = str(exc_info.value)
    assert "piece_id=3" in message
    assert "-1" in message


def test_transition_to_raises_unknown_transition_target_error_if_states_dict_mutated_after_construction():
    # Unreachable through the public on_event/advance API under normal
    # operation: __init__'s IncompleteAnimationStatesError check
    # guarantees `states` has all 5 AnimationState keys at
    # construction, and every caller of _transition_to only ever
    # passes one of those same 5 members. This test reaches the guard
    # anyway by mutating the injected states dict *after*
    # construction - PieceAnimator stores it by reference, not a
    # defensive copy, so a misbehaving caller really could break the
    # invariant this way, which is exactly why the guard exists
    # despite being unreachable via the state machine's own
    # transitions.
    animator = PieceAnimator(piece_id=1, states=_all_states())
    del animator.states[AnimationState.JUMP]

    with pytest.raises(UnknownTransitionTargetError) as exc_info:
        animator._transition_to(AnimationState.JUMP)

    assert "piece_id=1" in str(exc_info.value)


def test_full_flow_with_real_qw_assets():
    states = load_piece_states(PIECES_ROOT / "QW")
    animator = PieceAnimator(piece_id=42, states=states)
    assert animator.current_state == AnimationState.IDLE

    animator.on_event(
        MoveAccepted(piece_id=42, from_cell=Position(row=0, col=0), to_cell=Position(row=0, col=1), duration_ms=1000)
    )
    assert animator.current_state == AnimationState.MOVE
    assert animator.current_frame_index == 0

    animator.advance(250)
    assert animator.current_state == AnimationState.MOVE
    assert animator.current_sprite_path() in states[AnimationState.MOVE].sprite_paths

    animator.on_event(
        JumpAccepted(piece_id=42, from_cell=Position(row=0, col=1), to_cell=Position(row=0, col=1), duration_ms=625)
    )
    assert animator.current_state == AnimationState.JUMP
    assert animator.current_frame_index == 0

    jump_config = states[AnimationState.JUMP]
    assert jump_config.graphics.is_loop is False

    total_jump_duration_ms = len(jump_config.sprite_paths) / jump_config.graphics.frames_per_sec * 1000
    animator.advance(int(total_jump_duration_ms) + 100)

    assert animator.current_state == jump_config.physics.next_state_when_finished
    assert animator.current_frame_index == 0
    assert animator.elapsed_ms_in_state == 0
