from __future__ import annotations

import json
from pathlib import Path

import pytest

from kungfu_chess.client.animation.animation_state import AnimationState
from kungfu_chess.client.animation.state_config import (
    PIECES_ROOT,
    StateConfigError,
    load_piece_states,
    load_state_config,
)

FIXTURES_ROOT = Path(__file__).resolve().parent / "fixtures"
QW_MOVE_CONFIG = PIECES_ROOT / "QW" / "states" / "move" / "config.json"
QW_DIR = PIECES_ROOT / "QW"


def test_load_state_config_matches_the_real_files_raw_values():
    raw = json.loads(QW_MOVE_CONFIG.read_text(encoding="utf-8"))

    config = load_state_config(QW_MOVE_CONFIG)

    assert config.physics.speed_m_per_sec == raw["physics"]["speed_m_per_sec"]
    assert config.physics.next_state_when_finished == AnimationState(raw["physics"]["next_state_when_finished"])
    assert config.graphics.frames_per_sec == raw["graphics"]["frames_per_sec"]
    assert config.graphics.is_loop == raw["graphics"]["is_loop"]


def test_load_piece_states_returns_all_five_animation_states_for_qw():
    states = load_piece_states(QW_DIR)

    assert set(states.keys()) == set(AnimationState)
    assert len(states) == 5


def test_sprite_paths_collected_per_state_are_non_empty_and_sorted():
    states = load_piece_states(QW_DIR)

    for state, config in states.items():
        assert len(config.sprite_paths) > 0, state
        assert list(config.sprite_paths) == sorted(config.sprite_paths, key=lambda p: p.name), state
        assert all(p.is_file() for p in config.sprite_paths), state


def test_missing_field_in_config_json_raises_clear_error():
    broken_path = FIXTURES_ROOT / "broken_missing_field" / "config.json"

    with pytest.raises(StateConfigError) as exc_info:
        load_state_config(broken_path)

    message = str(exc_info.value)
    assert str(broken_path) in message
    assert "frames_per_sec" in message


def test_malformed_json_raises_clear_error():
    broken_path = FIXTURES_ROOT / "broken_invalid_json" / "config.json"

    with pytest.raises(StateConfigError) as exc_info:
        load_state_config(broken_path)

    message = str(exc_info.value)
    assert str(broken_path) in message


def test_missing_config_file_raises_clear_error():
    missing_path = FIXTURES_ROOT / "does_not_exist" / "config.json"

    with pytest.raises(StateConfigError) as exc_info:
        load_state_config(missing_path)

    assert str(missing_path) in str(exc_info.value)
