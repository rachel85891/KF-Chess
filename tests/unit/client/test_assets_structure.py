import json
from pathlib import Path

import pytest

ASSETS_ROOT = Path(__file__).resolve().parents[3] / "assets"
PIECES_ROOT = ASSETS_ROOT / "pieces"

KINDS = {"K", "Q", "R", "B", "N", "P"}
COLORS = {"W", "B"}
EXPECTED_COMBOS = {kind + color for kind in KINDS for color in COLORS}

REQUIRED_PHYSICS_KEYS = {"speed_m_per_sec", "next_state_when_finished"}
REQUIRED_GRAPHICS_KEYS = {"frames_per_sec", "is_loop"}


def combo_dirs():
    return sorted(p for p in PIECES_ROOT.iterdir() if p.is_dir())


def test_exactly_twelve_kind_color_combos_present():
    found = {p.name for p in combo_dirs()}
    assert found == EXPECTED_COMBOS
    assert len(found) == 12


@pytest.mark.parametrize("combo_dir", combo_dirs(), ids=lambda p: p.name)
def test_every_state_config_is_valid(combo_dir):
    state_dirs = sorted(p for p in (combo_dir / "states").iterdir() if p.is_dir())
    assert state_dirs, f"{combo_dir.name} has no states/"

    for state_dir in state_dirs:
        config_path = state_dir / "config.json"
        assert config_path.is_file(), f"missing config.json in {state_dir}"

        with config_path.open(encoding="utf-8") as f:
            config = json.load(f)

        assert REQUIRED_PHYSICS_KEYS <= config.get("physics", {}).keys(), state_dir
        assert REQUIRED_GRAPHICS_KEYS <= config.get("graphics", {}).keys(), state_dir

        sprites_dir = state_dir / "sprites"
        assert sprites_dir.is_dir(), f"missing sprites/ in {state_dir}"
        assert any(sprites_dir.iterdir()), f"empty sprites/ in {state_dir}"


def test_board_image_present_and_non_empty():
    board_path = ASSETS_ROOT / "board.png"
    assert board_path.is_file()
    assert board_path.stat().st_size > 0
