"""CapturedPiecesRenderer: draws a small row of captured-piece icons
below one side's SidePanelRenderer output - a new UI piece for
NetworkGameLoopRunner's own consumption of the server-authoritative
MovesLogSnapshot (kungfu_chess/notation/game_state_snapshot_wire_format.py's
"STATE:" broadcast, decoded back into a real MovesLogSnapshot).

DOES NOT MODIFY SidePanelRenderer/ScoreObserver/MovesLogObserver/
MovesLogSnapshot/CaptureLogEntry IN ANY WAY (per this stage's own
explicit requirement) - this module only ever READS a MovesLogSnapshot
already handed to it and only ever calls AssetCache/Img's existing
public methods.

SRP/DIP, mirroring SidePanelRenderer's own conventions exactly: a pure
function of an already-computed MovesLogSnapshot - no engine/board/
network reference, no score/log computation of its own (that already
happened once, server-side, inside MovesLogObserver - re-verified
directly - this class only re-derives a GROUPING from data that
observer already produced, never a capture/score fact of its own).

GROUPING LOGIC (its own dedicated, pure, independently-testable
function - group_captured_pieces_by_color - per this stage's own
requirement for a "dedicated test... testable without any rendering at
all"): a captured piece belongs in the CAPTURING side's own box, not
its own original side's box - the same real chess-UI convention (and
the SAME rule ScoreObserver._apply_capture, kungfu_chess/client/events/
observers.py, already re-verified directly, encodes for scoring:
`capturing_color = captured_info.color.opposite`) applied here to
grouping icons instead of summing values. A white piece captured
therefore appears in BLACK's own captured-pieces box (Black is who
captured it), and vice versa. Since a box's own captured pieces are, by
this same rule, ALWAYS the OPPOSITE color of the box itself, the
grouping only needs to record piece KIND per box (the icon's own color
is always `box_color.opposite`, a constant per box) - no need to also
store per-entry color.

WHY ITS OWN MODULE, NOT FOLDED INTO SidePanelRenderer: SidePanelRenderer
is explicitly off-limits for modification this stage (per requirement
5), and this is materially a SEPARATE rendering concern (a derived
grouping over the SAME log data, not the log's own chronological
listing SidePanelRenderer's own table already draws) - keeping it
separate also means a future stage that wants to change ONLY the
captured-pieces display (e.g. a different icon size/layout) touches
one small, focused module, not the panel's own established table/
score/title rendering.

LAYOUT PLACEMENT: drawn in the SAME [x, x+width) horizontal region a
caller's own SidePanelRenderer call already used for that color (this
class takes the identical x/width/color parameters, by design, so a
caller passes the exact same triple to both), starting at a Y position
computed from SidePanelRenderer's own PUBLIC layout constants
(TABLE_FIRST_ROW_Y + PANEL_MAX_LOG_ROWS * TABLE_ROW_HEIGHT + PANEL_PADDING
- comfortably below the panel's own Time/Move table's maximum possible
extent, reusing those constants directly rather than hardcoding a
duplicate magic number that could silently drift out of sync if
SidePanelRenderer's own layout ever changes) - "below each side's
existing SidePanelRenderer output," matching this stage's own suggested
placement. This is well within the panel's own already-reserved
background rectangle (SidePanelRenderer's own panel spans the FULL
canvas height already), so no new canvas space is needed for this
class at all - unlike GameTimerRenderer (kungfu_chess/client/ui/
game_timer_renderer.py), which does need new canvas space of its own.

ICON RENDERING: reuses the exact same lower-level, PUBLIC asset-loading
primitives kungfu_chess/client/surface/img_surface.py's own
_idle_sprite_path already uses (PIECES_ROOT, load_piece_states,
AnimationState.IDLE) rather than depending on ImgSurface itself (which
has no public API for "just resolve a static sprite path for this
kind+color", only a private method) - this keeps this class fully
independent of ImgSurface (SRP: no dependency on a class whose whole
job is drawing the BOARD), while still reusing every already-public
building block, not re-deriving asset-path conventions a third way.
Icons are drawn small (ICON_SIZE, well under a full CELL_SIZE) in a
left-to-right row, wrapping to a new row if a side captures enough
pieces to overflow one row's own width - a real, if rare in practice,
possibility (multiple pawns/pieces captured over a long game).
"""

from __future__ import annotations

from typing import Dict, List

from kungfu_chess.client.animation.animation_state import AnimationState
from kungfu_chess.client.animation.state_config import PIECES_ROOT, load_piece_states
from kungfu_chess.client.events.observers import CaptureLogEntry, MovesLogSnapshot
from kungfu_chess.client.surface.asset_cache import AssetCache
from kungfu_chess.client.surface.img import Img
from kungfu_chess.client.ui.side_panel_renderer import (
    PANEL_MAX_LOG_ROWS,
    PANEL_PADDING,
    TABLE_FIRST_ROW_Y,
    TABLE_ROW_HEIGHT,
)
from kungfu_chess.model.color import Color
from kungfu_chess.model.piece import PieceKind

# Comfortably below the panel's own Time/Move table's maximum possible
# extent - see module docstring's "LAYOUT PLACEMENT" section for why
# this is derived from SidePanelRenderer's own public constants, not a
# hardcoded, independently-drifting magic number.
CAPTURED_BOX_Y = TABLE_FIRST_ROW_Y + PANEL_MAX_LOG_ROWS * TABLE_ROW_HEIGHT + PANEL_PADDING
CAPTURED_BOX_LABEL_Y = CAPTURED_BOX_Y + 14
CAPTURED_BOX_LABEL_COLOR = (220, 220, 220)
CAPTURED_BOX_LABEL_FONT_SCALE = 0.5

ICON_SIZE = 26
ICON_ROW_Y_OFFSET = CAPTURED_BOX_LABEL_Y + 10
ICON_ROW_SPACING = 4


def group_captured_pieces_by_color(log: MovesLogSnapshot) -> Dict[Color, List[PieceKind]]:
    """Group every CaptureLogEntry in `log` by the CAPTURING side's own
    color - see module docstring's "GROUPING LOGIC" section for the
    full reasoning (the same captured_piece_color.opposite rule
    ScoreObserver._apply_capture already applies for scoring).

    Args:
        log: The current MovesLogSnapshot (kungfu_chess/client/events/
            observers.py's MovesLogObserver.snapshot(), or a real,
            wire-parsed reconstruction of the same shape - re-verified
            directly, kungfu_chess/notation/
            game_state_snapshot_wire_format.py's parse_game_state_
            snapshot already produces an equal-in-every-field
            MovesLogSnapshot).

    Returns:
        {Color.WHITE: [...], Color.BLACK: [...]} - always both keys
        present (an empty list, not a missing key, for a side that
        hasn't captured anything yet), each list holding one
        PieceKind per captured piece, in the order captured
        (chronological, matching `log.entries`'s own order) - every
        entry in a given color's list is, by this function's own rule,
        always of the OPPOSITE color (White's own box only ever lists
        pieces White captured, which are always Black's own pieces),
        so only the kind needs to be recorded per entry.
    """

    grouped: Dict[Color, List[PieceKind]] = {Color.WHITE: [], Color.BLACK: []}
    for entry in log.entries:
        if isinstance(entry, CaptureLogEntry):
            capturing_color = entry.captured_piece_color.opposite
            grouped[capturing_color].append(entry.captured_piece_kind)
    return grouped


class CapturedPiecesRenderer:
    """Draws one color's own captured-piece icon row - see module
    docstring for the full layout/grouping reasoning."""

    def __init__(self, canvas: Img, asset_cache: AssetCache) -> None:
        """canvas/asset_cache are both injected (DIP), not created or
        owned here - same pattern as ImgSurface's own canvas/
        asset_cache injection."""

        self._canvas = canvas
        self._asset_cache = asset_cache

    def render(self, x: int, width: int, color: Color, log: MovesLogSnapshot) -> None:
        """Draw `color`'s own captured-piece icon row at horizontal
        region [x, x+width) - the SAME region a caller's own
        SidePanelRenderer.render(x=x, width=width, color=color, ...)
        call already used for this color (see module docstring's
        "LAYOUT PLACEMENT" section).

        Args:
            x: Left pixel edge of this panel's region on the canvas -
                identical to the x already passed to SidePanelRenderer
                for this same color.
            width: This panel's pixel width.
            color: Which side's own captured-pieces box this is (the
                side that DID the capturing, per group_captured_pieces_
                by_color's own rule - not the color of the icons
                themselves, which are always the OPPOSITE color).
            log: The current MovesLogSnapshot.

        Returns:
            None.
        """

        captured_kinds = group_captured_pieces_by_color(log)[color]
        icon_color = color.opposite

        self._canvas.draw_text(
            "Captured:", x + PANEL_PADDING, CAPTURED_BOX_LABEL_Y,
            color=CAPTURED_BOX_LABEL_COLOR, font_scale=CAPTURED_BOX_LABEL_FONT_SCALE,
        )

        icons_per_row = max(1, (width - 2 * PANEL_PADDING) // (ICON_SIZE + ICON_ROW_SPACING))
        for index, kind in enumerate(captured_kinds):
            row, col = divmod(index, icons_per_row)
            icon_x = x + PANEL_PADDING + col * (ICON_SIZE + ICON_ROW_SPACING)
            icon_y = ICON_ROW_Y_OFFSET + row * (ICON_SIZE + ICON_ROW_SPACING)
            sprite = self._icon_sprite(kind, icon_color)
            self._canvas.paste(sprite, icon_x, icon_y)

    def _icon_sprite(self, kind: PieceKind, color: Color) -> Img:
        """Resolve and resize the static idle-frame-0 sprite for
        kind+color to ICON_SIZE x ICON_SIZE.

        NO per-instance StateConfig cache here (unlike ImgSurface's own
        _piece_states_cache): the expensive part - decoding the actual
        sprite image bytes from disk - is already cached across every
        frame by the shared `self._asset_cache` instance
        (AssetCache.get, keyed by resolved path); load_piece_states
        itself only re-parses one small config.json per kind+color
        combo (at most 12 combos ever exist), a bounded, cheap
        operation even called fresh every frame - unlike ImgSurface's
        own cache, which mostly sits dormant in real usage (that class
        always has a live PieceAnimatorRegistry, so its static-idle
        fallback path - the only path that would ever consult its
        cache - is never actually exercised in practice; this class has
        no such live-animator alternative, so its own cache would
        genuinely be hit every frame - not worth the added complexity
        for a cheap, bounded operation).

        See module docstring's "ICON RENDERING" section for why this
        reuses the same PIECES_ROOT/load_piece_states/AnimationState.IDLE primitives
        img_surface.py's own _idle_sprite_path already uses, rather
        than depending on ImgSurface itself.

        Args:
            kind: The captured piece's own kind.
            color: The captured piece's own color (always
                box_color.opposite - see render()'s own docstring).

        Returns:
            A resized Img, ICON_SIZE x ICON_SIZE.
        """

        key = f"{kind.value}{color.value.upper()}"
        piece_dir = PIECES_ROOT / key
        sprite_path = load_piece_states(piece_dir)[AnimationState.IDLE].sprite_paths[0]
        native_sprite = self._asset_cache.get(sprite_path)
        return native_sprite.resize(ICON_SIZE, ICON_SIZE)
