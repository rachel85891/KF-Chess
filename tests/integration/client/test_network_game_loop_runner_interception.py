"""Real, end-to-end integration test for fix/interception-event-and-
network-removal - the CORE regression test proving the originally
reported bug is fixed: a real jump interception over the network must
remove the destroyed attacker from BOTH connected NetworkGameLoopRunner
instances' own Board and _active_motions state, not just the server's
own authoritative one (which already looked correct locally, by
accident, since it never went through this client-side path at all).

Mirrors tests/integration/client/test_network_game_loop_runner_jump_
cooldown.py's own _BackgroundTestServer pattern, extended with an
optional injected GameSession (mirroring tests/integration/server/
test_score_moveslog_timer_broadcast.py's own session-injection pattern)
so a small, custom board with an immediate interception scenario can be
used - the EXACT scenario tests/unit/test_jump.py's own
test_enemy_move_targeting_airborne_cell_results_in_attacker_destroyed_
defender_untouched already establishes, reused here rather than
inventing a new one, per this fix's own requirement.

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
from kungfu_chess.realtime.real_time_arbiter import MS_PER_SQUARE
from server.application.game_server import GameServer
from server.application.game_session import GameSession

_JOIN_TIMEOUT_S = 5.0
_POLL_INTERVAL_S = 0.05


def _empty_grid(rows: int, cols: int) -> list[list[None]]:
    return [[None for _ in range(cols)] for _ in range(rows)]


def _interception_ready_session() -> GameSession:
    """The exact scenario tests/unit/test_jump.py's own
    test_enemy_move_targeting_airborne_cell_results_in_attacker_
    destroyed_defender_untouched already establishes: a white pawn
    (defender) about to jump at its own cell, a black rook (attacker)
    three squares away that will move toward that same cell."""

    grid = _empty_grid(4, 4)
    defender = Piece(color=Color.WHITE, kind=PieceKind.PAWN, cell=Position(row=0, col=0))
    attacker = Piece(color=Color.BLACK, kind=PieceKind.ROOK, cell=Position(row=0, col=3))
    grid[0][0] = defender
    grid[0][3] = attacker
    return GameSession(board=Board(grid))


class _BackgroundTestServer:
    """Identical in shape to test_network_game_loop_runner_jump_
    cooldown.py's own _BackgroundTestServer, extended with an optional
    injected GameSession (mirrors test_score_moveslog_timer_broadcast.py's
    own session-injection pattern) so this test can seed a small,
    custom board with an immediate interception scenario."""

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


def test_a_real_jump_interception_removes_the_attacker_from_both_network_clients():
    session = _interception_ready_session()
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

            defender_cell = Position(row=0, col=0)  # a8
            attacker_cell = Position(row=0, col=3)  # d8

            # Each client independently parsed its OWN Board/piece_id
            # space (re-verified directly, PROBLEM 1's own reasoning) -
            # the "same" attacker has a DIFFERENT id on each client, so
            # each is captured separately here rather than assuming a
            # shared id.
            attacker_before_white = runner_white.board.piece_at(attacker_cell)
            attacker_before_black = runner_black.board.piece_at(attacker_cell)
            assert attacker_before_white is not None
            assert attacker_before_black is not None
            assert runner_white.board.piece_at(defender_cell) is not None
            assert runner_black.board.piece_at(defender_cell) is not None

            # White (defender's owner) jumps its own pawn; Black
            # (attacker's owner) immediately sends its own rook toward
            # the airborne cell - the exact scenario
            # tests/unit/test_jump.py's own established interception
            # test already exercises, reproduced here over the real
            # network.
            runner_white.network_client.send_jump(Color.WHITE, PieceKind.PAWN, defender_cell)
            runner_black.network_client.send_move(Color.BLACK, PieceKind.ROOK, attacker_cell, defender_cell)

            # First, prove the ORIGINALLY REPORTED symptom's own
            # precondition genuinely occurs: the attacker's own
            # MoveAccepted really is tracked as an active client-side
            # motion on both clients (Stage B7.5) - before this fix, it
            # would have stayed there FOREVER, since no PieceArrived was
            # ever coming for it.
            _poll_until(
                [runner_white, runner_black],
                lambda: (
                    attacker_before_white.id in runner_white._active_motions
                    and attacker_before_black.id in runner_black._active_motions
                ),
                timeout_s=5.0,
            )
            assert attacker_before_white.id in runner_white._active_motions
            assert attacker_before_black.id in runner_black._active_motions

            def attacker_gone_from_both() -> bool:
                white_gone = runner_white.board.piece_at(attacker_cell) is None
                black_gone = runner_black.board.piece_at(attacker_cell) is None
                white_no_motion = attacker_before_white.id not in runner_white._active_motions
                black_no_motion = attacker_before_black.id not in runner_black._active_motions
                return white_gone and black_gone and white_no_motion and black_no_motion

            timeout_s = MS_PER_SQUARE / 1000 + 5.0
            _poll_until([runner_white, runner_black], attacker_gone_from_both, timeout_s)

            assert attacker_gone_from_both(), "attacker was not removed from both clients' own Board/_active_motions"

            # The defender is the only piece left on that square,
            # correctly still present and untouched (an interception
            # destroys the ATTACKER, never the defender).
            defender_after_white = runner_white.board.piece_at(defender_cell)
            defender_after_black = runner_black.board.piece_at(defender_cell)
            assert defender_after_white is not None and defender_after_white.kind is PieceKind.PAWN
            assert defender_after_black is not None and defender_after_black.kind is PieceKind.PAWN
        finally:
            runner_black.close()
    finally:
        runner_white.close()
        test_server.stop()
