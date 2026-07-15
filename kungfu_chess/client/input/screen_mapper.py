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
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ImagePosition:
    x: float
    y: float


@dataclass(frozen=True)
class ScreenToImageMapper:
    window_origin: tuple[int, int]
    window_scale: float

    def to_image(self, screen_x: float, screen_y: float) -> ImagePosition:
        origin_x, origin_y = self.window_origin
        return ImagePosition(
            x=(screen_x - origin_x) / self.window_scale,
            y=(screen_y - origin_y) / self.window_scale,
        )
