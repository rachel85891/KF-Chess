"""tests/unit/server/test_game_allocator.py: Stage I3 - proves
GameAllocator's own least-loaded-shard selection (server/application/
game_allocator.py) actually works against a real Redis sorted set,
including the one property that actually justifies its atomic-`allocate`
design decision: many genuinely concurrent `allocate()` calls never lose
an increment or let two callers both "win" the same read. Marked
`requires_redis` - skips cleanly (via conftest.py's own
`redis_client_or_skip` factory fixture) if no real Redis is reachable in
this environment (see pytest.ini's own marker registration). Mirrors
test_redis_pubsub.py's own "prove the new capability correct on its own"
module shape (Stage I2).

Per Implementation_Plan.md's own I3 wording (restated in I3_prompt.md's
own Background section): this stage's own acceptance criteria is
satisfied by seeding "stubbed" shard-load entries directly via the
injected client (register_shard/allocate/release), NOT by running any
real heartbeat-producer loop - no such producer exists yet (see
game_allocator.py's own module docstring).
"""

from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest

from server.application.game_allocator import GameAllocator, NoShardsRegisteredError

pytestmark = pytest.mark.requires_redis


@pytest.fixture
def allocator(redis_client_or_skip):
    """A fresh GameAllocator against a real Redis client, namespaced by
    a unique per-test key_prefix - mirrors
    test_session_coordinator_contract.py's own `coordinator` fixture
    reasoning: lets every test run independently against one real,
    shared Redis instance without colliding with any other test's own
    shard-load state. Cleans up its own key afterward."""

    client = redis_client_or_skip()
    prefix = f"test-{uuid.uuid4().hex}"
    real_allocator = GameAllocator(client=client, key_prefix=prefix)
    yield real_allocator
    client.delete(f"{prefix}:shard_load")


def test_allocate_returns_the_currently_lowest_scored_registered_shard(allocator):
    allocator.register_shard("shard-a", initial_load=5)
    allocator.register_shard("shard-b", initial_load=1)
    allocator.register_shard("shard-c", initial_load=9)

    assert allocator.allocate() == "shard-b"


def test_allocate_increments_the_chosen_shards_score_so_a_tie_moves_to_the_next_shard(allocator):
    # Both start at the same score - the FIRST call's own choice
    # between them is unconstrained (redis breaks ties
    # lexicographically), but whichever one it picks must have its own
    # score bumped so the SECOND call picks the other one, not the same
    # one again.
    allocator.register_shard("shard-a", initial_load=0)
    allocator.register_shard("shard-b", initial_load=0)

    first = allocator.allocate()
    second = allocator.allocate()

    assert first != second
    assert {first, second} == {"shard-a", "shard-b"}


def test_release_decrements_a_specific_shards_score_independent_of_the_minimum(allocator):
    allocator.register_shard("shard-a", initial_load=0)
    allocator.register_shard("shard-b", initial_load=10)

    # shard-a is currently the minimum - allocate() bumps it to 1.
    assert allocator.allocate() == "shard-a"

    allocator.release("shard-b")  # not the minimum - no race concern per this method's own docstring

    assert allocator._client.zscore(allocator._shard_load_key, "shard-a") == 1
    assert allocator._client.zscore(allocator._shard_load_key, "shard-b") == 9


def test_allocate_raises_a_specific_error_when_no_shards_are_registered_at_all(allocator):
    with pytest.raises(NoShardsRegisteredError):
        allocator.allocate()


def test_allocate_is_atomic_under_real_concurrent_callers(allocator):
    """The one test that actually earns the atomic-`allocate()` design
    decision (see game_allocator.py's own module docstring) rather than
    merely documenting intent: many real threads share ONE
    GameAllocator/client and hammer `allocate()` concurrently against a
    small, fixed set of equally-loaded shards. If select-and-increment
    were ever two separate Redis round trips, two threads could read the
    same "currently least-loaded" shard before either's own increment
    landed, producing a final score distribution some shard(s) never
    got their fair share of, or a total less than the real call count
    (a lost update). Chosen counts (4 shards, 60 calls, 15 threads) are
    evenly divisible so the CORRECT final state is deterministic
    regardless of thread interleaving order: after any whole number of
    full "round robin" passes over N equally-loaded shards, each shard
    has been picked exactly the same number of times - the exact
    distribution sequential calls would have produced.
    """

    shard_ids = ["shard-a", "shard-b", "shard-c", "shard-d"]
    for shard_id in shard_ids:
        allocator.register_shard(shard_id, initial_load=0)

    call_count = 60

    with ThreadPoolExecutor(max_workers=15) as pool:
        results = list(pool.map(lambda _: allocator.allocate(), range(call_count)))

    assert len(results) == call_count
    key = allocator._shard_load_key
    scores = {shard_id: allocator._client.zscore(key, shard_id) for shard_id in shard_ids}

    # No lost increments: the real total across every shard's own final
    # score equals the real number of allocate() calls made.
    assert sum(scores.values()) == call_count
    # Perfectly even, exactly matching what call_count / len(shard_ids)
    # sequential calls would have produced - only possible if no two
    # concurrent callers ever won the same "currently least-loaded"
    # read before either's own write landed.
    expected_per_shard = call_count / len(shard_ids)
    assert all(score == expected_per_shard for score in scores.values())


def test_register_shard_is_idempotent_and_does_not_reset_an_already_registered_shards_load(allocator):
    """See game_allocator.py's own module docstring "REGISTER_SHARD IS
    IDEMPOTENT" section for the full reasoning: a repeat register_shard
    call (e.g. a real heartbeat producer re-announcing itself) must not
    wipe out load this same shard has already accrued via allocate()."""

    allocator.register_shard("shard-a", initial_load=0)
    allocator.allocate()  # shard-a's own score is now 1

    allocator.register_shard("shard-a", initial_load=0)  # a repeat announcement

    assert allocator._client.zscore(allocator._shard_load_key, "shard-a") == 1


def test_game_allocators_own_shard_load_key_is_distinct_from_the_matchmaking_queue_key(allocator):
    """SOLID/DRY checklist item, made concrete as a real, running test -
    mirrors test_session_coordinator_contract.py's own
    `test_matchmaking_queues_own_pairing_rating_range_constant_is_reused_
    not_redefined` pattern of turning a checklist item into an assertion,
    not just a code-read."""

    assert allocator._shard_load_key.endswith(":shard_load")
    assert "matchmaking:queue" not in allocator._shard_load_key
    assert "rooms" not in allocator._shard_load_key
