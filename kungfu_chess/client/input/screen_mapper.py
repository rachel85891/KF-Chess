"""ScreenToImageMapper: window pixel -> image pixel conversion, per
client_spec.md §7.

Sits one layer above kungfu_chess.input.board_mapper.BoardMapper in the
pipeline: BoardMapper already converts an image pixel to a logical cell
(Position, row/col). This class converts a raw *window* pixel to an
*image* pixel - it does not know about cells or bounds at all, and does
not depend on BoardMapper/Controller/Position in any way (spec's ISP:
three separate small contracts, not one fat one).

Design decisions:
- Output is a dedicated ImagePosition(x, y), not model.Position. The
  existing Position is documented as a logical (row, col) board
  coordinate (kungfu_chess/model/position.py) - reusing it here would
  mean stuffing a continuous pixel x/y into fields named row/col,
  which is a semantic mismatch, not a reuse. ImagePosition keeps the
  pixel-space concept distinct from the board-space one, exactly as
  the pipeline itself keeps them as two separate conversion steps.
- A single, uniform window_scale (not separate x/y scale factors):
  client_spec.md §7 states the formula in terms of one `window_scale`
  applied to both axes, matching how a single Img canvas is expected
  to be scaled uniformly to fit a window (no independent horizontal/
  vertical stretch is described anywhere in the spec).
- Immutable (frozen dataclass): consistent with Position and the rest
  of the pure model/pipeline types in this codebase, and appropriate
  for a stateless, "pure" conversion (spec §7: "no dependency on cv2 /
  an actual window"). A change in origin/scale (e.g. window resize) is
  represented by constructing a new mapper instance, not mutating one.
- Out-of-bounds screen coordinates are neither clamped nor rejected:
  to_image() always returns the mathematically transformed coordinate
  as-is, even if negative or beyond the image's extent. Bounds
  checking is explicitly a different layer's job (Board.in_bounds, the
  same separation of concerns Position itself already documents) - a
  pure coordinate transform has no notion of "the board's bounds" to
  check against.
- window_scale IS validated, at construction (__post_init__), because
  it is a denominator in to_image()'s division - a zero value would
  raise an opaque ZeroDivisionError from inside an unrelated method
  call, at a point far from where the bad value was actually supplied,
  and a negative value would silently mirror every coordinate instead
  of failing at all. Both are invalid window scales, not "different
  concerns" the way out-of-bounds screen input is - rejecting them
  eagerly at construction fails loudly at the actual mistake, with a
  named, specific exception (ScreenToImageMapperError's convention,
  matching BoardError/StateConfigError/GameEventPublisherError
  elsewhere in this codebase) instead of a bare built-in one.
"""

from __future__ import annotations

from dataclasses import dataclass


class ScreenToImageMapperError(Exception):
    """Base class for all ScreenToImageMapper errors, matching the
    same one-class-per-failure-mode convention as BoardError
    (kungfu_chess/model/board.py), StateConfigError
    (kungfu_chess/client/animation/state_config.py), and
    GameEventPublisherError (kungfu_chess/client/events/event_publisher.py):
    catchable via this one base, or via a specific subclass below."""


class InvalidWindowScaleError(ScreenToImageMapperError):
    """window_scale was <= 0 at ScreenToImageMapper construction - it
    is a divisor in to_image(), so a non-positive value would either
    crash with an opaque ZeroDivisionError far from the actual mistake
    (zero) or silently mirror every converted coordinate (negative)."""


@dataclass(frozen=True)
class ImagePosition:
    """A single point in image-pixel space (as opposed to window-pixel
    space or a logical board cell/Position).

    A plain, immutable data holder - x/y are continuous pixel
    coordinates within the logical board image, with no validation of
    their own (there is no "invalid" x/y here, unlike window_scale on
    ScreenToImageMapper below).

    Attributes:
        x: The horizontal image-pixel coordinate.
        y: The vertical image-pixel coordinate.
    """

    x: float
    y: float


@dataclass(frozen=True)
class ScreenToImageMapper:
    """Pure, immutable window-pixel -> image-pixel converter (see the
    module docstring for the full rationale behind ImagePosition vs.
    Position, uniform vs. per-axis scale, and immutability).

    Attributes:
        window_origin: The (x, y) window-pixel coordinate that
            corresponds to image-pixel (0, 0).
        window_scale: The uniform scale factor applied to both axes
            when converting a window pixel to an image pixel. Must be
            strictly positive (validated in __post_init__).
    """

    window_origin: tuple[int, int]
    window_scale: float

    def __post_init__(self) -> None:
        """Validate window_scale immediately at construction.

        Frozen dataclasses cannot be mutated after __init__, but
        __post_init__ still runs once, right after all fields are set
        - the standard place to validate a frozen dataclass's own
        fields without weakening its immutability.

        Raises:
            InvalidWindowScaleError: If window_scale is <= 0.
        """

        if self.window_scale <= 0:
            raise InvalidWindowScaleError(f"window_scale must be > 0, got {self.window_scale!r}")

    def to_image(self, screen_x: float, screen_y: float) -> ImagePosition:
        """Convert one raw window-pixel coordinate to an image-pixel
        coordinate, per client_spec.md §7's formula:
        image_x = (screen_x - origin_x) / scale (and similarly for y).

        Args:
            screen_x: The raw window-pixel x coordinate (e.g. from a
                mouse event), in the same coordinate space as
                window_origin.
            screen_y: The raw window-pixel y coordinate.

        Returns:
            The corresponding ImagePosition. Always the raw
            mathematical result, even if it falls outside the image's
            actual extent - see the module docstring's "out-of-bounds"
            design decision for why this method never clamps or raises
            on the screen_x/screen_y values themselves (window_scale
            is validated separately, at construction, not here).
        """

        origin_x, origin_y = self.window_origin
        return ImagePosition(
            x=(screen_x - origin_x) / self.window_scale,
            y=(screen_y - origin_y) / self.window_scale,
        )
