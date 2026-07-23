"""Tests for Stage B7.5's client-side pixel-position sliding
(kungfu_chess/client/loop/network_game_loop_runner.py's own "STAGE
B7.5 - CLIENT-SIDE PIXEL SLIDING" docstring section) - a real
GameServer-backed server and a real NetworkGameLoopRunner (headless),
mirroring test_network_game_loop_runner_animation.py's own
_BackgroundTestServer helper exactly (each test file in this project
stays self-contained, per established precedent).

Constructing a NetworkGameLoopRunner always requires a real WS
connection (by design - there is no lighter-weight construction path),
even for the deterministic, fake-clock-driven progress tests below -
matching this project's own strong "real, running instances, never
mocked" testing convention throughout the server track.

NEW, SEPARATE test file (not an edit to test_network_game_loop_runner_
animation.py), matching this codebase's own established "new behavior
gets a new test file" convention.

UPDATED for Stage E1's real matchmaking (feature/matchmaking-elo-
queue-e1): see test_network_game_loop_runner.py's own "UPDATED for
Stage E1" docstring section for the full reasoning. The 4 fake-clock-
driven progress tests below never send a real move (they manipulate
_active_motions directly), so a throwaway dummy opponent unblocks
their real matchmaking wait regardless of which color it results in;
the 2 tests that send a real WHITE-specific move construct two real
runners concurrently and pick whichever ended up WHITE.
"""

from __future__ import annotations

import asyncio
import threading
import time

import websockets

from kungfu_chess.client.loop.network_game_loop_runner import NetworkGameLoopRunner, _ClientMotion
from kungfu_chess.client.network.network_game_client import NetworkGameClient
from kungfu_chess.io.board_printer import BoardPrinter
from kungfu_chess.model.color import Color
from kungfu_chess.model.piece import PieceKind
from kungfu_chess.model.position import Position
from kungfu_chess.realtime.real_time_arbiter import MS_PER_SQUARE
from server.application.game_server import GameServer
from server.application.game_session import GameSession

_JOIN_TIMEOUT_S = 5.0
_POLL_INTERVAL_S = 0.05

_STARTING_BOARD_TEXT = BoardPrinter().print(GameSession().engine.board)


class _FakeClock:
    """A controllable, injectable time source (Stage B7.5's own
    `clock: Callable[[], float]` constructor parameter) - a plain
    callable object whose `.value` a test bumps directly, instead of a
    real time.sleep, matching this project's own general "inject the
    thing that varies" convention (see network_game_loop_runner.py's
    own module docstring, "STAGE B7.5" section, for the precedent this
    follows)."""

    def __init__(self, start: float = 0.0) -> None:
        self.value = start

    def __call__(self) -> float:
        return self.value


class _BackgroundTestServer:
    """Identical in shape to test_network_game_loop_runner_animation.py's
    own _BackgroundTestServer."""

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
        game_server = GameServer(user_repository_db_path=":memory:")
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


def _start_dummy_opponent(uri: str, username: str) -> tuple[NetworkGameClient, threading.Thread]:
    """Starts (but does not wait for) a throwaway, same-rated dummy
    opponent connecting on a background thread - must be started BEFORE
    constructing the real runner under test - see
    test_network_game_loop_runner.py's own identically-named helper for
    the full reasoning."""

    dummy = NetworkGameClient()
    dummy_thread = threading.Thread(
        target=dummy.connect, args=(uri, f"{username}_dummy_opponent", "dummy password"), daemon=True
    )
    dummy_thread.start()
    return dummy, dummy_thread


def _construct_concurrently(uri: str, username: str, password: str) -> tuple[threading.Thread, list]:
    """Constructs a NetworkGameLoopRunner on its own background thread -
    see test_network_game_loop_runner.py's own identically-named helper
    for the full reasoning."""

    result: list[NetworkGameLoopRunner] = []

    def _construct() -> None:
        result.append(NetworkGameLoopRunner(uri, username=username, password=password, headless=True))

    thread = threading.Thread(target=_construct, daemon=True)
    thread.start()
    return thread, result


def _white_and_black(
    runner1: NetworkGameLoopRunner, runner2: NetworkGameLoopRunner
) -> tuple[NetworkGameLoopRunner, NetworkGameLoopRunner]:
    """Returns (white_runner, black_runner) - color assignment is queue-
    order-driven, not construction-order-driven, so which of two
    concurrently-connecting runners is WHITE is genuinely racy."""

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


# --- Deterministic, fake-clock-driven progress tests (no real sleep) ---


def test_progress_is_zero_right_when_a_motion_starts():
    fake_clock = _FakeClock(start=100.0)
    test_server = _BackgroundTestServer()
    dummy, dummy_thread = _start_dummy_opponent(test_server.uri, "runner")
    runner = NetworkGameLoopRunner(test_server.uri, username="runner", password="runner_pw", headless=True, clock=fake_clock)
    try:
        dummy_thread.join(timeout=_JOIN_TIMEOUT_S)
        runner._active_motions[42] = _ClientMotion(
            from_cell=Position(row=0, col=0), to_cell=Position(row=0, col=4), duration_ms=2000, started_at=fake_clock.value
        )

        motions = runner._compute_motions_for_rendering()

        assert motions[42].progress == 0.0
        assert motions[42].from_cell == Position(row=0, col=0)
        assert motions[42].to_cell == Position(row=0, col=4)
    finally:
        runner.close()
        dummy.close()
        test_server.stop()


def test_progress_is_approximately_half_partway_through_duration():
    fake_clock = _FakeClock(start=0.0)
    test_server = _BackgroundTestServer()
    dummy, dummy_thread = _start_dummy_opponent(test_server.uri, "runner")
    runner = NetworkGameLoopRunner(test_server.uri, username="runner", password="runner_pw", headless=True, clock=fake_clock)
    try:
        dummy_thread.join(timeout=_JOIN_TIMEOUT_S)
        runner._active_motions[7] = _ClientMotion(
            from_cell=Position(row=0, col=0), to_cell=Position(row=0, col=4), duration_ms=2000, started_at=0.0
        )

        fake_clock.value = 1.0  # 1000ms of a 2000ms motion = exactly half

        motions = runner._compute_motions_for_rendering()

        assert motions[7].progress == 0.5
    finally:
        runner.close()
        dummy.close()
        test_server.stop()


def test_progress_is_one_at_exactly_full_duration():
    fake_clock = _FakeClock(start=0.0)
    test_server = _BackgroundTestServer()
    dummy, dummy_thread = _start_dummy_opponent(test_server.uri, "runner")
    runner = NetworkGameLoopRunner(test_server.uri, username="runner", password="runner_pw", headless=True, clock=fake_clock)
    try:
        dummy_thread.join(timeout=_JOIN_TIMEOUT_S)
        runner._active_motions[7] = _ClientMotion(
            from_cell=Position(row=0, col=0), to_cell=Position(row=0, col=4), duration_ms=2000, started_at=0.0
        )

        fake_clock.value = 2.0  # exactly 2000ms elapsed

        motions = runner._compute_motions_for_rendering()

        assert motions[7].progress == 1.0
    finally:
        runner.close()
        dummy.close()
        test_server.stop()


def test_progress_clamps_at_one_when_real_elapsed_time_overshoots_duration_before_arrival():
    """Requirement 6's explicit overshoot case: real network latency
    could mean PieceArrived hasn't been processed yet even though more
    real time than duration_ms has already elapsed - progress must
    clamp at 1.0 (piece visually parked at destination), never
    overshoot or oscillate past it."""

    fake_clock = _FakeClock(start=0.0)
    test_server = _BackgroundTestServer()
    dummy, dummy_thread = _start_dummy_opponent(test_server.uri, "runner")
    runner = NetworkGameLoopRunner(test_server.uri, username="runner", password="runner_pw", headless=True, clock=fake_clock)
    try:
        dummy_thread.join(timeout=_JOIN_TIMEOUT_S)
        runner._active_motions[7] = _ClientMotion(
            from_cell=Position(row=0, col=0), to_cell=Position(row=0, col=4), duration_ms=2000, started_at=0.0
        )

        fake_clock.value = 10.0  # 10000ms elapsed, 5x the motion's own 2000ms duration

        motions = runner._compute_motions_for_rendering()

        assert motions[7].progress == 1.0
    finally:
        runner.close()
        dummy.close()
        test_server.stop()


def test_a_piece_arrived_removes_its_own_active_motion_so_it_no_longer_slides():
    test_server = _BackgroundTestServer()
    thread1, result1 = _construct_concurrently(test_server.uri, "runner1", "runner1_pw")
    thread2, result2 = _construct_concurrently(test_server.uri, "runner2", "runner2_pw")
    thread1.join(timeout=_JOIN_TIMEOUT_S)
    thread2.join(timeout=_JOIN_TIMEOUT_S)
    other_runner = None
    try:
        runner, other_runner = _white_and_black(result1[0], result2[0])
        _poll_until(runner, lambda r: r.board is not None, _JOIN_TIMEOUT_S)

        e2 = Position(row=6, col=4)
        e4 = Position(row=4, col=4)
        piece_before = runner.board.piece_at(e2)
        assert piece_before is not None

        runner.network_client.send_move(Color.WHITE, PieceKind.PAWN, e2, e4)

        _poll_until(runner, lambda r: piece_before.id in r._active_motions, timeout_s=5.0)
        assert piece_before.id in runner._active_motions

        timeout_s = (2 * MS_PER_SQUARE) / 1000 + 5.0
        _poll_until(runner, lambda r: r.board.piece_at(e4) is not None and r.board.piece_at(e4).id == piece_before.id, timeout_s)

        assert piece_before.id not in runner._active_motions
    finally:
        if other_runner is not None:
            other_runner.close()
        runner.close()
        test_server.stop()


# --- Real, end-to-end network test: a moved piece genuinely renders
# partway between source and destination before finally arriving ---


def test_real_network_move_renders_a_genuinely_interpolated_mid_flight_pixel_position():
    test_server = _BackgroundTestServer()
    thread1, result1 = _construct_concurrently(test_server.uri, "runner1", "runner1_pw")
    thread2, result2 = _construct_concurrently(test_server.uri, "runner2", "runner2_pw")
    thread1.join(timeout=_JOIN_TIMEOUT_S)
    thread2.join(timeout=_JOIN_TIMEOUT_S)
    other_runner = None
    try:
        runner, other_runner = _white_and_black(result1[0], result2[0])
        _poll_until(runner, lambda r: r.board is not None, _JOIN_TIMEOUT_S)

        e2 = Position(row=6, col=4)
        e4 = Position(row=4, col=4)  # 2-square move -> 2 * MS_PER_SQUARE ms
        piece_before = runner.board.piece_at(e2)
        assert piece_before is not None

        runner.network_client.send_move(Color.WHITE, PieceKind.PAWN, e2, e4)

        _poll_until(runner, lambda r: piece_before.id in r._active_motions, timeout_s=5.0)

        # Sample the interpolated position at several real points in
        # time during the real motion - a genuine, observed, strictly
        # increasing (never decreasing) progression from 0 toward 1,
        # not just a snap at either end.
        observed_progress_values = []
        deadline = time.perf_counter() + (2 * MS_PER_SQUARE) / 1000 + 5.0
        while time.perf_counter() < deadline:
            runner.poll_and_process()
            motions = runner._compute_motions_for_rendering()
            if piece_before.id in motions:
                observed_progress_values.append(motions[piece_before.id].progress)
            elif observed_progress_values:
                break  # motion completed (removed from active_motions) - stop sampling
            time.sleep(0.05)

        assert len(observed_progress_values) >= 2, "not enough samples observed during the real motion"
        assert any(0.0 < p < 1.0 for p in observed_progress_values), (
            f"never observed a genuinely in-flight (0 < progress < 1) sample: {observed_progress_values}"
        )
        # Never decreases (a real, monotonic slide, not jitter/oscillation).
        assert observed_progress_values == sorted(observed_progress_values)

        # And, finally, the arrival is fully reflected - the piece
        # really did reach its destination.
        assert runner.board.piece_at(e2) is None
        moved = runner.board.piece_at(e4)
        assert moved is not None and moved.id == piece_before.id
    finally:
        if other_runner is not None:
            other_runner.close()
        runner.close()
        test_server.stop()
