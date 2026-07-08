"""GameEngine: the Facade composing every service into the same small
surface the original monolithic GameState exposed - handle_click,
handle_jump, handle_wait, plus a settle_due_events hook for the
presentation layer to call before reading board state. It orchestrates;
it does not itself implement selection rules, scheduling math,
settlement, promotion, or win detection - those are the services it
composes, so each stays independently testable.

Operates purely in (row, col) - pixel coordinates never reach this
layer, they are translated once at the presentation boundary. This is
what actually makes the engine reusable from a future GUI, not just the
text CLI.
"""

from typing import Optional

from kungfu_chess.config.game_rules import GameRules
from kungfu_chess.domain.board import Board
from kungfu_chess.domain.events import GameEnded, PieceCaptured
from kungfu_chess.services.click_interpreter import ClickIntentKind, interpret_click
from kungfu_chess.services.event_bus import EventBus
from kungfu_chess.services.move_legality_service import is_move_allowed
from kungfu_chess.services.move_resolver import resolve_due_events, resolve_instant_royal_capture
from kungfu_chess.services.move_scheduler import MoveScheduler
from kungfu_chess.services.promotion_service import PromotionService
from kungfu_chess.services.win_condition import RoyalCaptureWinCondition, WinCondition

Cell = tuple[int, int]


class GameEngine:
    def __init__(self, board: Board, game_rules: GameRules, win_conditions: Optional[list[WinCondition]] = None):
        self.board = board
        self.selected: Optional[Cell] = None
        self.clock_ms = 0
        self.game_over = False

        self._game_rules = game_rules
        self._scheduler = MoveScheduler()
        self.event_bus = EventBus()
        self._win_conditions = win_conditions if win_conditions is not None else [RoyalCaptureWinCondition()]

        PromotionService(self.board, self.event_bus)
        self.event_bus.subscribe(PieceCaptured, self._on_piece_captured)

    def _on_piece_captured(self, event: PieceCaptured) -> None:
        if any(condition.ends_game(event) for condition in self._win_conditions):
            self.game_over = True
            self.event_bus.publish(GameEnded(reason="royal_capture"))

    def settle_due_events(self) -> None:
        resolve_due_events(self._scheduler, self.board, self.clock_ms, self.event_bus)

    def handle_click(self, row: int, col: int) -> None:
        if self.game_over:
            return

        self.settle_due_events()

        if not self.board.in_bounds(row, col):
            return

        intent = interpret_click(self.selected, (row, col), self.board, self._scheduler)

        if intent.kind == ClickIntentKind.IGNORE:
            return

        if intent.kind == ClickIntentKind.SELECT:
            self.selected = intent.cell
            return

        self._handle_move_request(intent.from_cell, intent.to_cell)
        self.selected = None

    def _handle_move_request(self, from_cell: Cell, to_cell: Cell) -> None:
        mover = self.board.get_piece(*from_cell)

        if not is_move_allowed(self.board, from_cell, to_cell):
            return
        if self._scheduler.has_pending_for_color(mover.color.opposite):
            # A move already in flight for the OTHER color blocks a new
            # request outright; same-color moves may run in parallel.
            return

        target = self.board.get_piece(*to_cell)
        if target is not None and target.is_royal and not self._scheduler.is_airborne(*to_cell):
            resolve_instant_royal_capture(mover, from_cell, to_cell, self.board, self.event_bus)
            return

        distance = max(abs(to_cell[0] - from_cell[0]), abs(to_cell[1] - from_cell[1]))
        duration = distance * self._game_rules.move_duration_per_cell_ms
        self._scheduler.schedule_move(from_cell, to_cell, mover, self.clock_ms, self.clock_ms + duration)

    def handle_jump(self, row: int, col: int) -> None:
        if self.game_over:
            return

        self.settle_due_events()

        if not self.board.in_bounds(row, col):
            return

        piece = self.board.get_piece(row, col)
        if piece is None:
            return
        if self._scheduler.has_pending_move_from(row, col):
            return
        if self._scheduler.is_airborne(row, col):
            return

        land_time = self.clock_ms + self._game_rules.jump_duration_ms
        self._scheduler.schedule_landing((row, col), piece, self.clock_ms, land_time)

    def handle_wait(self, ms: int) -> None:
        self.clock_ms += ms
        self.settle_due_events()
