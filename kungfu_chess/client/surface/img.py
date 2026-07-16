"""Img: thin, generic OpenCV-backed graphics primitive, per
client_spec.md §0's hard constraint - ALL graphics (board, pieces,
animations, score, move log) must go exclusively through this class
(no pygame/SFML/LWJGL/etc).

Re-implemented from scratch for this project's own actual needs,
informed by (not copied from) the reference Img class found in the
CTD26 repo (https://github.com/KamaTechOrg/CTD26.git,
py/img.py, commit caef11a0bfa31f7dbb91b30188c03cc759c927c9): that
reference class supports loading+resizing an image, overlaying one
image onto another with alpha blending, drawing text, and a blocking
`show()`. This class covers the same underlying operations (load,
paste-with-alpha, filled rectangle, text, show) but is shaped around
what THIS project needs - a blank canvas to draw a board onto (the
reference has no such concept, only `read()` from a file), and a
non-blocking `show()` suited to being called once per frame by a
future real-time loop (Stage 10) rather than the reference's
single-blocking-keypress `show()`.

SRP: Img knows nothing about Kung Fu Chess concepts (board, piece,
cell, AnimationState) - it is a generic 2D-image primitive. cv2/numpy
usage is fully contained inside this one file; every public method
takes/returns plain Python values (paths, ints, color tuples) or
another Img, never a raw numpy array - ImgSurface (img_surface.py) is
the only place that translates domain concepts into calls on this
class.
"""

from __future__ import annotations

from pathlib import Path
from typing import Tuple

import cv2
import numpy as np


class ImgSurfaceError(Exception):
    """Shared base for every error raised anywhere in
    kungfu_chess/client/surface/ (this file, asset_cache.py,
    img_surface.py) - lives here, in the lowest-level module of the
    three, since img.py has no dependency on the other two and both of
    them already depend on it (DIP: dependencies point toward Img, not
    away from it). Named after the whole surface/ subsystem, not just
    this one file, matching the same one-class-per-failure-mode base
    convention as BoardError/StateConfigError/GameEventPublisherError/
    ScreenToImageMapperError/PieceAnimatorError elsewhere in this
    codebase: catchable via this one base, or via a specific subclass."""


class ImageLoadError(ImgSurfaceError):
    """An image file does not exist, or exists but cannot be decoded
    as an image (e.g. corrupted or wrong format) - cv2.imread returns
    None in both cases with no further detail, so this class is the
    only place that can tell the two apart from a plain None check;
    both are treated as one failure mode here since a caller can't act
    differently on either.
    """


class PasteOutOfBoundsError(ImgSurfaceError):
    """paste()'s sprite does not fit on the canvas at the given (x, y)
    - guarded explicitly because numpy slicing silently clips instead
    of raising, which would otherwise let a shape-mismatch surface
    later as a confusing bare ValueError from the alpha-blending step,
    far from the actual out-of-bounds position that caused it."""


class Img:
    """A single in-memory image (either a freshly-created blank
    canvas, or a sprite loaded from disk), wrapping one BGR/BGRA numpy
    array. The array itself is never exposed publicly."""

    def __init__(self, array: np.ndarray) -> None:
        """Wrap an already-built numpy array.

        Args:
            array: A BGR (3-channel) or BGRA (4-channel) uint8 image
                array, in OpenCV's own row-major (height, width,
                channels) layout.

        Returns:
            None.

        Not meant to be called directly by most callers - use the
        blank_canvas() or load() class methods instead, which build a
        correctly-shaped array for you. Exposed as a plain constructor
        anyway (rather than making it private) since some callers -
        e.g. a spy/fake in tests - may reasonably want to construct an
        Img around a hand-built array directly.
        """

        self._array = array

    @property
    def width(self) -> int:
        """The image's width in pixels.

        Returns:
            The array's second dimension (numpy images are indexed
            [row, col] i.e. [height, width]).
        """

        return self._array.shape[1]

    @property
    def height(self) -> int:
        """The image's height in pixels.

        Returns:
            The array's first dimension.
        """

        return self._array.shape[0]

    @classmethod
    def blank_canvas(cls, width: int, height: int, background_color: Tuple[int, int, int] = (255, 255, 255)) -> "Img":
        """Create a new, solid-color BGR canvas of the given size -
        the starting point for drawing a board frame from scratch.

        Args:
            width: Canvas width in pixels.
            height: Canvas height in pixels.
            background_color: BGR fill color (OpenCV's channel order,
                not RGB). Defaults to white.

        Returns:
            A new Img wrapping a fresh (height, width, 3) array filled
            with background_color.
        """

        array = np.zeros((height, width, 3), dtype=np.uint8)
        array[:, :] = background_color
        return cls(array)

    @classmethod
    def load(cls, path: Path) -> "Img":
        """Load an image file from disk (e.g. a piece sprite PNG).

        Args:
            path: Filesystem path to the image file. May include an
                alpha channel (loaded as BGRA) - cv2.IMREAD_UNCHANGED
                preserves it, needed for paste()'s alpha blending.

        Returns:
            A new Img wrapping the loaded array.

        Raises:
            ImageLoadError: If `path` does not exist or cannot be
                decoded as an image.
        """

        array = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
        if array is None:
            raise ImageLoadError(f"{path}: cannot load image (missing or unreadable)")
        return cls(array)

    def paste(self, sprite: "Img", x: int, y: int) -> None:
        """Paste `sprite` onto this image at pixel position (x, y),
        alpha-blending if sprite has a 4th (alpha) channel. Mutates
        this image in place; `sprite` itself is never modified - safe
        to call repeatedly with the same cached sprite Img pasted onto
        many different canvases/positions (e.g. AssetCache's shared,
        cached sprite instances).

        Args:
            x: Destination pixel x (left edge of where sprite lands).
            y: Destination pixel y (top edge of where sprite lands).
            sprite: The Img to paste onto this one.

        Returns:
            None.

        Raises:
            PasteOutOfBoundsError: If sprite does not fully fit within
                this image's bounds at (x, y).
        """

        sprite_h, sprite_w = sprite._array.shape[:2]
        canvas_h, canvas_w = self._array.shape[:2]

        if x < 0 or y < 0 or y + sprite_h > canvas_h or x + sprite_w > canvas_w:
            raise PasteOutOfBoundsError(
                f"sprite of size {sprite_w}x{sprite_h} does not fit at ({x}, {y}) "
                f"on a {canvas_w}x{canvas_h} canvas"
            )

        region = self._array[y : y + sprite_h, x : x + sprite_w]

        if sprite._array.shape[2] == 4:
            alpha = sprite._array[:, :, 3].astype(np.float32) / 255.0
            for channel in range(3):
                region[:, :, channel] = (1 - alpha) * region[:, :, channel] + alpha * sprite._array[:, :, channel]
        else:
            region[:, :, :3] = sprite._array[:, :, :3]

    def draw_rectangle(
        self, x: int, y: int, width: int, height: int, color: Tuple[int, int, int], thickness: int = -1
    ) -> None:
        """Draw a rectangle on this image.

        Args:
            x: Left edge, in pixels.
            y: Top edge, in pixels.
            width: Rectangle width, in pixels.
            height: Rectangle height, in pixels.
            color: BGR color.
            thickness: Border thickness in pixels; -1 (the default)
                fills the whole rectangle instead of just outlining it
                - OpenCV's own convention for cv2.rectangle, kept as-is
                here rather than inventing a separate "filled" flag.

        Returns:
            None.
        """

        cv2.rectangle(self._array, (x, y), (x + width, y + height), color, thickness)

    def draw_text(
        self,
        text: str,
        x: int,
        y: int,
        color: Tuple[int, int, int] = (0, 0, 0),
        font_scale: float = 1.0,
        thickness: int = 1,
    ) -> None:
        """Draw a line of text on this image.

        Args:
            text: The string to draw.
            x: Left edge of the text baseline, in pixels.
            y: The text baseline's vertical position, in pixels
                (OpenCV anchors text at its baseline, not its top-left
                corner - callers should account for this the same way
                any cv2.putText caller would).
            color: BGR color.
            font_scale: OpenCV font scale factor (roughly, font size).
            thickness: Stroke thickness in pixels.

        Returns:
            None.
        """

        cv2.putText(self._array, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, font_scale, color, thickness, cv2.LINE_AA)

    def show(self, window_name: str = "Kung Fu Chess") -> None:
        """Display this image in an OpenCV window.

        Args:
            window_name: The OpenCV window's title/identifier.

        Returns:
            None.

        Uses cv2.waitKey(1) (a 1ms, non-blocking poll) rather than the
        CTD26 reference's cv2.waitKey(0) (blocks until any keypress) -
        this project's game loop (client_spec.md §4/§8) calls
        show()-equivalent once per frame at ~30 FPS, so a blocking wait
        would freeze the whole loop on every single frame. No window-
        close handling is implemented here - this stage does not wire
        a real running loop yet (that's Stage 10's GameLoopRunner), so
        there is no loop for a close event to break out of.
        """

        cv2.imshow(window_name, self._array)
        cv2.waitKey(1)
