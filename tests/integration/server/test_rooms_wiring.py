"""Real, end-to-end integration tests for Stage F4's room wiring
(server/application/game_server.py's own "STAGE F4" docstring section)
- a REAL server (real GameServer, real SessionCoordinator, real
background tick loop) and REAL websockets clients, mirroring
test_matchmaking_protocol.py's own "real server, real client, no
mocking, concurrent asyncio.gather joins" convention exactly.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import pytest
import websockets
from websockets.exceptions import ConnectionClosed

from kungfu_chess.notation.auth_command_format import format_auth_command
from server.application.game_server import GameServer

# Marked slow: this file constructs a real, background-threaded/tasked
# server and relies on real wall-clock waiting (asyncio.sleep/time.sleep,
# real tick-loop cadence, or real network round trips) - excluded from
# `pytest -m "not slow"` for fast, deterministic day-to-day runs; still
# run in full via the dedicated slow/real-time pass.
pytestmark = pytest.mark.slow

_RECV_TIMEOUT_S = 20.0
_REACTION_DELAY_S = 0.3  # a real moment for the server's own coroutine to react


@asynccontextmanager
async def _running_game_server(start_tick_loop: bool = True):
    game_server = GameServer(user_repository_db_path=":memory:")
    server = await websockets.serve(game_server.handle_connection, "localhost", 0)
    tick_task = asyncio.create_task(game_server.run_tick_loop()) if start_tick_loop else None
    try:
        port = server.sockets[0].getsockname()[1]
        yield f"ws://localhost:{port}", game_server
    finally:
        if tick_task is not None:
            tick_task.cancel()
            try:
                await tick_task
            except asyncio.CancelledError:
                pass
        # A brief, real moment for every just-disconnected connection's
        # own handle_connection coroutine to actually reach
        # _handle_active_match_disconnect and register its own pending
        # countdown (a genuine scheduling race when clients close
        # back-to-back - see server/application/game_server.py's own
        # "STAGE - SERVER SHUTDOWN..." docstring section) before
        # shutdown() resolves whatever is currently pending.
        await asyncio.sleep(0.2)
        await game_server.shutdown()
        server.close()
        await server.wait_closed()


def _parse_assigned_color_and_rating(message: str) -> tuple[str, int]:
    _, color_name, rating_text = message.split(":", 2)
    return color_name, int(rating_text)


def test_host_creates_room_guest_joins_both_get_matched_and_a_real_move_broadcasts_to_both():
    async def scenario():
        async with _running_game_server() as (uri, _game_server):
            host = await websockets.connect(uri)
            await host.send(format_auth_command("alice", "correct horse battery staple"))
            await host.send("CREATE_ROOM")
            room_created = await asyncio.wait_for(host.recv(), timeout=_RECV_TIMEOUT_S)
            assert room_created.startswith("room_created:")
            code = room_created.split(":", 1)[1]

            guest = await websockets.connect(uri)
            await guest.send(format_auth_command("bob", "another real password"))
            await guest.send(f"JOIN_ROOM:{code}")

            room_joined = await asyncio.wait_for(guest.recv(), timeout=_RECV_TIMEOUT_S)
            assert room_joined == "room_joined:guest"

            host_welcome = await asyncio.wait_for(host.recv(), timeout=_RECV_TIMEOUT_S)
            guest_welcome = await asyncio.wait_for(guest.recv(), timeout=_RECV_TIMEOUT_S)
            host_color, _host_rating = _parse_assigned_color_and_rating(host_welcome)
            guest_color, _guest_rating = _parse_assigned_color_and_rating(guest_welcome)

            # Host=White, Guest=Black - see module docstring's "STAGE F4"
            # section for the full reasoning.
            assert host_color == "white"
            assert guest_color == "black"

            host_board = await asyncio.wait_for(host.recv(), timeout=_RECV_TIMEOUT_S)
            guest_board = await asyncio.wait_for(guest.recv(), timeout=_RECV_TIMEOUT_S)
            assert host_board == guest_board

            # A real move, from the real White (host) client - proves a
            # genuine, live GameSession backs this room-based match.
            await host.send("WPe2e4")

            # UPDATED for Stage G4's lean wire protocol
            # (feature/g4-lean-wire-protocol) - see
            # tests/integration/server/test_protocol_wiring.py's own
            # test_legal_move_from_correct_color_client_is_accepted_and_
            # broadcast_to_both_clients for the full per-event message-
            # count reasoning: MoveAccepted broadcasts wire+LOG_DELTA
            # (BOARD_DELTA empty/skipped), PieceArrived broadcasts wire+
            # BOARD_DELTA (LOG_DELTA skipped - nothing captured).
            for _ in range(2):
                await asyncio.wait_for(host.recv(), timeout=_RECV_TIMEOUT_S)
                await asyncio.wait_for(guest.recv(), timeout=_RECV_TIMEOUT_S)
            await asyncio.wait_for(host.recv(), timeout=_RECV_TIMEOUT_S)  # PieceArrived wire event
            await asyncio.wait_for(guest.recv(), timeout=_RECV_TIMEOUT_S)
            board_delta_host = await asyncio.wait_for(host.recv(), timeout=_RECV_TIMEOUT_S)
            board_delta_guest = await asyncio.wait_for(guest.recv(), timeout=_RECV_TIMEOUT_S)

            assert board_delta_host == board_delta_guest
            assert "e2:." in board_delta_host  # e2 now empty
            assert "e4:wP" in board_delta_host  # e4 now holds the white pawn

            await host.close()
            await guest.close()

    asyncio.run(scenario())


def test_join_room_with_a_code_that_was_never_created_receives_room_not_found_and_closes():
    async def scenario():
        async with _running_game_server() as (uri, _game_server):
            client = await websockets.connect(uri)
            await client.send(format_auth_command("alice", "correct horse battery staple"))
            await client.send("JOIN_ROOM:NOPE00")

            reply = await asyncio.wait_for(client.recv(), timeout=_RECV_TIMEOUT_S)
            assert reply == "room_not_found"

            with pytest.raises(ConnectionClosed):
                await asyncio.wait_for(client.recv(), timeout=_RECV_TIMEOUT_S)

    asyncio.run(scenario())


def test_a_third_client_joining_a_full_room_becomes_a_viewer_who_watches_but_cannot_move():
    # Stage F5 - a REAL, flagged behavior change from Stage F4's own
    # "room_joined:viewer, then closed" placeholder (see this project's
    # own established precedent for flagging such changes loudly, e.g.
    # Stage E1's "server_full removed" and Stage F4's own test
    # migrations, rather than silently leaving a now-false assertion in
    # place): a viewer now actually stays connected, watches every real
    # broadcast identically to the two real players, and has its own
    # move/jump attempts rejected via the SAME "rejected:wrong_color"
    # mechanism a real player's own wrong-color attempt already uses -
    # see server/application/game_server.py's own "STAGE F5" docstring
    # section for the full reasoning.
    async def scenario():
        async with _running_game_server() as (uri, _game_server):
            host = await websockets.connect(uri)
            await host.send(format_auth_command("alice", "correct horse battery staple"))
            await host.send("CREATE_ROOM")
            room_created = await asyncio.wait_for(host.recv(), timeout=_RECV_TIMEOUT_S)
            code = room_created.split(":", 1)[1]

            guest = await websockets.connect(uri)
            await guest.send(format_auth_command("bob", "another real password"))
            await guest.send(f"JOIN_ROOM:{code}")
            assert await asyncio.wait_for(guest.recv(), timeout=_RECV_TIMEOUT_S) == "room_joined:guest"

            host_welcome = await asyncio.wait_for(host.recv(), timeout=_RECV_TIMEOUT_S)
            await asyncio.wait_for(host.recv(), timeout=_RECV_TIMEOUT_S)  # host board
            await asyncio.wait_for(guest.recv(), timeout=_RECV_TIMEOUT_S)  # guest assigned_color
            await asyncio.wait_for(guest.recv(), timeout=_RECV_TIMEOUT_S)  # guest board
            host_color, _host_rating = _parse_assigned_color_and_rating(host_welcome)
            assert host_color == "white"  # Host=White - see module docstring's "STAGE F4" section.

            viewer = await websockets.connect(uri)
            await viewer.send(format_auth_command("carol", "yet another password"))
            await viewer.send(f"JOIN_ROOM:{code}")

            assert await asyncio.wait_for(viewer.recv(), timeout=_RECV_TIMEOUT_S) == "room_joined:viewer"
            # A viewer joining mid-game sees the CURRENT board
            # immediately - not a closed connection (Stage F4's own,
            # now-superseded placeholder). Not stored: Stage G4's own
            # BOARD_DELTA replaces the later full board-text broadcast
            # this used to be compared against - see the "e4:wP in
            # board_delta_viewer" assertion below for the real proof the
            # board genuinely advanced instead.
            await asyncio.wait_for(viewer.recv(), timeout=_RECV_TIMEOUT_S)

            # A real move, from the real White (host) client.
            await host.send("WPe2e4")

            # UPDATED for Stage G4's lean wire protocol
            # (feature/g4-lean-wire-protocol) - see
            # tests/integration/server/test_protocol_wiring.py's own
            # test_legal_move_from_correct_color_client_is_accepted_and_
            # broadcast_to_both_clients for the full per-event message-
            # count reasoning: MoveAccepted broadcasts wire+LOG_DELTA
            # (BOARD_DELTA empty/skipped), PieceArrived broadcasts wire+
            # BOARD_DELTA (LOG_DELTA skipped - nothing captured) - four
            # messages total, not five; nothing is left over after
            # capturing the BOARD_DELTA below.
            for _ in range(2):  # MoveAccepted: wire event, LOG_DELTA
                await asyncio.wait_for(host.recv(), timeout=_RECV_TIMEOUT_S)
                await asyncio.wait_for(guest.recv(), timeout=_RECV_TIMEOUT_S)
                await asyncio.wait_for(viewer.recv(), timeout=_RECV_TIMEOUT_S)
            await asyncio.wait_for(host.recv(), timeout=_RECV_TIMEOUT_S)  # PieceArrived wire event
            await asyncio.wait_for(guest.recv(), timeout=_RECV_TIMEOUT_S)
            await asyncio.wait_for(viewer.recv(), timeout=_RECV_TIMEOUT_S)
            board_delta_host = await asyncio.wait_for(host.recv(), timeout=_RECV_TIMEOUT_S)
            board_delta_guest = await asyncio.wait_for(guest.recv(), timeout=_RECV_TIMEOUT_S)
            board_delta_viewer = await asyncio.wait_for(viewer.recv(), timeout=_RECV_TIMEOUT_S)

            # The viewer received the EXACT SAME broadcast as both real
            # players - identical fan-out, not a second-class feed.
            assert board_delta_host == board_delta_guest == board_delta_viewer
            assert "e4:wP" in board_delta_viewer  # the board genuinely advanced

            # The viewer now attempts a move of its own.
            await viewer.send("WPd2d4")
            rejection = await asyncio.wait_for(viewer.recv(), timeout=_RECV_TIMEOUT_S)
            # The literal wire text, not just "some rejection" - byte-
            # identical to an existing real player's own wrong_color
            # rejection (test_protocol_wiring.py's own
            # test_move_command_with_wrong_color_prefix_for_the_connection_is_rejected).
            assert rejection == "rejected:wrong_color"

            # The viewer's own rejected move did not affect the board -
            # neither real player receives any further broadcast from
            # it.
            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(host.recv(), timeout=0.5)
            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(guest.recv(), timeout=0.5)

            await host.close()
            await guest.close()
            await viewer.close()

    asyncio.run(scenario())


def test_a_third_client_joining_a_room_whose_host_vanished_before_any_guest_joined_gets_room_not_found():
    # The "phantom room" edge case - a direct, further consequence of
    # Stage F4's own already-accepted "abandoned room" gap, not a new
    # bug: see server/application/game_server.py's own "STAGE F5"
    # docstring section for the full reasoning.
    async def scenario():
        async with _running_game_server() as (uri, _game_server):
            host = await websockets.connect(uri)
            await host.send(format_auth_command("alice", "correct horse battery staple"))
            await host.send("CREATE_ROOM")
            room_created = await asyncio.wait_for(host.recv(), timeout=_RECV_TIMEOUT_S)
            code = room_created.split(":", 1)[1]

            # The host disconnects before anyone ever joins (Stage F4's
            # own already-tested scenario).
            await host.close()
            await asyncio.sleep(_REACTION_DELAY_S)

            second = await websockets.connect(uri)
            await second.send(format_auth_command("bob", "another real password"))
            await second.send(f"JOIN_ROOM:{code}")
            reply = await asyncio.wait_for(second.recv(), timeout=_RECV_TIMEOUT_S)
            assert reply == "room_not_found"
            with pytest.raises(ConnectionClosed):
                await asyncio.wait_for(second.recv(), timeout=_RECV_TIMEOUT_S)

            # A THIRD connection joins that SAME, now-doubly-abandoned
            # code - SessionCoordinator's own Room shows 2 occupants
            # (the vanished host + the "phantom guest" above), so this
            # connection would structurally qualify as Role.VIEWER - but
            # self._room_matches has no entry for this code (no real
            # _Match was ever constructed), so it must ALSO get
            # room_not_found, not a viewer role and not a crash.
            third = await websockets.connect(uri)
            await third.send(format_auth_command("carol", "yet another password"))
            await third.send(f"JOIN_ROOM:{code}")
            reply2 = await asyncio.wait_for(third.recv(), timeout=_RECV_TIMEOUT_S)
            assert reply2 == "room_not_found"
            with pytest.raises(ConnectionClosed):
                await asyncio.wait_for(third.recv(), timeout=_RECV_TIMEOUT_S)

    asyncio.run(scenario())


def test_host_disconnects_before_any_guest_joins_then_a_later_join_attempt_gets_room_not_found():
    async def scenario():
        async with _running_game_server() as (uri, _game_server):
            host = await websockets.connect(uri)
            await host.send(format_auth_command("alice", "correct horse battery staple"))
            await host.send("CREATE_ROOM")
            room_created = await asyncio.wait_for(host.recv(), timeout=_RECV_TIMEOUT_S)
            code = room_created.split(":", 1)[1]

            # The host disconnects before anyone ever joins - the server
            # must not hang.
            await host.close()
            await asyncio.sleep(_REACTION_DELAY_S)

            guest = await websockets.connect(uri)
            await guest.send(format_auth_command("bob", "another real password"))
            await guest.send(f"JOIN_ROOM:{code}")

            reply = await asyncio.wait_for(guest.recv(), timeout=_RECV_TIMEOUT_S)
            assert reply == "room_not_found"

            with pytest.raises(ConnectionClosed):
                await asyncio.wait_for(guest.recv(), timeout=_RECV_TIMEOUT_S)

    asyncio.run(scenario())


def test_play_still_matchmakes_two_play_clients_exactly_as_before_non_regression():
    async def scenario():
        async with _running_game_server() as (uri, _game_server):
            client1 = await websockets.connect(uri)
            client2 = await websockets.connect(uri)

            await client1.send(format_auth_command("alice", "correct horse battery staple"))
            await client2.send(format_auth_command("bob", "another real password"))

            # The room choice ("PLAY") must be sent BEFORE waiting for
            # searching_for_opponent - the server now reads it first
            # (Stage F4) before ever sending that message.
            await client1.send("PLAY")
            await client2.send("PLAY")

            searching1 = await asyncio.wait_for(client1.recv(), timeout=_RECV_TIMEOUT_S)
            searching2 = await asyncio.wait_for(client2.recv(), timeout=_RECV_TIMEOUT_S)
            assert searching1 == "searching_for_opponent"
            assert searching2 == "searching_for_opponent"

            welcome1 = await asyncio.wait_for(client1.recv(), timeout=_RECV_TIMEOUT_S)
            welcome2 = await asyncio.wait_for(client2.recv(), timeout=_RECV_TIMEOUT_S)
            color1, _rating1 = _parse_assigned_color_and_rating(welcome1)
            color2, _rating2 = _parse_assigned_color_and_rating(welcome2)
            assert {color1, color2} == {"white", "black"}

            board1 = await asyncio.wait_for(client1.recv(), timeout=_RECV_TIMEOUT_S)
            board2 = await asyncio.wait_for(client2.recv(), timeout=_RECV_TIMEOUT_S)
            assert board1 == board2

            await client1.close()
            await client2.close()

    asyncio.run(scenario())


async def _drain_one_real_event(connections: list) -> list:
    """Drain exactly one real game event's own broadcast from every
    connection in `connections`, in lockstep, returning each
    connection's own second message - the one piece every caller below
    actually wants to compare across every connection.

    UPDATED for Stage G4's lean wire protocol (feature/g4-lean-wire-
    protocol): a real event now broadcasts its wire event plus exactly
    ONE of BOARD_DELTA/LOG_DELTA, not the old fixed 3-message (wire
    event, board text, state snapshot) shape - see
    server/application/game_server.py's own "STAGE G4" docstring
    section for why a non-capturing MoveAccepted always produces
    LOG_DELTA only (its own BOARD_DELTA is empty/skipped) and a
    non-capturing PieceArrived always produces BOARD_DELTA only (its own
    LOG_DELTA is skipped) - either way, exactly TWO messages per
    connection for every call site below (this scenario's own moves are
    all non-capturing).

    Stage F6 - the whole point of this helper is that it takes an
    arbitrary NUMBER of connections, never assuming exactly 2."""

    deltas = []
    for connection in connections:
        await asyncio.wait_for(connection.recv(), timeout=_RECV_TIMEOUT_S)  # wire event
        deltas.append(await asyncio.wait_for(connection.recv(), timeout=_RECV_TIMEOUT_S))  # LOG_DELTA or BOARD_DELTA
    return deltas


def test_two_players_and_three_viewers_all_five_connections_receive_every_broadcast_identically():
    # Stage F6's own definitive multi-viewer correctness test, deferred
    # by Stage F5 - see server/application/game_server.py's own
    # "STAGE F6" docstring section: 2 real players + 3 viewers = 5
    # connections, all treated identically by _broadcast_event's own
    # fan-out (already fixed in Stage F5) - re-verified here at N=3
    # viewers specifically, not just Stage F5's own N=1 case.
    async def scenario():
        async with _running_game_server() as (uri, _game_server):
            host = await websockets.connect(uri)
            await host.send(format_auth_command("alice", "correct horse battery staple"))
            await host.send("CREATE_ROOM")
            room_created = await asyncio.wait_for(host.recv(), timeout=_RECV_TIMEOUT_S)
            code = room_created.split(":", 1)[1]

            guest = await websockets.connect(uri)
            await guest.send(format_auth_command("bob", "another real password"))
            await guest.send(f"JOIN_ROOM:{code}")
            assert await asyncio.wait_for(guest.recv(), timeout=_RECV_TIMEOUT_S) == "room_joined:guest"

            host_welcome = await asyncio.wait_for(host.recv(), timeout=_RECV_TIMEOUT_S)
            await asyncio.wait_for(host.recv(), timeout=_RECV_TIMEOUT_S)  # host board
            await asyncio.wait_for(guest.recv(), timeout=_RECV_TIMEOUT_S)  # guest assigned_color
            await asyncio.wait_for(guest.recv(), timeout=_RECV_TIMEOUT_S)  # guest board
            host_color, _host_rating = _parse_assigned_color_and_rating(host_welcome)
            assert host_color == "white"

            viewers = []
            for name, password in (
                ("carol", "yet another password"),
                ("dave", "still another password"),
                ("erin", "one more password"),
            ):
                viewer = await websockets.connect(uri)
                await viewer.send(format_auth_command(name, password))
                await viewer.send(f"JOIN_ROOM:{code}")
                assert await asyncio.wait_for(viewer.recv(), timeout=_RECV_TIMEOUT_S) == "room_joined:viewer"
                await asyncio.wait_for(viewer.recv(), timeout=_RECV_TIMEOUT_S)  # initial board
                viewers.append(viewer)
            viewer1, viewer2, viewer3 = viewers

            all_five = [host, guest, viewer1, viewer2, viewer3]

            # A real move, from the real White (host) client - MoveAccepted
            # then PieceArrived, each its own full 3-message broadcast.
            await host.send("WPe2e4")
            move_boards = await _drain_one_real_event(all_five)
            arrival_boards = await _drain_one_real_event(all_five)

            # ALL FIVE connections received the identical wire text, at
            # both stages of the broadcast - not just "each got
            # something," the exact same content, host/guest/viewers alike.
            assert len(set(move_boards)) == 1
            assert len(set(arrival_boards)) == 1
            assert move_boards[0] != arrival_boards[0]  # the board genuinely advanced

            # One of the three viewers disconnects.
            await viewer2.close()
            await asyncio.sleep(_REACTION_DELAY_S)

            # A second real move (Black, from the guest) - the three
            # REMAINING connections must still receive it identically;
            # viewer2's own departure must not disturb anyone else's feed.
            await guest.send("BPe7e5")
            remaining = [host, guest, viewer1, viewer3]
            second_move_boards = await _drain_one_real_event(remaining)
            second_arrival_boards = await _drain_one_real_event(remaining)

            assert len(set(second_move_boards)) == 1
            assert len(set(second_arrival_boards)) == 1
            assert second_arrival_boards[0] != arrival_boards[0]  # advanced again

            await host.close()
            await guest.close()
            await viewer1.close()
            await viewer3.close()

    asyncio.run(scenario())
