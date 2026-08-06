"""Unit-level tests for Stage I4's connection-cap safety valve
(server/application/game_server.py's own new `max_connections`
constructor parameter + `handle_connection`'s new, very-first cap
check) - GameServer is constructed and driven DIRECTLY here (no
websockets.serve, no real network socket at all), mirroring Stage G1's
own already-established pattern of reading
`game_server._connection_manager.connection_count` straight off a
directly-constructed GameServer instance (see
tests/integration/server/test_auth_protocol.py's own identical
`game_server._connection_manager.connection_count` assertion) - just
taken one step further here: this stage's own "Test-Run Efficiency
Policy" explicitly calls out that a connection cap is testable
synchronously against a GameServer/ConnectionManager instance directly,
with no real network round-trip required at all, so this file drives
`GameServer.handle_connection` with a plain in-process test double
instead of a real websockets client/server pair - the SERVER-side
counterpart to test_network_game_client.py's own client-side
`_FakeConnection` convention (Stage G4), which this project had no
equivalent of yet.

NOT marked `slow` (see pytest.ini's own marker description: "sleep/wait
on real wall-clock time - real server, real tick loop, or real network
round trips"): no real network socket is ever opened here, and no
scenario below waits out a designed timeout/countdown - the only real
wall-clock cost is genuine PBKDF2 password-hashing compute time
(server/persistence/user_repository.py's own deliberately-slow-by-
design cost, real and not mocked, per this stage's own "two real,
successful AUTH'd connections" requirement) plus a short, bounded poll
(`_wait_until_connection_count`, below) synchronizing this test with
those concurrently-running filler connections - not a sleep guessing at
a fixed duration.
"""

from __future__ import annotations

import asyncio

from kungfu_chess.notation.auth_command_format import format_auth_command
from server.application.game_server import GameServer
from server.presentation.protocol_handler import SERVER_FULL_MESSAGE

_POLL_TIMEOUT_S = 10.0
_POLL_INTERVAL_S = 0.005
# A bound on the one call this file cares most about proving is FAST
# (the rejected connection's own handle_connection call) - not a
# designed wait, purely a safety net so a broken/missing cap check
# fails this test quickly with a clear TimeoutError instead of hanging
# the whole suite forever (without the cap check, a rejected connection
# with no further scripted messages would otherwise block indefinitely
# on its own room-choice recv(), exactly like a real idle connection
# would - this is precisely the bug this bound exists to catch, not
# something to design around by scripting more messages).
_REJECTED_CALL_TIMEOUT_S = 5.0


class _FakeServerConnection:
    """A minimal stand-in for a real websockets ServerConnection - only
    recv/send/close are ever touched by GameServer.handle_connection, so
    only those are faked here (mirrors test_network_game_client.py's own
    client-side `_FakeConnection` "only fake what's actually called"
    convention).

    Scripted incoming messages (`incoming`) are returned by `recv()` one
    at a time, in order. Once exhausted, `recv()` blocks forever instead
    of raising - mirroring a real, still-open connection that simply
    hasn't sent anything further yet (the exact shape a filler
    connection parked mid-handshake, waiting on its own room-choice
    message, needs for this stage's own cap tests below).
    """

    def __init__(self, incoming: "list[str] | None" = None) -> None:
        self._incoming = list(incoming) if incoming else []
        self.sent: "list[str]" = []
        self.closed = False
        self.recv_call_count = 0

    async def recv(self) -> str:
        self.recv_call_count += 1
        if self._incoming:
            return self._incoming.pop(0)
        # No more scripted messages - block forever, never raise, never
        # return: a genuinely idle-but-still-open real connection.
        await asyncio.Event().wait()
        raise AssertionError("unreachable")  # pragma: no cover

    async def send(self, text: str) -> None:
        self.sent.append(text)

    async def close(self) -> None:
        self.closed = True


class _NeverReadServerConnection:
    """A STRICTER double than `_FakeServerConnection` above, used only
    for the one test that must prove the cap check runs before ANY
    attempt to read from the connection at all - `recv()` raises
    immediately if ever called, rather than merely being counted. A
    connection this cheap to reject shouldn't even need scripted
    content: whatever would have come next (a real AUTH command, a
    malformed one, or nothing at all before the client vanished) must
    not matter, since the cap check must reject it before recv() is
    ever awaited even once."""

    def __init__(self) -> None:
        self.sent: "list[str]" = []
        self.closed = False

    async def recv(self) -> str:
        raise AssertionError(
            "handle_connection called recv() on a connection that should "
            "have been rejected by the max_connections cap check BEFORE "
            "ever attempting to read anything from it"
        )

    async def send(self, text: str) -> None:
        self.sent.append(text)

    async def close(self) -> None:
        self.closed = True


async def _wait_until_connection_count(game_server: GameServer, target: int) -> None:
    """Poll `game_server`'s own `_connection_manager.connection_count`
    until it reaches `target` - real PBKDF2 hashing (offloaded to
    GameServer's own single persistent worker thread) means a filler
    connection's own AUTH finishes at a real, if small, unpredictable
    delay; a short, bounded poll is the correct synchronization tool
    here, not a fixed sleep guess and not a real designed timeout being
    waited out (contrast this project's own established
    matchmaking_timeout_s/disconnect_countdown_s `slow` tests)."""

    loop = asyncio.get_event_loop()
    deadline = loop.time() + _POLL_TIMEOUT_S
    while game_server._connection_manager.connection_count < target:
        if loop.time() >= deadline:
            raise AssertionError(
                f"connection_count never reached {target} within "
                f"{_POLL_TIMEOUT_S}s (stuck at "
                f"{game_server._connection_manager.connection_count})"
            )
        await asyncio.sleep(_POLL_INTERVAL_S)


async def _cancel_and_await(*tasks: "asyncio.Task") -> None:
    for task in tasks:
        task.cancel()
    for task in tasks:
        try:
            await task
        except asyncio.CancelledError:
            pass


def test_a_connection_beyond_the_configured_cap_is_rejected_with_server_full_and_closed():
    async def scenario():
        game_server = GameServer(user_repository_db_path=":memory:", max_connections=2)

        filler_a = _FakeServerConnection([format_auth_command("filler_alice", "correct horse battery staple")])
        filler_b = _FakeServerConnection([format_auth_command("filler_bob", "another real password")])
        task_a = asyncio.create_task(game_server.handle_connection(filler_a))
        task_b = asyncio.create_task(game_server.handle_connection(filler_b))
        try:
            await _wait_until_connection_count(game_server, 2)

            # The third connection HAS a valid scripted AUTH message
            # ready to go (proving it would have authenticated
            # successfully if given the chance) - it is still rejected,
            # and never even reads that message: recv_call_count stays 0.
            # wait_for, not a bare await: without the cap check, this
            # connection would otherwise sail through AUTH and then
            # block forever on its own room-choice recv() - see
            # _REJECTED_CALL_TIMEOUT_S's own docstring for why.
            rejected = _FakeServerConnection([format_auth_command("filler_carol", "yet another real password")])
            await asyncio.wait_for(game_server.handle_connection(rejected), timeout=_REJECTED_CALL_TIMEOUT_S)

            assert rejected.sent == [SERVER_FULL_MESSAGE]
            assert rejected.closed is True
            assert rejected.recv_call_count == 0
            assert game_server._connection_manager.connection_count == 2
        finally:
            await _cancel_and_await(task_a, task_b)

    asyncio.run(scenario())


def test_the_cap_check_runs_before_auth_is_ever_read_so_a_missing_auth_message_never_matters():
    async def scenario():
        game_server = GameServer(user_repository_db_path=":memory:", max_connections=1)

        filler = _FakeServerConnection([format_auth_command("solo_filler", "correct horse battery staple")])
        task = asyncio.create_task(game_server.handle_connection(filler))
        try:
            await _wait_until_connection_count(game_server, 1)

            # This connection's own recv() raises immediately if ever
            # called at all - proving definitively that the cap check
            # happens strictly before any AUTH read is even attempted,
            # not merely before a successful one.
            rejected = _NeverReadServerConnection()
            await game_server.handle_connection(rejected)

            assert rejected.sent == [SERVER_FULL_MESSAGE]
            assert rejected.closed is True
            assert game_server._connection_manager.connection_count == 1
        finally:
            await _cancel_and_await(task)

    asyncio.run(scenario())


def test_max_connections_none_is_the_default_and_preserves_unlimited_connections():
    async def scenario():
        game_server = GameServer(user_repository_db_path=":memory:")
        assert game_server._max_connections is None

        connections = [
            _FakeServerConnection([format_auth_command(f"unlimited_user_{i}", "a real password")]) for i in range(5)
        ]
        tasks = [asyncio.create_task(game_server.handle_connection(c)) for c in connections]
        try:
            await _wait_until_connection_count(game_server, 5)

            assert game_server._connection_manager.connection_count == 5
            for connection in connections:
                assert SERVER_FULL_MESSAGE not in connection.sent
                assert connection.closed is False
        finally:
            await _cancel_and_await(*tasks)

    asyncio.run(scenario())
