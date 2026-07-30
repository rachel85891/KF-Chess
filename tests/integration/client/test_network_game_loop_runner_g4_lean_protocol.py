"""Real, end-to-end integration test for Stage G4's lean wire protocol
(feature/g4-lean-wire-protocol, server/application/game_server.py's own
"STAGE G4" docstring section) - the full-script regression test this
stage's own task calls "the one that matters most": a client driven
PURELY by the new incremental BOARD_DELTA/LOG_DELTA deltas must end up
in the EXACT SAME final observable state as a client that instead
resynced to a fresh, full RESYNC_REQUEST baseline partway through the
SAME real match.

WHY THIS COMPARES TWO REAL CLIENTS OF THE SAME MATCH, NOT "OLD CODE vs.
NEW CODE": the old, per-event full-board/full-log broadcast this stage
replaces no longer exists anywhere in this codebase to run side-by-side
(see this stage's own task framing: "keeping the existing full-board/
full-log messages only as a RESYNC_REQUEST-triggered recovery path" -
the old design's own wire shape IS still produced, just only on
RESYNC_REQUEST now). A client that triggers a real RESYNC_REQUEST
partway through a match receives EXACTLY that old, full-resend wire
shape as its own fresh baseline - comparing ITS final state against a
second, real client that never resyncs at all (purely incremental
BOARD_DELTA/LOG_DELTA tracking, start to finish) is therefore a genuine,
faithful "does the new incremental path produce the identical result the
old full-resend path already guaranteed" proof, without needing the
retired code itself to still exist.

NEW, SEPARATE test file (not an edit to any existing
test_network_game_loop_runner*.py file), matching this codebase's own
established "new behavior gets a new test file" convention. Mirrors
test_network_game_loop_runner_state_snapshot.py's own
_BackgroundTestServer/session-injection/_capture_ready_session pattern.
"""

from __future__ import annotations

import asyncio
import threading
import time
from typing import Optional

import pytest
import websockets

from kungfu_chess.client.loop.network_game_loop_runner import NetworkGameLoopRunner
from kungfu_chess.client.network.network_game_client import NetworkGameClient
from kungfu_chess.model.board import Board
from kungfu_chess.model.color import Color
from kungfu_chess.model.piece import Piece, PieceKind
from kungfu_chess.model.position import Position
from kungfu_chess.notation.board_delta_wire_format import board_to_occupancy
from kungfu_chess.realtime.real_time_arbiter import MS_PER_SQUARE
from server.application.game_server import GameServer
from server.application.game_session import GameSession

# Marked slow: this file constructs a real, background-threaded/tasked
# server and relies on real wall-clock waiting (asyncio.sleep/time.sleep,
# real tick-loop cadence, or real network round trips) - excluded from
# `pytest -m "not slow"` for fast, deterministic day-to-day runs; still
# run in full via the dedicated slow/real-time pass.
pytestmark = pytest.mark.slow


_JOIN_TIMEOUT_S = 5.0
_POLL_INTERVAL_S = 0.05
_RESYNC_SEND_TIMEOUT_S = 5.0


class _BackgroundTestServer:
    """Identical in shape to test_network_game_loop_runner_state_
    snapshot.py's own _BackgroundTestServer."""

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
        kwargs = {"user_repository_db_path": ":memory:"}
        if session is not None:
            kwargs["session_factory"] = lambda: session
        game_server = GameServer(**kwargs)
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


def _construct_concurrently(uri: str, username: str, password: str) -> tuple[threading.Thread, list]:
    result: list[NetworkGameLoopRunner] = []

    def _construct() -> None:
        result.append(NetworkGameLoopRunner(uri, username=username, password=password, headless=True))

    thread = threading.Thread(target=_construct, daemon=True)
    thread.start()
    return thread, result


def _white_and_black(
    runner1: NetworkGameLoopRunner, runner2: NetworkGameLoopRunner
) -> tuple[NetworkGameLoopRunner, NetworkGameLoopRunner]:
    assert {runner1.assigned_color, runner2.assigned_color} == {Color.WHITE, Color.BLACK}
    if runner1.assigned_color == Color.WHITE:
        return runner1, runner2
    return runner2, runner1


def _poll_until(runner: NetworkGameLoopRunner, predicate, timeout_s: float) -> None:
    deadline = time.perf_counter() + timeout_s
    while time.perf_counter() < deadline:
        runner.poll_and_process()
        if predicate(runner):
            return
        time.sleep(_POLL_INTERVAL_S)


def _send_raw_text(client: NetworkGameClient, text: str) -> None:
    """Sends raw wire text directly over `client`'s own real connection
    - there is no public NetworkGameClient method for this (send_move/
    send_jump are the only real send primitives it exposes), so this
    test reaches into the same internals `_track_seq_and_maybe_resync`
    itself already uses, mirroring this project's own established
    white-box-test convention for this exact class (e.g.
    test_network_game_client.py's own direct `_last_seq` manipulation)."""

    future = asyncio.run_coroutine_threadsafe(client._connection.send(text), client._loop)
    future.result(timeout=_RESYNC_SEND_TIMEOUT_S)


def _empty_grid(rows: int, cols: int) -> list[list[None]]:
    return [[None for _ in range(cols)] for _ in range(rows)]


def _capture_ready_session() -> GameSession:
    """A white rook one square away from a black pawn - the minimum
    setup for a real, immediate, one-square capturing move (mirrors
    test_score_moveslog_timer_broadcast.py's own identical scenario)."""

    grid = _empty_grid(3, 3)
    mover = Piece(color=Color.WHITE, kind=PieceKind.ROOK, cell=Position(row=0, col=0))  # a8
    target = Piece(color=Color.BLACK, kind=PieceKind.PAWN, cell=Position(row=0, col=1))  # b8
    grid[0][0] = mover
    grid[0][1] = target
    return GameSession(board=Board(grid))


def test_a_client_that_resyncs_partway_through_ends_up_identical_to_one_that_never_drops_a_message():
    session = _capture_ready_session()
    test_server = _BackgroundTestServer(session=session)
    thread1, result1 = _construct_concurrently(test_server.uri, "runner1", "runner1_pw")
    thread2, result2 = _construct_concurrently(test_server.uri, "runner2", "runner2_pw")
    thread1.join(timeout=_JOIN_TIMEOUT_S)
    thread2.join(timeout=_JOIN_TIMEOUT_S)
    resynced_runner: Optional[NetworkGameLoopRunner] = None
    steady_runner: Optional[NetworkGameLoopRunner] = None
    try:
        # White will be the one that (artificially) drops a message and
        # resyncs; Black is the "steady", never-drops-anything baseline.
        resynced_runner, steady_runner = _white_and_black(result1[0], result2[0])
        _poll_until(resynced_runner, lambda r: r.board is not None, _JOIN_TIMEOUT_S)
        _poll_until(steady_runner, lambda r: r.board is not None, _JOIN_TIMEOUT_S)

        # a8 -> b8: a real, one-square, capturing rook move - the SAME
        # real match script test_score_moveslog_timer_broadcast.py's own
        # test_a_real_capture_broadcasts_the_correct_score_move_log_and_
        # advancing_elapsed_clock uses.
        resynced_runner.network_client.send_move(
            Color.WHITE, PieceKind.ROOK, Position(row=0, col=0), Position(row=0, col=1)
        )

        def capture_reflected(r: NetworkGameLoopRunner) -> bool:
            return r._latest_score.score_by_color.get(Color.WHITE, 0) > 0

        timeout_s = MS_PER_SQUARE / 1000 + 5.0
        _poll_until(resynced_runner, capture_reflected, timeout_s)
        _poll_until(steady_runner, capture_reflected, timeout_s)
        assert capture_reflected(resynced_runner)
        assert capture_reflected(steady_runner)

        # NOW simulate a dropped message on the "resynced" runner only:
        # a real RESYNC_REQUEST, sent directly over its own real
        # connection, and applied through the runner's own real,
        # unmodified poll_and_process/_apply_broadcast/_apply_state_
        # snapshot dispatch - exactly the same code path a genuine
        # seq-gap would have triggered via NetworkGameClient itself.
        _send_raw_text(resynced_runner.network_client, "RESYNC_REQUEST")

        # A fixed, real wait for the resync round trip (request sent,
        # server responds with the full board-text + "STATE:" baseline,
        # this runner's own poll_and_process applies both) to complete -
        # generous relative to a real localhost round trip.
        _poll_until(resynced_runner, lambda _r: False, 2.0)

        # THE REGRESSION PROOF: `resynced_runner` (self._board_occupancy/
        # self._latest_log rebuilt from a fresh, full RESYNC_REQUEST
        # baseline) and `steady_runner` (self._board_occupancy/self.
        # _latest_log built ENTIRELY from incremental BOARD_DELTA/
        # LOG_DELTA messages, never resynced) must be byte-for-byte/
        # field-for-field identical - proving the new incremental path
        # produces exactly what the old full-resend path already
        # guaranteed, invisible in outcome, only smaller on the wire.
        assert resynced_runner._board_occupancy == steady_runner._board_occupancy
        assert resynced_runner._latest_log.entries == steady_runner._latest_log.entries
        assert resynced_runner._latest_score == steady_runner._latest_score

        # self.board (EVT:-driven, never touched by BOARD_DELTA/resync at
        # all - see module docstring's "STAGE G4" section) stays
        # consistent with the freshly-resynced occupancy grid too - no
        # `_log_resync_mismatch` diagnostic would have had anything real
        # to report.
        assert board_to_occupancy(resynced_runner.board) == resynced_runner._board_occupancy
    finally:
        if resynced_runner is not None:
            resynced_runner.close()
        if steady_runner is not None:
            steady_runner.close()
        test_server.stop()
