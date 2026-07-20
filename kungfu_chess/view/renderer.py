"""GameSnapshot, build_snapshot, and Renderer, per spec.md §12.

GameSnapshot is a read-only DTO: board_width, board_height, pieces
(kind/color/pixel position/state), game_over. `selected` is an addition
beyond spec's literal field list - required by the Renderer's own
"highlight a selected piece" responsibility, which has nowhere else to
read that information from; sourced from Controller.selected.

build_snapshot is the one place in this file that depends on
GameEngine/Controller/RealTimeArbiter (per spec.md §4's dependency
list: "TextTestRunner depends on BoardParser, BoardPrinter, Controller,
GameEngine" - this snapshot builder plays the analogous composing role
for the View). Renderer itself only ever touches GameSnapshot/Surface,
preserving "view depends on game-state snapshots" (spec.md §3).

In-flight interpolation: for each of RealTimeArbiter.active_motions(),
progress = clamp((clock_ms - start_time) / (arrival_time - start_time), 0, 1),
applied linearly per axis between the source and destination cells'
pixel positions (top-left corner of each cell, i.e. col*CELL_SIZE /
row*CELL_SIZE - the same anchor convention BoardMapper already uses).
A piece not currently in an active motion renders at its own cell's
pixel position directly.

build_snapshot_from_board (Stage B6, server track): a SECOND, additive
snapshot builder, alongside build_snapshot above - not a replacement
for it, and build_snapshot/Renderer/GameSnapshot/PieceSnapshot are all
otherwise completely unchanged by this addition (re-verified via diff
before committing). Needed because kungfu_chess/client/loop/
network_game_loop_runner.py's NetworkGameLoopRunner has no GameEngine/
Controller/RealTimeArbiter at all - the server, not this process, is
the sole source of truth (matching every other network-track stage's
own design: B2's GameSession, B3's GameServer) - it only ever has a
plain Board, parsed via BoardParser from a server board-state
broadcast. build_snapshot itself cannot be reused as-is for this: it
unconditionally reads engine.state.clock_ms and
engine.arbiter.active_motions() to interpolate in-flight motion, and
network mode has neither a real engine nor a real arbiter to ask.

SCOPE DECISION (Stage B6, explicit and accepted - do not relitigate):
the server's existing broadcast (Stage B3) sends a full board-as-text
snapshot at two points per move (MoveAccepted = pre-move, PieceArrived
= post-move), not the rich, continuous animation-frame event stream
PieceAnimatorRegistry expects locally. Building smooth cross-network
animation is explicitly OUT OF SCOPE for Stage B6 and left to a
separate future stage. build_snapshot_from_board therefore never
interpolates - every piece renders statically at its own cell's pixel
position (Piece.state itself, always PieceState.IDLE for anything
BoardParser ever produces, is used as-is; there is no live animation
state to ask for in network mode either).

`game_over` defaults to False and is never inferred from the Board
itself: raw board-state broadcast text carries no explicit game-over
signal at all (GameServer's own broadcaster sends identical board text
regardless of which of MoveAccepted/MoveRejected/PieceArrived/GameOver
triggered it) - a documented, accepted gap, not something this function
can silently paper over by guessing (e.g. "a missing king" would be an
inference, not a fact this function was told). A future stage wanting
real game-over detection in network mode would need either a
distinguishable server message or explicit client-side board diffing;
out of scope here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from kungfu_chess.engine.game_engine import GameEngine
from kungfu_chess.input.controller import Controller
from kungfu_chess.model.board import Board
from kungfu_chess.model.color import Color
from kungfu_chess.model.piece import PieceKind, PieceState
from kungfu_chess.model.position import Position
from kungfu_chess.realtime.real_time_arbiter import CELL_SIZE
from kungfu_chess.view.image_view import Surface


@dataclass(frozen=True)
class PieceSnapshot:
    id: int
    kind: PieceKind
    color: Color
    x: int
    y: int
    state: PieceState


@dataclass(frozen=True)
class GameSnapshot:
    board_width: int
    board_height: int
    pieces: tuple[PieceSnapshot, ...]
    game_over: bool
    selected: Optional[Position] = None


def _cell_pixel(cell: Position) -> tuple[int, int]:
    return cell.col * CELL_SIZE, cell.row * CELL_SIZE


def build_snapshot(engine: GameEngine, controller: Controller) -> GameSnapshot:
    board = engine.board
    clock_ms = engine.state.clock_ms

    in_flight_positions: dict[int, tuple[int, int]] = {}
    for motion in engine.arbiter.active_motions():
        total_ms = motion.arrival_time - motion.start_time
        elapsed_ms = clock_ms - motion.start_time
        progress = 0.0 if total_ms <= 0 else max(0.0, min(1.0, elapsed_ms / total_ms))

        source_x, source_y = _cell_pixel(motion.source)
        destination_x, destination_y = _cell_pixel(motion.destination)
        x = round(source_x + (destination_x - source_x) * progress)
        y = round(source_y + (destination_y - source_y) * progress)
        in_flight_positions[motion.piece.id] = (x, y)

    pieces = []
    for row in range(board.height):
        for col in range(board.width):
            piece = board.piece_at(Position(row=row, col=col))
            if piece is None:
                continue

            if piece.id in in_flight_positions:
                x, y = in_flight_positions[piece.id]
            else:
                x, y = _cell_pixel(piece.cell)

            pieces.append(
                PieceSnapshot(id=piece.id, kind=piece.kind, color=piece.color, x=x, y=y, state=piece.state)
            )

    return GameSnapshot(
        board_width=board.width,
        board_height=board.height,
        pieces=tuple(pieces),
        game_over=engine.state.game_over,
        selected=controller.selected,
    )


def build_snapshot_from_board(
    board: Board,
    selected: Optional[Position] = None,
    game_over: bool = False,
) -> GameSnapshot:
    """Build a GameSnapshot directly from a plain Board - no
    GameEngine/Controller/RealTimeArbiter involved. See module
    docstring's "build_snapshot_from_board (Stage B6...)" section for
    the full reasoning (why this exists, and its explicit no-
    interpolation scope decision).

    Args:
        board: The Board to snapshot - e.g. one just parsed via
            BoardParser from a server board-state broadcast.
        selected: The currently-selected cell, if any (same role as
            Controller.selected for build_snapshot above) - passed
            through to GameSnapshot as-is.
        game_over: Whether to mark the snapshot as game-over. Defaults
            to False - see module docstring for why this can never be
            inferred from `board` itself.

    Returns:
        A GameSnapshot with every piece rendered statically at its own
        cell's pixel position (no in-flight interpolation).
    """

    pieces = []
    for row in range(board.height):
        for col in range(board.width):
            piece = board.piece_at(Position(row=row, col=col))
            if piece is None:
                continue

            x, y = _cell_pixel(piece.cell)
            pieces.append(PieceSnapshot(id=piece.id, kind=piece.kind, color=piece.color, x=x, y=y, state=piece.state))

    return GameSnapshot(
        board_width=board.width,
        board_height=board.height,
        pieces=tuple(pieces),
        game_over=game_over,
        selected=selected,
    )


class Renderer:
    def __init__(self, surface: Surface):
        self.surface = surface

    def render(self, snapshot: GameSnapshot) -> None:
        self.surface.draw_grid(snapshot.board_width, snapshot.board_height)

        for piece in snapshot.pieces:
            self.surface.draw_piece(piece)

        if snapshot.selected is not None:
            self.surface.draw_selection_highlight(snapshot.selected)

        if snapshot.game_over:
            self.surface.draw_game_over_message()
