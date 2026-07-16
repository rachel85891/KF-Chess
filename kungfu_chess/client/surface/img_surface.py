"""ImgSurface: implements the existing Surface Protocol
(kungfu_chess/view/image_view.py) on top of Img + AssetCache, per
client_spec.md §3's component table ("ImgSurface | Implements Surface
on top of Img; draws grid, pieces, highlights, HUD | Img, Surface
protocol").

This is the only class in kungfu_chess/client/surface/ that knows Kung
Fu Chess domain concepts (PieceSnapshot, Position, PieceKind, Color,
AnimationState) - Img and AssetCache stay fully generic (SRP: Img only
draws primitives, AssetCache only loads/caches, ImgSurface only
translates domain snapshots into calls on the other two).

DIP: ImgSurface depends only on Img's and AssetCache's public methods,
never on cv2/numpy directly - all cv2 usage stays inside img.py.

ISP: this class's public surface is exactly the Surface Protocol's 4
methods (draw_grid, draw_piece, draw_selection_highlight,
draw_game_over_message) - nothing extra Renderer doesn't already call.

STATIC IDLE SPRITE - TEMPORARY, PENDING STAGE 10: PieceAnimator (Stage
5) is not wired to a GameEventPublisher or to this class yet (that
wiring is Stage 10's GameLoopRunner composition root). Without a live
PieceAnimator per piece, draw_piece has no current animation
state/frame to draw from - so, for THIS stage only, every piece is
drawn using its <KIND><COLOR>'s AnimationState.IDLE state, frame 0
(sprite_paths[0]), regardless of the piece's actual model PieceState.
Note the deliberate distinction: PieceSnapshot.state is
model.piece.PieceState (idle/moving/captured, a 3-value enum from the
LOGIC layer) - NOT client_spec.md's 5-value AnimationState (the CLIENT
layer's animation states) - these are different enums with similarly-
named members and must not be confused; this class currently ignores
PieceSnapshot.state entirely, which is exactly the gap Stage 10 closes
by wiring a real PieceAnimator.current_sprite_path() per piece instead
of this hardcoded idle lookup.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict

from kungfu_chess.client.animation.animation_state import AnimationState
from kungfu_chess.client.animation.state_config import PIECES_ROOT, StateConfig, load_piece_states
from kungfu_chess.client.surface.asset_cache import AssetCache
from kungfu_chess.client.surface.img import Img, ImgSurfaceError
from kungfu_chess.model.position import Position
from kungfu_chess.realtime.real_time_arbiter import CELL_SIZE
from kungfu_chess.view.renderer import PieceSnapshot

LIGHT_CELL_COLOR = (222, 235, 235)
DARK_CELL_COLOR = (90, 110, 110)
HIGHLIGHT_COLOR = (0, 215, 255)
HIGHLIGHT_THICKNESS = 4
GAME_OVER_TEXT = "GAME OVER"
GAME_OVER_TEXT_COLOR = (0, 0, 255)
GAME_OVER_FONT_SCALE = 1.5
GAME_OVER_TEXT_THICKNESS = 3


class UnknownPieceAssetError(ImgSurfaceError):
    """draw_piece was given a PieceSnapshot whose kind+color combo has
    no matching assets/pieces/<KIND><COLOR> directory at all. Narrower
    than "any StateConfigError from Stage 4's loader": if the
    directory DOES exist but its data is malformed (a real asset bug),
    that is a different, already-well-named failure - Stage 4's own
    specific StateConfigError subclass is left to propagate as-is
    rather than being folded into this one, so the two distinct
    problems ("this combo doesn't exist" vs. "this combo's data is
    broken") stay distinguishable."""


class ImgSurface:
    """Surface Protocol implementation backed by a real Img canvas and
    an AssetCache."""

    def __init__(self, canvas: Img, asset_cache: AssetCache) -> None:
        """Construct an ImgSurface.

        Args:
            canvas: The Img every draw_* call renders onto - owned by
                the caller (e.g. a future GameLoopRunner), not created
                here, so the same canvas can be shown/saved outside
                this class's own knowledge.
            asset_cache: The AssetCache used to load/cache piece
                sprites.

        Returns:
            None.
        """

        self._canvas = canvas
        self._asset_cache = asset_cache
        self._piece_states_cache: Dict[str, Dict[AnimationState, StateConfig]] = {}

    def _kind_color_key(self, piece: PieceSnapshot) -> str:
        """Build the <KIND><COLOR> directory-name key for a piece.

        Args:
            piece: The PieceSnapshot to derive a key for.

        Returns:
            A 2-character string like "QW" or "PB", matching
            assets/pieces/<KIND><COLOR>'s real directory naming
            exactly (kind.value is already the single uppercase
            letter used there; color.value is lowercase ("w"/"b") so
            it is upper-cased to match).
        """

        return f"{piece.kind.value}{piece.color.value.upper()}"

    def _idle_sprite_path(self, piece: PieceSnapshot) -> Path:
        """Resolve the static idle-frame-0 sprite Path for a piece's
        kind+color combo, loading and caching that combo's full
        5-state StateConfig set on first use (see module docstring's
        "static idle sprite" note for why frame 0 of IDLE, not the
        piece's actual state, is used at this stage).

        Args:
            piece: The PieceSnapshot to resolve a sprite for.

        Returns:
            The Path to that combo's AnimationState.IDLE,
            sprite_paths[0].

        Raises:
            UnknownPieceAssetError: If no assets/pieces/<KIND><COLOR>
                directory exists for this piece's kind+color combo.
        """

        key = self._kind_color_key(piece)
        if key not in self._piece_states_cache:
            piece_dir = PIECES_ROOT / key
            if not piece_dir.is_dir():
                raise UnknownPieceAssetError(
                    f"no assets/pieces/{key} directory for kind={piece.kind.value} color={piece.color.value}"
                )
            self._piece_states_cache[key] = load_piece_states(piece_dir)

        return self._piece_states_cache[key][AnimationState.IDLE].sprite_paths[0]

    def draw_grid(self, width: int, height: int) -> None:
        """Draw a width x height checkerboard grid of board cells.

        Args:
            width: Board width, in CELLS (not pixels) - matches
                GameSnapshot.board_width, per the Surface Protocol.
            height: Board height, in cells.

        Returns:
            None.

        Alternating LIGHT_CELL_COLOR/DARK_CELL_COLOR filled rectangles
        (standard checkerboard) - a reasonable default visual
        treatment; client_spec.md does not mandate a specific palette.
        """

        for row in range(height):
            for col in range(width):
                color = LIGHT_CELL_COLOR if (row + col) % 2 == 0 else DARK_CELL_COLOR
                self._canvas.draw_rectangle(col * CELL_SIZE, row * CELL_SIZE, CELL_SIZE, CELL_SIZE, color)

    def draw_piece(self, piece: PieceSnapshot) -> None:
        """Draw one piece's static idle sprite at its snapshot pixel
        position (see module docstring's "static idle sprite" note).

        Args:
            piece: The PieceSnapshot to draw. piece.x/piece.y are
                already pixel coordinates (build_snapshot has already
                done cell-to-pixel and in-flight-motion interpolation
                - this method only pastes at the position it's given).

        Returns:
            None.

        Raises:
            UnknownPieceAssetError: See _idle_sprite_path.
        """

        sprite_path = self._idle_sprite_path(piece)
        sprite = self._asset_cache.get(sprite_path)
        self._canvas.paste(sprite, piece.x, piece.y)

    def draw_selection_highlight(self, cell: Position) -> None:
        """Draw a highlighted border around the selected cell.

        Args:
            cell: The logical (row, col) cell to highlight.

        Returns:
            None.

        An unfilled rectangle outline (thickness=HIGHLIGHT_THICKNESS,
        not a filled block) so the piece and cell color underneath the
        selection remain visible - a filled highlight would completely
        obscure both.
        """

        x, y = cell.col * CELL_SIZE, cell.row * CELL_SIZE
        self._canvas.draw_rectangle(x, y, CELL_SIZE, CELL_SIZE, HIGHLIGHT_COLOR, thickness=HIGHLIGHT_THICKNESS)

    def draw_game_over_message(self) -> None:
        """Draw a "GAME OVER" text overlay, roughly centered on the
        canvas.

        Returns:
            None.

        Approximate centering (canvas width/4, canvas height/2), not
        pixel-perfect text-metrics centering - a dedicated HUD/text-
        layout component (hud_renderer.py, client_spec.md §2's
        directory tree) isn't part of this stage's scope; this is a
        simple, reasonable placeholder treatment.
        """

        x = max(10, self._canvas.width // 4)
        y = self._canvas.height // 2
        self._canvas.draw_text(
            GAME_OVER_TEXT, x, y, color=GAME_OVER_TEXT_COLOR, font_scale=GAME_OVER_FONT_SCALE,
            thickness=GAME_OVER_TEXT_THICKNESS,
        )
