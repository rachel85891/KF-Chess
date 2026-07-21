"""Real, end-to-end integration test for fix/network-gameover-and-king-
interception - proves a real King captured via jump.py interception
(1) actually ends the game at the model layer (ExtraEngine.wait sets
engine.state.game_over - see that module's own docstring) and (2) is
correctly broadcast to and recognized by BOTH connected
NetworkGameLoopRunner clients, which must then stop accepting further
input and expose the real winner.

Mirrors tests/integration/client/test_network_game_loop_runner_
interception.py's own _BackgroundTestServer/session-injection pattern
exactly, reusing a King-as-attacker variant of that same test's own
interception scenario (per this fix's own task: a King-captured-via-
interception scenario is simpler than, and equally valid to, engineering
a full checkmate - this project has no checkmate detection at all, see
docs/spec.md §2).

NEW, SEPARATE test file (not an edit to any existing
test_network_game_loop_runner*.py file), matching this codebase's own
established "new behavior gets a new test file" convention.
"""

from __future__ import annotations

import asyncio
import threading
import time
from typing import Optional

import websockets

from kungfu_chess.client.loop.network_game_loop_runner import NetworkGameLoopRunner
from kungfu_chess.model.board import Board
from kungfu_chess.model.color import Color
from kungfu_chess.model.piece import Piece, PieceKind
from kungfu_chess.model.position import Position
from server.game_server import GameServer
from server.game_session import GameSession

_JOIN_TIMEOUT_S = 5.0
_POLL_INTERVAL_S = 0.05


def _empty_grid(rows: int, cols: int) -> list[list[None]]:
    return [[None for _ in range(cols)] for _ in range(rows)]


def _king_interception_ready_session() -> GameSession:
    """A King-as-attacker variant of test_network_game_loop_runner_
    interception.py's own interception scenario: a white pawn (defender)
    about to jump at its own cell, a black KING (attacker) one square
    away that will move toward that same cell (a King, unlike the ROOK
    that test uses, can only legally move one square at a time - see
    tests/unit/test_jump.py's own identically-adjusted King scenarios)."""

    grid = _empty_grid(4, 4)
    defender = Piece(color=Color.WHITE, kind=PieceKind.PAWN, cell=Position(row=0, col=0))
    attacker = Piece(color=Color.BLACK, kind=PieceKind.KING, cell=Position(row=0, col=1))
    grid[0][0] = defender
    grid[0][1] = attacker
    return GameSession(board=Board(grid))


class _BackgroundTestServer:
    """Identical in shape to test_network_game_loop_runner_
    interception.py's own _BackgroundTestServer."""

    def __init__(self, session: Optional[GameSession] = None) -> None:
        self.uri: str = ""
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._stop_event: Optional[asyncio.Event] = None
        ready = threading.Event()
        self._thread = threading.Thread(target=self._run, args=(ready, session), daemon=True)
        self._thread.start()
        if not ready.wait(timeout=_JOIN_TIMEOUT_S):
            raise RuntimeError("background test server failed to start in time")

    def _run(self, ready: threading.Event, session: Optional[GameSession]) -> None:
        asyncio.run(self._serve(ready, session))

    async def _serve(self, ready: threading.Event, session: Optional[GameSession]) -> None:
        game_server = GameServer(session=session)
        server = await websockets.serve(game_server.handle_connection, "localhost", 0)
        tick_task = asyncio.create_task(game_server.run_tick_loop())
        port = server.sockets[0].getsockname()[1]
        self.uri = f"ws://localhost:{port}"
        self._loop = asyncio.get_running_loop()
        self._stop_event = asyncio.Event()
        ready.set()

        await self._stop_event.wait()

        tick_task.cancel()
        server.close()
        await server.wait_closed()

    def stop(self) -> None:
        if self._loop is not None and self._stop_event is not None:
            self._loop.call_soon_threadsafe(self._stop_event.set)
        self._thread.join(timeout=_JOIN_TIMEOUT_S)


def _poll_until(runners, predicate, timeout_s: float) -> None:
    deadline = time.perf_counter() + timeout_s
    while time.perf_counter() < deadline:
        for runner in runners:
            runner.poll_and_process()
        if predicate():
            return
        time.sleep(_POLL_INTERVAL_S)


def test_a_real_king_interception_ends_the_game_for_both_network_clients():
    session = _king_interception_ready_session()
    test_server = _BackgroundTestServer(session=session)
    runner_white = NetworkGameLoopRunner(test_server.uri, headless=True)
    try:
        runner_black = NetworkGameLoopRunner(test_server.uri, headless=True)
        try:
            assert runner_white.assigned_color == Color.WHITE
            assert runner_black.assigned_color == Color.BLACK

            _poll_until(
                [runner_white, runner_black],
                lambda: runner_white.board is not None and runner_black.board is not None,
                _JOIN_TIMEOUT_S,
            )

            defender_cell = Position(row=0, col=0)
            attacker_cell = Position(row=0, col=1)

            # White (defender's owner) jumps its own pawn; Black
            # (attacker's owner, a KING) immediately sends its own king
            # toward the airborne cell - the King is destroyed instead of
            # capturing, and MUST end the game (fix/network-gameover-
            # and-king-interception's own Part A).
            runner_white.network_client.send_jump(Color.WHITE, PieceKind.PAWN, defender_cell)
            runner_black.network_client.send_move(Color.BLACK, PieceKind.KING, attacker_cell, defender_cell)

            def both_see_game_over() -> bool:
                return runner_white._game_over and runner_black._game_over

            _poll_until([runner_white, runner_black], both_see_game_over, timeout_s=5.0)

            assert runner_white._game_over is True
            assert runner_black._game_over is True
            # White's king was never touched - White is the winner.
            assert runner_white._game_over_winner_color is Color.WHITE
            assert runner_black._game_over_winner_color is Color.WHITE

            # Both clients must now refuse further input (Part B's
            # freeze-and-display design - see NetworkClickController's
            # own "GAME-OVER INPUT FREEZE" docstring section).
            assert runner_white.click_controller.game_over is True
            assert runner_black.click_controller.game_over is True

            # A click after game_over must not select anything - the
            # click_controller.game_over guard makes click() a no-op
            # (see NetworkClickController.click's own docstring).
            runner_white.click_controller.click(0, 0)
            assert runner_white.click_controller.selected is None
        finally:
            runner_black.close()
    finally:
        runner_white.close()
        test_server.stop()
