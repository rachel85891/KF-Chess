"""Unit tests for Stage F2's SessionCoordinator Protocol and its one
concrete InMemorySessionCoordinator (server/application/
session_coordinator.py) - built and tested COMPLETELY IN ISOLATION,
mirroring test_matchmaking_queue.py's and test_room.py's own established
pattern. InMemorySessionCoordinator composes the REAL MatchmakingQueue
and REAL Room/RoomCodeGenerator (Stage E1/F1, both already independently
tested) - these tests deliberately do NOT re-test either collaborator's
own internal pairing/capacity logic a second time; they only prove this
new module delegates to them correctly.
"""

from __future__ import annotations

from server.application.matchmaking_queue import MatchmakingQueue
from server.application.room import ROOM_CODE_LENGTH, Role
from server.application.session_coordinator import (
    InMemorySessionCoordinator,
    SessionCoordinator,
)


class _FakeClock:
    """Same settable fake clock shape as test_matchmaking_queue.py's own
    _FakeClock - injected here via a real MatchmakingQueue so tests never
    depend on real elapsed time."""

    def __init__(self, value: float = 0.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value


def test_in_memory_session_coordinator_satisfies_the_session_coordinator_protocol():
    coordinator = InMemorySessionCoordinator()

    # A real, structural isinstance check against a @runtime_checkable
    # Protocol - proves InMemorySessionCoordinator's own public method
    # shapes genuinely satisfy the Protocol, not merely "by convention."
    assert isinstance(coordinator, SessionCoordinator)


def test_find_match_returns_none_for_a_single_waiting_participant():
    coordinator = InMemorySessionCoordinator()

    assert coordinator.find_match(connection_id="conn-a", username="alice", rating=1200) is None


def test_find_match_pairs_two_rating_compatible_participants_and_returns_the_pair_to_the_completing_caller():
    coordinator = InMemorySessionCoordinator()

    # Mirrors test_matchmaking_queue.py's own already-tested pairing
    # behavior - this test only proves DELEGATION, not the pairing rule
    # itself (already proven in test_matchmaking_queue.py).
    first_result = coordinator.find_match(connection_id="conn-a", username="alice", rating=1200)
    assert first_result is None  # alice alone - nobody to pair with yet

    second_result = coordinator.find_match(connection_id="conn-b", username="bob", rating=1250)

    assert second_result is not None
    first, second = second_result
    assert first.username == "alice"
    assert second.username == "bob"


def test_find_match_returns_none_when_the_only_two_participants_differ_by_more_than_100():
    coordinator = InMemorySessionCoordinator()

    coordinator.find_match(connection_id="conn-a", username="alice", rating=1200)
    result = coordinator.find_match(connection_id="conn-b", username="bob", rating=1301)  # 101 apart

    assert result is None


def test_find_match_leaves_an_unmatched_participant_queued_for_a_later_call():
    coordinator = InMemorySessionCoordinator()

    coordinator.find_match(connection_id="conn-a", username="alice", rating=1200)
    coordinator.find_match(connection_id="conn-b", username="bob", rating=9999)  # incompatible with alice

    # A third, alice-compatible participant now completes alice's own
    # match - proving alice's own earlier, unmatched entry genuinely
    # stayed queued rather than being silently dropped.
    result = coordinator.find_match(connection_id="conn-c", username="carol", rating=1210)

    assert result is not None
    first, second = result
    assert {first.username, second.username} == {"alice", "carol"}


def test_find_match_delegates_to_an_injected_matchmaking_queue_instance():
    clock = _FakeClock(100.0)
    queue = MatchmakingQueue(clock=clock)
    coordinator = InMemorySessionCoordinator(matchmaking_queue=queue)

    coordinator.find_match(connection_id="conn-a", username="alice", rating=1200)

    # The injected queue instance itself was genuinely mutated - proves
    # this is delegation, not a separately-reimplemented queue.
    clock.value = 161.0
    expired = queue.expire_timed_out(now=clock.value, timeout_seconds=60)
    assert [entry.connection_id for entry in expired] == ["conn-a"]


def test_create_room_returns_a_real_valid_room_code():
    coordinator = InMemorySessionCoordinator()

    code = coordinator.create_room(host_identity="alice")

    assert isinstance(code, str)
    assert len(code) == ROOM_CODE_LENGTH


def test_create_room_produces_a_room_whose_host_can_be_joined_as_guest():
    coordinator = InMemorySessionCoordinator()
    code = coordinator.create_room(host_identity="alice")

    result = coordinator.join_room(code, identity="bob")

    assert result is not None
    assert result.role is Role.GUEST
    assert [member.identity for member in result.room.players()] == ["alice", "bob"]


def test_join_room_assigns_viewer_once_the_room_already_has_a_host_and_a_guest():
    coordinator = InMemorySessionCoordinator()
    code = coordinator.create_room(host_identity="alice")
    coordinator.join_room(code, identity="bob")  # fills the guest slot

    result = coordinator.join_room(code, identity="carol")

    assert result is not None
    assert result.role is Role.VIEWER
    assert [member.identity for member in result.room.viewers()] == ["carol"]


def test_join_room_returns_none_for_an_unknown_code_no_exception():
    coordinator = InMemorySessionCoordinator()

    result = coordinator.join_room("NOPE00", identity="bob")  # never created

    assert result is None


def test_join_room_uses_the_same_room_instance_across_repeated_joins():
    coordinator = InMemorySessionCoordinator()
    code = coordinator.create_room(host_identity="alice")

    first = coordinator.join_room(code, identity="bob")
    second = coordinator.join_room(code, identity="carol")

    assert first.room is second.room  # the SAME Room instance, not a copy
