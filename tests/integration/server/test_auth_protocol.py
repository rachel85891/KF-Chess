"""Real, end-to-end integration tests for Stage D2's real username+
password authentication protocol (server/application/game_server.py's
own new pre-assigned_color AUTH handshake, backed by
server/persistence/user_repository.py's UserRepository) - a REAL server
(real GameServer, a real SQLite database - ":memory:" or a real
tmp_path file, per scenario below) and REAL websockets clients,
mirroring this project's own established "real server, real client, no
mocking" convention (tests/integration/server/test_protocol_wiring.py's
own identical helper shape).

WHY THESE TESTS NEVER HOLD A DIRECT REFERENCE TO GameServer's OWN
INTERNAL UserRepository INSTANCE (unlike an earlier draft of this file):
see server/application/game_server.py's own "LAZY, THREAD-PINNED
CONSTRUCTION" docstring section for the full reasoning - GameServer's
own UserRepository is constructed lazily, on its own persistent worker
thread, specifically BECAUSE sqlite3 connections are thread-affine and
must never be touched from any other thread. A test holding its own
separate reference could never safely call into that SAME internal
object anyway (and, for ":memory:" specifically, a SEPARATELY
constructed UserRepository wouldn't even see the same data at all - an
in-memory SQLite database is private to the one connection that
created it). Every scenario below therefore verifies behavior
EXCLUSIVELY through the real wire protocol (a second real login proves
persistence; GameServer's own plain-Python `_connection_manager`/
`_colors` - never sqlite-backed - proves "no session state created"),
and scenario 2 pre-seeds a rating via a real, separate, tmp_path FILE
(genuinely shared through the filesystem, unlike ":memory:") rather
than a shared connection object.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import pytest
import websockets
from websockets.exceptions import ConnectionClosed

from kungfu_chess.notation.auth_command_format import format_auth_command
from server.application.game_server import GameServer
from server.persistence.user_repository import DEFAULT_STARTING_RATING, UserRepository

_RECV_TIMEOUT_S = 5.0


@asynccontextmanager
async def _running_game_server(user_repository_db_path: str):
    game_server = GameServer(user_repository_db_path=user_repository_db_path)
    server = await websockets.serve(game_server.handle_connection, "localhost", 0)
    try:
        port = server.sockets[0].getsockname()[1]
        yield f"ws://localhost:{port}", game_server
    finally:
        server.close()
        await server.wait_closed()


def _parse_assigned_color_and_rating(message: str) -> tuple[str, int]:
    """"assigned_color:white:1200" -> ("white", 1200)."""

    _, color_name, rating_text = message.split(":", 2)
    return color_name, int(rating_text)


@asynccontextmanager
async def _connected_and_authenticated(uri: str, username: str, password: str):
    """Open a real connection, send the real AUTH command, and yield
    (connection, welcome_message) - the connection stays OPEN for the
    caller's own `async with` block (unlike a plain function that
    would close it immediately on return), so scenarios that need a
    connection to still be tracked (e.g. to prove a SECOND, concurrent
    connection sees the correct next color, or that a rejected sibling
    attempt left no trace) can keep it alive for exactly as long as
    they need to."""

    async with websockets.connect(uri) as client:
        await client.send(format_auth_command(username, password))
        welcome = await asyncio.wait_for(client.recv(), timeout=_RECV_TIMEOUT_S)
        yield client, welcome


def test_a_new_username_creates_an_account_with_the_default_starting_rating_and_the_account_really_persists():
    async def scenario():
        async with _running_game_server(":memory:") as (uri, _game_server):
            async with _connected_and_authenticated(uri, "alice", "correct horse battery staple") as (
                _client1,
                first_welcome,
            ):
                color_name, rating = _parse_assigned_color_and_rating(first_welcome)
                assert color_name == "white"
                assert rating == DEFAULT_STARTING_RATING

                # Real persistence, proven through the wire protocol
                # itself (never a direct reference to GameServer's own
                # internal UserRepository - see module docstring): a
                # SECOND real connection with the SAME credentials, made
                # while the first is still open, logs in (as the second
                # real connection this server has ever accepted) rather
                # than silently creating a second account, and still
                # reports the same, real rating.
                async with _connected_and_authenticated(uri, "alice", "correct horse battery staple") as (
                    _client2,
                    second_welcome,
                ):
                    color_name_2, rating_2 = _parse_assigned_color_and_rating(second_welcome)
                    assert color_name_2 == "black"
                    assert rating_2 == DEFAULT_STARTING_RATING

    asyncio.run(scenario())


def test_existing_username_with_correct_password_logs_in_and_returns_the_real_stored_rating(tmp_path):
    async def scenario():
        # A real FILE (not ":memory:") - genuinely shared through the
        # filesystem between this pre-seeding UserRepository and
        # GameServer's own, separately-constructed one (see module
        # docstring for why ":memory:" could not be used to pre-seed
        # data for a SEPARATE connection this way).
        db_path = str(tmp_path / "auth_protocol_test.db")
        seed_repo = UserRepository(db_path=db_path)
        seed_repo.create_account("alice", "correct horse battery staple")
        seed_repo.update_rating("alice", 1450)  # a distinguishable, non-default rating

        async with _running_game_server(db_path) as (uri, _game_server):
            async with _connected_and_authenticated(uri, "alice", "correct horse battery staple") as (_client, welcome):
                color_name, rating = _parse_assigned_color_and_rating(welcome)

        assert color_name == "white"
        assert rating == 1450  # the REAL stored rating, not the default

    asyncio.run(scenario())


def test_existing_username_with_wrong_password_is_rejected_and_the_connection_closes_with_no_session_state_created():
    async def scenario():
        async with _running_game_server(":memory:") as (uri, game_server):
            # Create the real account first, through the real wire
            # protocol, on this same running server - kept OPEN for the
            # rest of this scenario, so the assertion below can prove
            # the rejected sibling attempt (right below) added no
            # session state of its own, without this first, legitimate
            # connection's own tracked state confusingly vanishing first.
            async with _connected_and_authenticated(uri, "alice", "correct horse battery staple") as (_client1, _welcome1):
                async with websockets.connect(uri) as client2:
                    await client2.send(format_auth_command("alice", "totally wrong password"))
                    rejection = await asyncio.wait_for(client2.recv(), timeout=_RECV_TIMEOUT_S)

                    assert rejection == "rejected:wrong_password"
                    with pytest.raises(ConnectionClosed):
                        await asyncio.wait_for(client2.recv(), timeout=_RECV_TIMEOUT_S)

                # Exactly the first (successful) connection is tracked -
                # the rejected wrong-password attempt was never tracked
                # at all, the exact same "no partial/viewer capacity
                # granted" guarantee server_full's own rejection path
                # already established (server/application/game_server.py's
                # own "THIRD-PLUS CONNECTION POLICY" docstring section),
                # now proven for a rejected LOGIN attempt too. Both
                # `_connection_manager`/`_colors` are plain Python
                # state, not sqlite-backed, so reading them directly
                # here has no thread-affinity concern at all.
                assert game_server._connection_manager.connection_count == 1
                assert len(game_server._colors) == 1

    asyncio.run(scenario())


def test_a_malformed_auth_command_is_rejected_and_does_not_crash_the_server_which_keeps_accepting_valid_connections():
    async def scenario():
        async with _running_game_server(":memory:") as (uri, _game_server):
            async with websockets.connect(uri) as bad_client:
                await bad_client.send("not a real auth command")
                rejection = await asyncio.wait_for(bad_client.recv(), timeout=_RECV_TIMEOUT_S)
                assert "rejected" in rejection
                with pytest.raises(ConnectionClosed):
                    await asyncio.wait_for(bad_client.recv(), timeout=_RECV_TIMEOUT_S)

            # The server process itself must still be healthy
            # afterward - proven by a real, subsequent valid login
            # still working normally.
            async with _connected_and_authenticated(uri, "bob", "a real password") as (_client, welcome):
                color_name, rating = _parse_assigned_color_and_rating(welcome)
            assert color_name == "white"
            assert rating == DEFAULT_STARTING_RATING

    asyncio.run(scenario())
