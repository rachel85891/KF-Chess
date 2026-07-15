"""AnimationState: the 5 animation states, per client_spec.md §5.

Values match the real directory names found under
assets/pieces/<KIND><COLOR>/states/ (verified against
assets/pieces/QW/states/* before writing this) exactly, including
casing - both because config.json's own "next_state_when_finished"
field uses these exact strings, and so AnimationState(name) round-trips
cleanly against the vendored assets without any translation table.
"""

from __future__ import annotations

from enum import Enum


class AnimationState(Enum):
    IDLE = "idle"
    JUMP = "jump"
    LONG_REST = "long_rest"
    MOVE = "move"
    SHORT_REST = "short_rest"
