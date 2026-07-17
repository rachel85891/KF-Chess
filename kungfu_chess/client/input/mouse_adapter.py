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

JUMP (Stage 11a): right-click is routed to a SEPARATE, optional
`on_jump_requested` callback, never through Controller.click - a jump
(ExtraEngine.request_jump(cell), re-verified directly) acts on
whichever piece sits at ONE cell, with no select-then-target two-step
the way a move has; Controller.click's whole job is interpreting a
click against the current selection state, which is the wrong model
entirely for a single-click, no-selection gesture. Right-click (not
some other gesture) was chosen because it's already the conventional
"alternate action" mouse gesture in most desktop UIs, distinct from
left-click's primary action, needing no new modifier keys or on-screen
affordance - and because a jump conceptually parallels a move closely
enough (both act on a piece the user points at) that reusing the same
input device with a different button, rather than introducing keyboard
input for this, keeps the interaction model consistent.

WHY a plain callback (Callable[[Position], None]), not a new
interface/class: MouseAdapter is handing off exactly one piece of
information (a cell) to trigger exactly one action - inventing a
Protocol/class for a single method would be needless ceremony over a
function reference, the same reasoning already used for
EventOrderingPolicy (Stage 3) being a bare Callable, not a class.
Defaults to None (a no-op on right-click) so every existing caller
that constructs a MouseAdapter without it - Stage 7's own tests and
usage - keeps working completely unchanged (verified via diff, the
same backward-compatibility rule Stage 10b's ImgSurface change
followed).

The right-click path resolves its own logical cell via a private,
internally-constructed BoardMapper (kungfu_chess/input/board_mapper.py)
- the same pattern Controller itself already uses internally
(`self.board_mapper = BoardMapper()`, never injected, since BoardMapper
takes no configuration and has no state) - because on_jump_requested
needs a logical (row, col) Position, not a raw image pixel: unlike the
left-click path, this one bypasses Controller/its own BoardMapper
entirely, so MouseAdapter needs the same pixel-to-cell conversion
available to itself.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

import cv2

from kungfu_chess.client.input.screen_mapper import ScreenToImageMapper
from kungfu_chess.input.board_mapper import BoardMapper
from kungfu_chess.input.controller import Controller
from kungfu_chess.model.position import Position


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
    def __init__(
        self,
        mapper: ScreenToImageMapper,
        controller: Controller,
        on_jump_requested: Optional[Callable[[Position], None]] = None,
    ) -> None:
        """mapper and controller are both injected (DIP) rather than
        constructed here - which mapper/controller to use is a wiring
        decision that belongs to a future composition root
        (GameLoopRunner), not to this class. on_jump_requested is also
        injected, but stays Optional/defaulted (see module docstring)
        so every existing caller that predates JUMP support (Stage 7)
        keeps constructing MouseAdapter exactly as before.

        board_mapper is NOT a constructor parameter, unlike the other
        three - it's built internally, the same way Controller builds
        its own (see module docstring): a pure, stateless,
        zero-configuration utility class has nothing for DIP to
        usefully inject.
        """

        self._mapper = mapper
        self._controller = controller
        self._on_jump_requested = on_jump_requested
        self._board_mapper = BoardMapper()

    def on_mouse_event(self, event: int, x: int, y: int, flags: int, param: Any) -> None:
        """Left-click and right-click are two distinct gestures with
        two distinct destinations (see module docstring for why right-
        click specifically, and why a callback). Every OTHER event cv2
        reports on this same callback (move, button-up, wheel, drag)
        remains a legitimate no-op, not an unhandled case: this
        project's interaction model (client_spec.md §7/§11) still only
        recognizes these two click gestures, nothing else.

        x/y are rounded to the nearest int before reaching
        Controller.click or on_jump_requested: ScreenToImageMapper.
        to_image returns continuous floats, but Controller.click/
        BoardMapper both do integer floor-division against CELL_SIZE -
        passing a float through unrounded would silently produce a
        float Position field several layers down instead of the int
        the rest of the model layer expects.
        """

        if event == cv2.EVENT_LBUTTONDOWN:
            image_position = self._mapper.to_image(x, y)
            self._controller.click(round(image_position.x), round(image_position.y))
            return

        if event == cv2.EVENT_RBUTTONDOWN and self._on_jump_requested is not None:
            image_position = self._mapper.to_image(x, y)
            cell = self._board_mapper.pixel_to_cell(round(image_position.x), round(image_position.y))
            self._on_jump_requested(cell)

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
