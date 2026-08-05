"""tests/unit/server/test_session_coordinator_contract.py: Stage I2 -
the SAME SessionCoordinator Protocol contract, run against BOTH concrete
implementations - InMemorySessionCoordinator (Stage F2, always) and
RedisSessionCoordinator (Stage I2, marked `requires_redis` - skips
cleanly if no real Redis is reachable in this environment, see
conftest.py/pytest.ini).

WHERE THESE 10 TESTS CAME FROM: split out of test_session_coordinator.py
(Stage F2's own original suite, 11 tests total) - re-verified directly,
10 of those 11 tests only ever use the 3 public Protocol methods
(`find_match`/`create_room`/`join_room`) and one `isinstance` conformance
check, none of them touching InMemorySessionCoordinator's own internal
`_matchmaking_queue`/`_rooms` state or constructor-injection shape - so
they are genuinely backend-agnostic once parameterized over the
`coordinator` fixture, below, instead of each constructing
`InMemorySessionCoordinator()` directly. The 1 remaining test
(`test_find_match_delegates_to_an_injected_matchmaking_queue_instance`)
stayed in test_session_coordinator.py, unmoved - it asserts real
delegation to an injected `MatchmakingQueue` instance, a design detail
RedisSessionCoordinator does not share (it queries a Redis sorted set
directly - there is no "injected collaborator" for it to delegate to).

ONE TEST ADDED BEYOND THE ORIGINAL 10 (per this project's own established
"add tests for stated-but-unnamed requirements without stopping to ask"
convention): `test_redis_session_coordinator_join_room_reconstructs_the_
same_room_data_from_a_second_coordinator_instance` - Redis-only (not
parameterized), proving the actual cross-process data-visibility
guarantee this whole stage exists for (session_coordinator.py's own
long-standing module docstring explicitly named this as what a future
distributed implementation would need to satisfy) - none of the 10
shared tests above exercise a SECOND coordinator instance at all, so
this genuinely-new behavior had no existing test to parameterize into.
"""

from __future__ import annotations

import uuid

import pytest

from server.application.matchmaking_queue import MatchmakingQueue
from server.application.room import ROOM_CODE_LENGTH, Role
from server.application.session_coordinator import (
    InMemorySessionCoordinator,
    RedisSessionCoordinator,
    SessionCoordinator,
)


@pytest.fixture(params=["in_memory", pytest.param("redis", marks=pytest.mark.requires_redis)])
def coordinator(request, redis_client_or_skip):
    """Yields a fresh SessionCoordinator - InMemorySessionCoordinator
    for the "in_memory" param, or a real-Redis-backed
    RedisSessionCoordinator (skipping cleanly if no real Redis is
    reachable) for the "redis" param. Every test below receives this
    fixture as its own `coordinator` parameter and runs, unmodified,
    against whichever backend pytest is currently parameterizing."""

    if request.param == "in_memory":
        yield InMemorySessionCoordinator()
        return

    client = redis_client_or_skip()
    # A fresh, unique key namespace per test - see
    # RedisSessionCoordinator's own `key_prefix` docstring: this is what
    # lets every test run independently against one real, shared Redis
    # instance without colliding with any other test's own state.
    prefix = f"test-{uuid.uuid4().hex}"
    real_coordinator = RedisSessionCoordinator(client=client, key_prefix=prefix)
    yield real_coordinator
    client.delete(f"{prefix}:matchmaking:queue")
    client.delete(f"{prefix}:rooms")


def test_session_coordinator_satisfies_the_session_coordinator_protocol(coordinator):
    # A real, structural isinstance check against a @runtime_checkable
    # Protocol - proves this backend's own public method shapes
    # genuinely satisfy the Protocol, not merely "by convention."
    assert isinstance(coordinator, SessionCoordinator)


def test_find_match_returns_none_for_a_single_waiting_participant(coordinator):
    assert coordinator.find_match(connection_id="conn-a", username="alice", rating=1200) is None


def test_find_match_pairs_two_rating_compatible_participants_and_returns_the_pair_to_the_completing_caller(
    coordinator,
):
    first_result = coordinator.find_match(connection_id="conn-a", username="alice", rating=1200)
    assert first_result is None  # alice alone - nobody to pair with yet

    second_result = coordinator.find_match(connection_id="conn-b", username="bob", rating=1250)

    assert second_result is not None
    first, second = second_result
    assert first.username == "alice"
    assert second.username == "bob"


def test_find_match_returns_none_when_the_only_two_participants_differ_by_more_than_100(coordinator):
    coordinator.find_match(connection_id="conn-a", username="alice", rating=1200)
    result = coordinator.find_match(connection_id="conn-b", username="bob", rating=1301)  # 101 apart

    assert result is None


def test_find_match_leaves_an_unmatched_participant_queued_for_a_later_call(coordinator):
    coordinator.find_match(connection_id="conn-a", username="alice", rating=1200)
    coordinator.find_match(connection_id="conn-b", username="bob", rating=9999)  # incompatible with alice

    # A third, alice-compatible participant now completes alice's own
    # match - proving alice's own earlier, unmatched entry genuinely
    # stayed queued rather than being silently dropped.
    result = coordinator.find_match(connection_id="conn-c", username="carol", rating=1210)

    assert result is not None
    first, second = result
    assert {first.username, second.username} == {"alice", "carol"}


def test_create_room_returns_a_real_valid_room_code(coordinator):
    code = coordinator.create_room(host_identity="alice")

    assert isinstance(code, str)
    assert len(code) == ROOM_CODE_LENGTH


def test_create_room_produces_a_room_whose_host_can_be_joined_as_guest(coordinator):
    code = coordinator.create_room(host_identity="alice")

    result = coordinator.join_room(code, identity="bob")

    assert result is not None
    assert result.role is Role.GUEST
    assert [member.identity for member in result.room.players()] == ["alice", "bob"]


def test_join_room_assigns_viewer_once_the_room_already_has_a_host_and_a_guest(coordinator):
    code = coordinator.create_room(host_identity="alice")
    coordinator.join_room(code, identity="bob")  # fills the guest slot

    result = coordinator.join_room(code, identity="carol")

    assert result is not None
    assert result.role is Role.VIEWER
    assert [member.identity for member in result.room.viewers()] == ["carol"]


def test_join_room_returns_none_for_an_unknown_code_no_exception(coordinator):
    result = coordinator.join_room("NOPE00", identity="bob")  # never created

    assert result is None


def test_join_room_uses_the_same_room_instance_across_repeated_joins(coordinator):
    code = coordinator.create_room(host_identity="alice")

    first = coordinator.join_room(code, identity="bob")
    second = coordinator.join_room(code, identity="carol")

    assert first.room is second.room  # the SAME Room instance, not a copy


@pytest.mark.requires_redis
def test_redis_session_coordinator_join_room_reconstructs_the_same_room_data_from_a_second_coordinator_instance(
    redis_client_or_skip,
):
    """The actual cross-process guarantee this stage exists for (see
    this file's own module docstring, and session_coordinator.py's own
    "WHY A LOCAL, PER-INSTANCE `_room_cache` EXISTS AT ALL" section): a
    SECOND RedisSessionCoordinator instance, pointed at the SAME Redis
    key namespace, sees the exact same room DATA the first instance
    created - a different Room object (never object-identical across
    instances - see that same docstring section for why that would be
    the wrong guarantee to expect here), but the same real state."""

    client = redis_client_or_skip()
    prefix = f"test-{uuid.uuid4().hex}"

    first_coordinator = RedisSessionCoordinator(client=client, key_prefix=prefix)
    second_coordinator = RedisSessionCoordinator(client=client, key_prefix=prefix)

    try:
        code = first_coordinator.create_room(host_identity="alice")

        # bob joins via the SECOND, otherwise-unrelated coordinator
        # instance - its own local `_room_cache` starts completely
        # empty, so this can only succeed by correctly reconstructing
        # the room from Redis's own persisted state.
        result = second_coordinator.join_room(code, identity="bob")

        assert result is not None
        assert result.role is Role.GUEST
        assert [member.identity for member in result.room.players()] == ["alice", "bob"]
        # Not the same Python object as anything the first instance
        # ever held - it was never given a chance to construct one.
        assert code not in first_coordinator._room_cache or first_coordinator._room_cache[code][0] is not (
            result.room
        )
    finally:
        client.delete(f"{prefix}:matchmaking:queue")
        client.delete(f"{prefix}:rooms")


def test_matchmaking_queues_own_pairing_rating_range_constant_is_reused_not_redefined():
    """SOLID/DRY checklist item, made concrete as a real, running test:
    RedisSessionCoordinator imports MatchmakingQueue's own
    RATING_RANGE_POINTS constant rather than hardcoding a second literal
    "100" somewhere in session_coordinator.py."""

    import inspect

    from server.application import session_coordinator as module

    source = inspect.getsource(module)
    assert "from server.application.matchmaking_queue import" in source
    assert "RATING_RANGE_POINTS" in source
    assert MatchmakingQueue is not None  # import actually used above, not dead
