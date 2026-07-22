"""Real, end-to-end integration tests for Stage B7's real, event-driven
piece animation over the network (kungfu_chess/client/loop/
network_game_loop_runner.py's own "STAGE B7 - REAL EVENT-DRIVEN
ANIMATION" docstring section) - a real GameServer-backed server and a
real NetworkGameLoopRunner (headless=True, matching this project's own
established convention - see tests/integration/client/
test_network_game_loop_runner.py's own module docstring for why),
mirroring that file's own _BackgroundTestServer helper exactly (each
test file in this project stays self-contained, per established
precedent - test_initial_board_state_on_join.py's own docstring notes
the same thing).

NEW, SEPARATE test file (not an edit to the existing
test_network_game_loop_runner.py), matching this codebase's own
established "new behavior gets a new test file" convention (see
tests/unit/client/test_piece_animator_arrival_transition.py's own
docstring for the identical precedent).
"""

from __future__ import annotations

import asyncio
import threading
import time

import pytest
import websockets

from kungfu_chess.client.animation.animation_state import AnimationState
from kungfu_chess.client.events.game_events import MoveAccepted
from kungfu_chess.client.loop.network_game_loop_runner import NetworkGameLoopRunner
from kungfu_chess.io.board_printer import BoardPrinter
from kungfu_chess.model.color import Color
from kungfu_chess.model.piece import PieceKind
from kungfu_chess.model.position import Position
from kungfu_chess.notation.game_event_wire_format import MalformedGameEventWireFormatError, parse_game_event
from kungfu_chess.realtime.real_time_arbiter import MS_PER_SQUARE
from server.application.game_server import GameServer
from server.application.game_session import GameSession

_JOIN_TIMEOUT_S = 5.0
_POLL_INTERVAL_S = 0.05

_STARTING_BOARD_TEXT = BoardPrinter().print(GameSession().engine.board)


class _BackgroundTestServer:
    """Identical in shape to test_network_game_loop_runner.py's own
    _BackgroundTestServer - see that file's own docstring for the full
    reasoning (a real server on its own background thread + loop)."""

    def __init__(self) -> None:
        self.uri: str = ""
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop_event: asyncio.Event | None = None
        ready = threading.Event()
        self._thread = threading.Thread(target=self._run, args=(ready,), daemon=True)
        self._thread.start()
        if not ready.wait(timeout=_JOIN_TIMEOUT_S):
            raise RuntimeError("background test server failed to start in time")

    def _run(self, ready: threading.Event) -> None:
        asyncio.run(self._serve(ready))

    async def _serve(self, ready: threading.Event) -> None:
        game_server = GameServer()
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


def _poll_until(runner: NetworkGameLoopRunner, predicate, timeout_s: float) -> None:
    """Repeatedly call runner.poll_and_process() (real sleeps, real
    time) until predicate(runner) is True or timeout_s elapses - only
    the event-driven dispatch path is exercised here (never
    _run_one_frame/advance_all), since every assertion in this file is
    about STATE TRANSITIONS (on_event), which are entirely independent
    of advance()/advance_all() (re-verified directly against
    piece_animator.py: MOVE/JUMP entry and the PieceArrived-forced IDLE
    exit are both purely event-driven, never timing-inferred)."""

    deadline = time.perf_counter() + timeout_s
    while time.perf_counter() < deadline:
        runner.poll_and_process()
        if predicate(runner):
            return
        time.sleep(_POLL_INTERVAL_S)


def test_real_network_move_transitions_piece_animator_through_move_and_back_to_idle():
    test_server = _BackgroundTestServer()
    runner = NetworkGameLoopRunner(test_server.uri, headless=True)
    try:
        # Drain the join-time initial board-state broadcast - this is
        # what establishes runner.piece_animator_registry (Stage B7).
        _poll_until(runner, lambda r: r.piece_animator_registry is not None, _JOIN_TIMEOUT_S)

        e2 = Position(row=6, col=4)
        e4 = Position(row=4, col=4)
        piece_before = runner.board.piece_at(e2)
        assert piece_before is not None

        runner.network_client.send_move(Color.WHITE, PieceKind.PAWN, e2, e4)

        # Real, observed proof the wire-format MoveAccepted was
        # correctly translated (server piece_id -> this client's own
        # Piece) and forwarded to piece_animator_registry.on_event: the
        # SAME PieceAnimator this client built at construction actually
        # entered MOVE.
        seen_move_state = {"value": False}

        def saw_move_state(r: NetworkGameLoopRunner) -> bool:
            animator = r.piece_animator_registry.animator_for(piece_before.id)
            if animator.current_state == AnimationState.MOVE:
                seen_move_state["value"] = True
            return seen_move_state["value"]

        _poll_until(runner, saw_move_state, timeout_s=5.0)
        assert seen_move_state["value"], "animator never observed to enter MOVE - MoveAccepted translation/forwarding failed"

        # Real, observed proof the wire-format PieceArrived later forced
        # it back to IDLE, and the board position itself was updated in
        # place (same Piece object/id, not a fresh one from a resync).
        def arrived_and_idle(r: NetworkGameLoopRunner) -> bool:
            piece_now = r.board.piece_at(e4)
            if piece_now is None or piece_now.id != piece_before.id:
                return False
            return r.piece_animator_registry.animator_for(piece_before.id).current_state == AnimationState.IDLE

        timeout_s = (2 * MS_PER_SQUARE) / 1000 + 5.0
        _poll_until(runner, arrived_and_idle, timeout_s)

        assert runner.board.piece_at(e2) is None
        moved = runner.board.piece_at(e4)
        assert moved is not None and moved.id == piece_before.id
        assert runner.piece_animator_registry.animator_for(piece_before.id).current_state == AnimationState.IDLE
    finally:
        runner.close()
        test_server.stop()


def test_malformed_wire_format_event_message_does_not_crash_the_client():
    test_server = _BackgroundTestServer()
    runner = NetworkGameLoopRunner(test_server.uri, headless=True)
    try:
        _poll_until(runner, lambda r: r.board is not None, _JOIN_TIMEOUT_S)

        # Every one of these must be silently ignored, not raise -
        # matching this project's "malformed input never crashes the
        # process" convention (see _apply_wire_event's own docstring).
        runner._apply_wire_event("EVT:NONSENSE:garbage")
        runner._apply_wire_event("EVT:MOVE:not_an_int:e2:e4:1000")
        runner._apply_wire_event("EVT:MOVE:1:e2:e4")  # missing duration_ms
        runner._apply_wire_event("EVT:ARRIVED:1:e2:not_none_or_int")

        # The runner is still fully usable afterward - a real,
        # subsequent valid broadcast still works normally.
        runner.poll_and_process()
        assert runner.board is not None
    finally:
        runner.close()
        test_server.stop()


def test_parse_game_event_error_type_is_the_one_this_client_actually_catches():
    """A direct, pure check that _apply_wire_event's own try/except
    targets the real exception type parse_game_event raises - guards
    against the two silently drifting apart in the future. No server/
    runner needed - this is a fact about the wire-format module and
    NetworkGameLoopRunner's own except clause, not network behavior."""

    with pytest.raises(MalformedGameEventWireFormatError):
        parse_game_event("EVT:NONSENSE:garbage")


def test_a_later_board_text_resync_never_replaces_self_board_or_disrupts_an_in_flight_animator():
    test_server = _BackgroundTestServer()
    runner = NetworkGameLoopRunner(test_server.uri, headless=True)
    try:
        _poll_until(runner, lambda r: r.board is not None, _JOIN_TIMEOUT_S)
        original_board = runner.board
        piece = runner.board.piece_at(Position(row=6, col=4))
        assert piece is not None

        # Force this piece's animator into MOVE directly - a
        # deterministic stand-in for "genuinely mid-motion" (no real
        # network timing dependency for this specific assertion).
        runner.piece_animator_registry.on_event(
            MoveAccepted(piece_id=piece.id, from_cell=piece.cell, to_cell=Position(row=4, col=4), duration_ms=2000)
        )
        assert runner.piece_animator_registry.animator_for(piece.id).current_state == AnimationState.MOVE

        # A second, later board-text broadcast (a legitimate, MATCHING
        # resync - the exact same starting position) must not replace
        # self.board, must not replace this Piece's own identity, and
        # must not touch the in-flight animator at all.
        runner._apply_broadcast(_STARTING_BOARD_TEXT)

        assert runner.board is original_board
        assert runner.board.piece_at(Position(row=6, col=4)) is piece
        assert runner.piece_animator_registry.animator_for(piece.id).current_state == AnimationState.MOVE
    finally:
        runner.close()
        test_server.stop()


def test_log_resync_mismatch_prints_a_diagnostic_on_a_genuine_disagreement(capsys):
    test_server = _BackgroundTestServer()
    runner = NetworkGameLoopRunner(test_server.uri, headless=True)
    try:
        _poll_until(runner, lambda r: r.board is not None, _JOIN_TIMEOUT_S)

        # A synthetic resync that deliberately disagrees at e2 (says
        # empty, but this client's own real, locally-tracked board
        # still has White's pawn there) - used purely to prove a
        # genuine mismatch is DETECTED and LOGGED (never silently
        # swallowed, and never used to auto-correct self.board), not
        # to claim this ever happens with a real, correctly-functioning
        # server.
        mismatched_lines = _STARTING_BOARD_TEXT.splitlines()
        cells = mismatched_lines[6].split()
        cells[4] = "."
        mismatched_lines[6] = " ".join(cells)
        mismatched_text = "\n".join(mismatched_lines)

        runner._apply_broadcast(mismatched_text)

        captured = capsys.readouterr()
        assert "resync mismatch" in captured.out
        # And, per the policy, self.board itself is still untouched -
        # the real pawn is still there despite the mismatched broadcast.
        assert runner.board.piece_at(Position(row=6, col=4)) is not None
    finally:
        runner.close()
        test_server.stop()
