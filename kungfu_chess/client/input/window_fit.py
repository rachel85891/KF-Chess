"""window_fit.py: pure math for fitting a fixed-size canvas image into
an arbitrarily-sized, resizable window - one uniform "letterbox" scale
factor plus a centering origin, never independent per-axis stretching.

WHY THIS IS ITS OWN MODULE, NOT ADDED TO screen_mapper.py:
kungfu_chess/client/input/screen_mapper.py's ScreenToImageMapper is a
small, pure, already-tested module whose own docstring explicitly
documents a single uniform `window_scale` (not separate x/y factors)
as a deliberate design decision, matching client_spec.md §7's own
formula - and it is explicitly NOT to be modified for this fix (its
existing contract already assumes uniform scaling; the job of THIS fix
is to make sure that assumption is actually kept true in practice as a
real window gets resized, not to change what ScreenToImageMapper
itself does with a scale/origin once it's given one). This module's
own responsibility is different and separate: given a canvas size and
the window's actual current on-screen size, compute WHAT scale/origin
ScreenToImageMapper should be constructed with this frame - a
computation, not a coordinate conversion. Kept alongside
screen_mapper.py (same package) since the two are closely related in
purpose, but as a clearly separate file/function so screen_mapper.py's
own file is untouched, and so this new math is independently unit-
testable without a real cv2 window at all (see this module's own
tests) - the two composition-root classes
(kungfu_chess/client/loop/game_loop.py's GameLoopRunner and
kungfu_chess/client/loop/network_game_loop_runner.py's
NetworkGameLoopRunner) are the only real callers, and the only place a
real cv2.getWindowImageRect() call is ever made.

WHY min(), NOT INDEPENDENT PER-AXIS STRETCHING: if a user drags a real
window into a non-proportional shape (e.g. much wider than the
canvas's own aspect ratio), stretching each axis independently to fill
the window would mean the rendered image's own x and y scale factors
differ from each other - but ScreenToImageMapper only accepts ONE
window_scale for both axes (by design, per its own docstring - see
above). Rather than changing that contract, this function guarantees
it stays true: `scale = min(window_width / canvas_width,
window_height / canvas_height)` picks the SAME single scale factor
that both fits within the window on both axes (never overflows either
one) and is the one actually applied when the canvas image itself is
resized before display (see the two Runner classes' own per-frame
code) - so the displayed image and the click-mapping math are
GUARANTEED to agree, by construction, not by coincidence.

ACCEPTED, DELIBERATE CONSEQUENCE - LETTERBOXING/PILLARBOXING: because
only one axis can be the "binding" constraint whenever the window's
aspect ratio doesn't exactly match the canvas's own, the scaled image
will not fill the window completely on the OTHER axis - e.g. a window
dragged much wider than tall will have the image centered with solid-
color empty margin on the left and right (pillarboxing); much taller
than wide leaves margin above and below (letterboxing). This is the
CORRECT, intended behavior for a non-proportionally-resized window,
not a bug or an oversight: the alternative (independently stretching
each axis) would silently break click-accuracy the moment the window's
own aspect ratio ever diverged from the canvas's, which is exactly the
failure this whole fix exists to prevent.

origin_x/origin_y CENTER the scaled image within the actual window
rect: origin_x = (window_width - canvas_width * scale) / 2 (and
similarly for y) - the window-pixel coordinate where the scaled
image's own local (0, 0) begins. This is exactly the value
ScreenToImageMapper's own `window_origin` parameter already expects
(client_spec.md §7: "the (x, y) window-pixel coordinate that
corresponds to image-pixel (0, 0)") - once given this real origin and
this real scale, ScreenToImageMapper.to_image's own existing, untouched
formula already maps a click in the letterboxed margin to an out-of-
canvas image coordinate correctly, with NO new clamping logic needed
here or there (Board.in_bounds, already called downstream by
Controller/NetworkClickController, is what rejects an out-of-canvas
click - the same separation of concerns this project already
established).

DEGENERATE INPUT (a minimized window, or any non-positive width/
height): returns scale=0.0 (or whatever non-positive value the raw
division produces) rather than raising - deliberately so a caller can
cheaply check `scale > 0` to decide whether this frame's result is
trustworthy, without this pure function needing to know anything about
"minimized windows" or make a policy decision about what to do when
one is encountered (that policy - skip the refresh, reuse the last
known-good mapper - belongs to the two Runner classes, per this
module's own "WHY THIS IS ITS OWN MODULE" section: this function only
computes numbers from sizes).
"""

from __future__ import annotations

from typing import Tuple


def compute_fit_scale_and_origin(
    canvas_width: int, canvas_height: int, window_width: int, window_height: int
) -> Tuple[float, float, float]:
    """Compute the uniform scale factor and centering origin needed to
    fit a `canvas_width` x `canvas_height` image into an actual
    `window_width` x `window_height` window rect, preserving aspect
    ratio (see module docstring for the full reasoning).

    Args:
        canvas_width: The rendered canvas's own native width, in
            pixels (never changes at runtime - fixed at construction).
        canvas_height: The rendered canvas's own native height.
        window_width: The window's actual, current on-screen image
            width, in pixels (e.g. from cv2.getWindowImageRect) - may
            be 0 or negative for a minimized/degenerate window.
        window_height: The window's actual, current on-screen image
            height.

    Returns:
        (scale, origin_x, origin_y):
        - scale: The single uniform factor to resize the canvas by so
          it fits within the window on both axes without overflowing
          either. Non-positive (e.g. 0.0) if window_width or
          window_height is non-positive - see module docstring's
          "DEGENERATE INPUT" section for why this is not an error.
        - origin_x, origin_y: The window-pixel coordinate where the
          scaled image's own (0, 0) should be placed to center it
          within the window - meaningless (but still returned, never
          raising) when scale is non-positive.
    """

    scale = min(window_width / canvas_width, window_height / canvas_height)
    origin_x = (window_width - canvas_width * scale) / 2
    origin_y = (window_height - canvas_height * scale) / 2
    return scale, origin_x, origin_y
