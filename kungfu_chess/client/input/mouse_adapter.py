"""MouseAdapter: thin wrapper over cv2.setMouseCallback, per
client_spec.md §7 - the only class in this codebase that touches cv2
for mouse registration; ScreenToImageMapper and Controller each stay
completely ignorant of cv2 (that boundary is the whole point of this
class existing as its own file rather than folding this glue into
either of them).

Real signatures verified directly from source before writing this,
per the standing project convention of not guessing:
- `help(cv2.setMouseCallback)` ->
  `setMouseCallback(windowName, onMouse[, param]) -> None`, where
  OpenCV's own onMouse convention is `onMouse(event, x, y, flags,
  param)` - on_mouse_event's signature matches that exactly.
- `Controller.click(self, x: int, y: int) -> None`
  (kungfu_chess/input/controller.py) already calls
  `board.in_bounds(cell)` itself and handles an out-of-bounds click
  gracefully (clears selection, returns - no exception). MouseAdapter
  therefore does NOT re-check bounds: that would be the same rule
  enforced in two places, one of which (this file) would have no real
  authority over what "in bounds" even means.
"""

from __future__ import annotations

from typing import Any

import cv2

from kungfu_chess.client.input.screen_mapper import ScreenToImageMapper
from kungfu_chess.input.controller import Controller


class MouseAdapterError(Exception):
    """Base for MouseAdapter's own errors. Only one concrete subclass
    exists (InvalidWindowNameError) - re-checking Controller's and
    ScreenToImageMapper's actual behavior beforehand ruled out adding
    anything else here: both already fail safely (or don't fail at
    all) for every input this class can hand them."""


class InvalidWindowNameError(MouseAdapterError):
    """cv2.setMouseCallback itself does not validate window_name - an
    empty string would silently register a callback against a
    nonsensical window identifier with no error anywhere, a real gap
    neither Controller nor ScreenToImageMapper has any say over."""


class MouseAdapter:
    def __init__(self, mapper: ScreenToImageMapper, controller: Controller) -> None:
        """mapper and controller are both injected (DIP) rather than
        constructed here - which mapper/controller to use is a wiring
        decision that belongs to a future composition root
        (GameLoopRunner), not to this class."""

        self._mapper = mapper
        self._controller = controller

    def on_mouse_event(self, event: int, x: int, y: int, flags: int, param: Any) -> None:
        """Only cv2.EVENT_LBUTTONDOWN is treated as a click. Every
        other event cv2 reports on the same callback (move, button-up,
        right-click, wheel, drag) is a legitimate no-op here, not an
        unhandled case: this project's interaction model
        (client_spec.md §7/§11) is a single left-click-to-select-or-
        move gesture, nothing else.

        x/y are rounded to the nearest int before reaching
        Controller.click: ScreenToImageMapper.to_image returns
        continuous floats, but Controller.click (and BoardMapper
        underneath it) do integer floor-division against CELL_SIZE -
        passing a float through unrounded would silently produce a
        float Position field several layers down instead of the int
        the rest of the model layer expects.
        """

        if event != cv2.EVENT_LBUTTONDOWN:
            return

        image_position = self._mapper.to_image(x, y)
        self._controller.click(round(image_position.x), round(image_position.y))

    def attach(self, window_name: str) -> None:
        """The one place in this class that calls cv2 for callback
        registration, kept separate from on_mouse_event so the click-
        translation logic itself can be unit-tested without ever
        calling cv2.setMouseCallback or opening a real window.

        Raises:
            InvalidWindowNameError: If window_name is empty - see the
                class's own docstring for why this is checked here
                rather than left to cv2 (which wouldn't check it at
                all).
        """

        if not window_name:
            raise InvalidWindowNameError("window_name must be a non-empty string")

        cv2.setMouseCallback(window_name, self.on_mouse_event)
