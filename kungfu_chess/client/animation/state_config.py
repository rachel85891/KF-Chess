"""StateConfig: one animation state's config.json, parsed and
validated, per client_spec.md §5/§11.

Real file shape (verified directly against assets/pieces/QW/states/
{idle,jump,move,short_rest,long_rest}/config.json before writing this,
per client_spec.md §11's instruction not to assume field names from
spec text alone):

    {
      "physics": {"speed_m_per_sec": 1.5, "next_state_when_finished": "long_rest"},
      "graphics": {"frames_per_sec": 12, "is_loop": true}
    }

StateConfig mirrors this nesting (PhysicsConfig/GraphicsConfig as
sub-dataclasses) rather than flattening it onto one level. Chosen
because it keeps the loader's shape in 1:1 correspondence with the
file's own shape - anyone comparing a StateConfig to its source
config.json sees the same two groups, and a future third top-level
section in config.json (or a new field within an existing one) has an
obvious place to land without renaming/prefixing flat fields to avoid
collisions.

ASSETS_ROOT is the single constant every future asset-loading component
(AssetCache, this module) should import, rather than each hardcoding
its own relative path to assets/, per client_spec.md §11 step 5.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Tuple

from kungfu_chess.client.animation.animation_state import AnimationState

ASSETS_ROOT = Path(__file__).resolve().parents[3] / "assets"
PIECES_ROOT = ASSETS_ROOT / "pieces"

STATES = tuple(AnimationState)


class StateConfigError(Exception):
    """Raised when a config.json is missing, malformed, or missing a
    required field - always names the offending path so the failure is
    diagnosable without a traceback dive."""


@dataclass(frozen=True)
class PhysicsConfig:
    speed_m_per_sec: float
    next_state_when_finished: AnimationState


@dataclass(frozen=True)
class GraphicsConfig:
    frames_per_sec: int
    is_loop: bool


@dataclass(frozen=True)
class StateConfig:
    physics: PhysicsConfig
    graphics: GraphicsConfig
    sprite_paths: Tuple[Path, ...]


def _require(section: dict, key: str, *, section_name: str, path: Path) -> object:
    if key not in section:
        raise StateConfigError(f"{path}: missing required field '{section_name}.{key}'")
    return section[key]


def _sprite_paths_for(config_path: Path) -> Tuple[Path, ...]:
    sprites_dir = config_path.parent / "sprites"
    if not sprites_dir.is_dir():
        raise StateConfigError(f"{config_path}: missing sibling sprites/ directory ({sprites_dir})")
    return tuple(sorted(sprites_dir.iterdir(), key=lambda p: p.name))


def load_state_config(path: Path) -> StateConfig:
    """Load and validate one states/<state>/config.json, and collect
    its sibling sprites/ directory's file paths (sorted by filename) -
    the two are always siblings under the same state directory per
    client_spec.md §11's fixed layout, so no separate call is needed."""

    try:
        raw_text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise StateConfigError(f"{path}: config.json not found") from exc

    try:
        raw = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise StateConfigError(f"{path}: invalid JSON ({exc})") from exc

    if "physics" not in raw:
        raise StateConfigError(f"{path}: missing required section 'physics'")
    if "graphics" not in raw:
        raise StateConfigError(f"{path}: missing required section 'graphics'")

    physics_raw = raw["physics"]
    graphics_raw = raw["graphics"]

    next_state_raw = _require(physics_raw, "next_state_when_finished", section_name="physics", path=path)
    try:
        next_state = AnimationState(next_state_raw)
    except ValueError as exc:
        raise StateConfigError(
            f"{path}: physics.next_state_when_finished has unknown value {next_state_raw!r}"
        ) from exc

    physics = PhysicsConfig(
        speed_m_per_sec=_require(physics_raw, "speed_m_per_sec", section_name="physics", path=path),
        next_state_when_finished=next_state,
    )
    graphics = GraphicsConfig(
        frames_per_sec=_require(graphics_raw, "frames_per_sec", section_name="graphics", path=path),
        is_loop=_require(graphics_raw, "is_loop", section_name="graphics", path=path),
    )

    return StateConfig(physics=physics, graphics=graphics, sprite_paths=_sprite_paths_for(path))


def load_piece_states(piece_dir: Path) -> Dict[AnimationState, StateConfig]:
    """Load all 5 states/<state>/config.json files under one
    <KIND><COLOR> directory (e.g. assets/pieces/QW), keyed by
    AnimationState."""

    return {state: load_state_config(piece_dir / "states" / state.value / "config.json") for state in STATES}
