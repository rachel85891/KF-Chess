"""GameState: the mutable session state a GameEngine holds or points
to, per spec.md §9 - separate from GameEngine itself so the engine's
orchestration logic and the data it coordinates over stay distinct.
Named explicitly in spec.md §4's target project structure.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class GameState:
    game_over: bool = False
    clock_ms: int = 0
