"""Timing/geometry rules for a game session, as configuration data rather
than constants baked into business logic. A custom game can supply its
own GameRules instance instead of DEFAULT_GAME_RULES."""

from dataclasses import dataclass


@dataclass(frozen=True)
class GameRules:
    cell_size: int
    move_duration_per_cell_ms: int
    jump_duration_ms: int


DEFAULT_GAME_RULES = GameRules(
    cell_size=100,
    move_duration_per_cell_ms=1000,
    jump_duration_ms=1000,
)
