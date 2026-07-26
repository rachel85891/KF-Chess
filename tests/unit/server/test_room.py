"""Unit tests for Stage F1's standalone RoomCodeGenerator/Room
(server/application/room.py) - built and tested COMPLETELY IN
ISOLATION from networking/GameSession/GameServer, mirroring
server/application/matchmaking_queue.py's own established pattern of
proving a new capability correct on its own before wiring it into
anything. No real randomness where determinism is needed - a fake,
seeded random source throughout those tests, mirroring
test_matchmaking_queue.py's own "inject the fake clock" convention,
applied here to injected randomness instead.
"""

from __future__ import annotations

import random

from server.application.room import (
    ROOM_CODE_ALPHABET,
    ROOM_CODE_LENGTH,
    Role,
    Room,
    RoomCodeGenerator,
    RoomFullError,
)


class _FakeRandomSource:
    """A settable fake random source - the same shape this project's
    own test_matchmaking_queue.py uses for its fake clock, applied here
    to `.choice(sequence)` instead of a callable-with-no-args. Cycles
    through a fixed, pre-determined sequence of characters, one per
    `.choice()` call, so a test can assert on the EXACT resulting code
    without depending on real randomness at all."""

    def __init__(self, characters: str) -> None:
        self._characters = list(characters)
        self._next_index = 0

    def choice(self, sequence):
        character = self._characters[self._next_index]
        self._next_index += 1
        return character


def test_generate_produces_a_code_of_the_configured_length():
    generator = RoomCodeGenerator()

    code = generator.generate()

    assert len(code) == ROOM_CODE_LENGTH


def test_generate_produces_different_codes_across_calls_using_a_real_random_source():
    generator = RoomCodeGenerator(random_source=random.Random())

    codes = {generator.generate() for _ in range(50)}

    # Not a proof of uniqueness (this module makes no such guarantee -
    # see module docstring), just that a real random source genuinely
    # varies call to call rather than always producing the same code.
    assert len(codes) > 1


def test_generate_only_ever_uses_characters_from_the_configured_alphabet():
    generator = RoomCodeGenerator(random_source=random.Random())

    for _ in range(20):
        code = generator.generate()
        assert all(character in ROOM_CODE_ALPHABET for character in code)


def test_generate_is_deterministic_and_reproducible_with_an_injected_fake_random_source():
    fake_source = _FakeRandomSource("ABCDEF" * 2)
    generator = RoomCodeGenerator(random_source=fake_source)

    first_code = generator.generate()

    fake_source_2 = _FakeRandomSource("ABCDEF" * 2)
    generator_2 = RoomCodeGenerator(random_source=fake_source_2)
    second_code = generator_2.generate()

    assert first_code == second_code == "ABCDEF"


def test_room_starts_with_just_the_host_and_no_guest():
    room = Room(code="ABCDEF", host_identity="alice")

    assert room.code == "ABCDEF"
    players = room.players()
    assert len(players) == 1
    assert players[0].identity == "alice"
    assert players[0].role is Role.HOST
    assert room.viewers() == ()


def test_can_add_player_is_true_with_only_a_host_present():
    room = Room(code="ABCDEF", host_identity="alice")

    assert room.can_add_player() is True
    assert room.is_full() is False


def test_add_player_joins_as_guest_and_then_the_room_is_full_for_further_players():
    room = Room(code="ABCDEF", host_identity="alice")

    room.add_player("bob")

    players = room.players()
    assert len(players) == 2
    assert players[1].identity == "bob"
    assert players[1].role is Role.GUEST
    assert room.can_add_player() is False
    assert room.is_full() is True


def test_add_player_raises_once_the_room_already_has_a_host_and_a_guest():
    room = Room(code="ABCDEF", host_identity="alice")
    room.add_player("bob")

    try:
        room.add_player("carol")
        assert False, "expected RoomFullError"
    except RoomFullError:
        pass

    # The rejected attempt left no trace - still exactly host + guest.
    assert [member.identity for member in room.players()] == ["alice", "bob"]


def test_a_full_room_of_two_real_players_can_still_add_a_viewer():
    room = Room(code="ABCDEF", host_identity="alice")
    room.add_player("bob")
    assert room.is_full() is True

    room.add_viewer("carol")

    viewers = room.viewers()
    assert len(viewers) == 1
    assert viewers[0].identity == "carol"
    assert viewers[0].role is Role.VIEWER


def test_viewers_have_no_upper_bound_even_with_a_host_only_room():
    # Re-verifies this project's own explicit requirement: no hardcoded
    # "max N viewers" assumption exists anywhere in this class - a
    # host-only (not yet full) room can already accept any number of
    # viewers, and a full room can keep accepting still more.
    room = Room(code="ABCDEF", host_identity="alice")

    for i in range(25):
        room.add_viewer(f"viewer-{i}")

    assert len(room.viewers()) == 25
    # Still perfectly able to add the real second player afterward too -
    # viewers never occupy or block a player slot.
    assert room.can_add_player() is True
    room.add_player("bob")
    assert room.is_full() is True

    # And still more viewers on top of a now-full room.
    for i in range(25, 40):
        room.add_viewer(f"viewer-{i}")
    assert len(room.viewers()) == 40


def test_players_and_viewers_return_defensive_copies_not_the_live_internal_state():
    room = Room(code="ABCDEF", host_identity="alice")

    players_snapshot = room.players()
    room.add_player("bob")

    # The earlier snapshot is unaffected by the later mutation.
    assert len(players_snapshot) == 1
