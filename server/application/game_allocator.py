"""game_allocator.py: Stage I3 - GameAllocator, a Redis-backed
least-loaded-shard selector (Server_Design.md §5, "Assigning Players to
Game Servers - the real gap in this project today"). A second, distinct
Redis sorted set (scored by each shard's current active-match count, not
rating) from Stage I2's own MatchmakingQueue-flavored sorted set in
session_coordinator.py - mirrors matchmaking_queue.py's own
RATING_RANGE_POINTS precedent of "a distinct sorted set for a genuinely
different purpose, reusing the same primitive, not the same key or
data."

WHAT THIS STAGE DELIBERATELY DOES NOT DO (I3_prompt.md's own Background
section, restated here so it isn't silently assumed to be in scope by
anyone reading only this module):

1. It does not build the HEARTBEAT PRODUCER - the periodic process that
   would report each real shard's own current load into Redis. No
   "shard" concept exists anywhere else in this single-process codebase
   yet - that's a Phase 4 concern, once the nine-service split gives
   this project actual separate Match-Host processes to report load
   FROM. This class's own tests seed "stubbed" load entries directly via
   `register_shard`, exactly matching the plan's own acceptance-criteria
   wording, not by running any real heartbeat loop.
2. It does not wire `release()`'s own call site into GameSession's real
   teardown path - Implementation_Plan.md's own I3 wording explicitly
   assigns that as "a small addition to Phase 4's J1," not this stage's.
   Nothing in game_server.py or session_coordinator.py calls this class
   at all yet.
3. It does not implement consistent hashing (Server_Design.md §5 names
   this only as an alternative "if session affinity... is preferred",
   not a requirement) or write the `room:{room_id} -> {shard_ip, port,
   worker_pid}` registry entry described in Server_Design.md §7 - that
   is a distinct piece of state (which shard a specific, already-
   allocated room landed on) from this class's own sorted set (which
   shard is CURRENTLY least loaded, in general); a real, separate,
   deliberately out-of-scope piece of the picture, not something this
   class's own sorted set happens to already cover.

WHY allocate() IS A SINGLE ATOMIC LUA SCRIPT (EVAL), NOT A
WATCH/MULTI/EXEC TRANSACTION: "picks the least-loaded shard" and
"increments its score on allocation" (Implementation_Plan.md's own I3
acceptance criteria) must happen as ONE atomic operation - reading the
current minimum and incrementing it as two separate Redis round trips
(`ZRANGE ... WITHSCORES` then `ZINCRBY`) has a real, narrow race window
under genuinely concurrent callers: two allocators could both read the
same "currently least-loaded" shard before either's own increment
lands, and both pick it (a lost-update bug in the one method whose
entire job is correct load balancing - see I3_prompt.md's own Background
section for why this is NOT the same kind of "acceptable interim gap"
as items 1/2 above). A `WATCH key` / `MULTI` / `EXEC` optimistic-locking
transaction could also solve this, but needs an explicit retry loop
(another client modifying the watched key between WATCH and EXEC aborts
the transaction, per redis-py's own documented behavior) - more code,
and a real, if unlikely, livelock risk under heavy contention with no
natural retry cap. A Lua script executed via EVAL is simpler and
provably correct instead: Redis executes an entire script as one atomic
step - no other client's command, including another EVAL of this same
script, can interleave partway through - so "find the current minimum"
and "increment it" are genuinely inseparable from every other caller's
own point of view, in a single round trip, with no retry logic needed at
all. test_game_allocator.py's own
`test_allocate_is_atomic_under_real_concurrent_callers` is the actual
proof of this, not just a code-read.

REGISTER_SHARD IS IDEMPOTENT (ZADD ... NX, not a plain overwriting
ZADD): a repeat `register_shard()` call for an already-registered
shard_id is a no-op, preserving whatever load that shard has already
accrued via `allocate()`/`release()` calls since. Chosen over
always-overwrite because the real caller (a periodic heartbeat
producer, Phase 4's job, see item 1 above) would plausibly re-announce
a shard's own presence on every heartbeat tick - an always-overwrite
`register_shard()` would silently reset an already-accurate load count
back to `initial_load` on every single one of those re-announcements,
which is never the intent of "this shard still exists."

EXPLICIT REGISTRATION IS REQUIRED BEFORE A SHARD CAN BE ALLOCATED -
allocate() NEVER IMPLICITLY REGISTERS ANYTHING: allocate() takes no
shard_id parameter at all (per its own required signature below), so
there is nothing for it to implicitly register even in principle - its
own Lua script only ever selects among sorted-set members that already
exist (`ZRANGE key 0 0`), it never creates one. The only way a new shard
ever enters the pool is its own explicit `register_shard()` call,
matching Server_Design.md §5's own real heartbeat model directly (each
shard announces ITSELF; nothing else can announce a shard on its
behalf). `release()`, unlike allocate(), DOES take a shard_id argument,
and IS implemented as a literal, plain `ZINCRBY key -1 shard_id` per
this stage's own explicit requirement wording - Redis's own ZINCRBY
creates a member with the increment as its score if it did not already
exist, so calling `release()` for a shard_id that was never
`register_shard()`-ed creates a phantom entry with score -1 rather than
raising. This is an accepted, narrow gap, not a silently-ignored one:
`release()`'s only real caller (Phase 4's GameSession teardown, item 2
above, explicitly out of scope here) would only ever pass a shard_id it
had itself received from a prior `allocate()` call, so in practice the
shard is always already known; this class does not defensively guard
against a hypothetically-mistaken caller passing an unknown shard_id
because doing so is not part of this stage's own required scope.

CONSTRUCTOR SHAPE MIRRORS RedisSessionCoordinator'S OWN ESTABLISHED
CONVENTION EXACTLY (session_coordinator.py, Stage I2), FOR CONSISTENCY
ACROSS THIS PROJECT'S REDIS-BACKED CLASSES: `redis_url`/`client` mutually
exclusive (production passes `redis_url`; tests inject an
already-connected `client`), `key_prefix` for test isolation against one
shared real Redis instance, synchronous `redis.Redis` (not
`redis.asyncio.Redis`) - same reasoning as that class's own docstring:
this is a plain, synchronous call shape, not part of any async Protocol
here either.
"""

from __future__ import annotations

from typing import Optional

import redis


class GameAllocatorError(Exception):
    """Base class for GameAllocator's own errors - mirrors
    server/application/room.py's own RoomError/RoomFullError
    per-class base-exception convention."""


class NoShardsRegisteredError(GameAllocatorError):
    """Raised by allocate() when no shard has ever been
    register_shard()'d (or every registration has since been removed
    from the underlying sorted set) - a real, specific exception per
    this stage's own "not a bare Exception" requirement, mirroring
    RoomFullError's own identical reasoning in room.py."""


class GameAllocator:
    """A Redis-backed least-loaded-shard selector - see module
    docstring for the full reasoning behind every decision below."""

    _SHARD_LOAD_KEY_SUFFIX = "shard_load"

    # See module docstring's "WHY allocate() IS A SINGLE ATOMIC LUA
    # SCRIPT..." section. KEYS[1] is this instance's own
    # `_shard_load_key` - passed positionally via EVALSHA/EVAL, never
    # hardcoded into the script itself, so one registered script object
    # is reusable across every GameAllocator instance/key_prefix.
    _ALLOCATE_SCRIPT = """
        local least_loaded = redis.call('ZRANGE', KEYS[1], 0, 0)
        if #least_loaded == 0 then
            return false
        end
        local shard_id = least_loaded[1]
        redis.call('ZINCRBY', KEYS[1], 1, shard_id)
        return shard_id
    """

    def __init__(
        self,
        redis_url: Optional[str] = None,
        client: Optional["redis.Redis"] = None,
        key_prefix: str = "kfchess",
    ) -> None:
        """Create an allocator.

        Args:
            redis_url: A real `redis://...` URL - this instance builds
                its own `redis.Redis.from_url(...)` client from it.
                Mutually exclusive with `client` (see module docstring's
                "CONSTRUCTOR SHAPE..." section).
            client: An already-constructed `redis.Redis` instance to use
                instead of building one from `redis_url` - injectable
                (DIP) purely for testability.
            key_prefix: Namespaces the Redis key this instance reads or
                writes (`f"{key_prefix}:shard_load"`) - defaults to
                `"kfchess"` for production; tests pass a unique prefix
                per test so parallel/repeated test runs against one
                real, shared Redis instance never collide with each
                other's own shard-load state, or with
                RedisSessionCoordinator's own `matchmaking:queue`/
                `rooms` keys under the same prefix.

        Returns:
            None.

        Raises:
            ValueError: If neither `redis_url` nor `client` is given.
        """

        if client is not None:
            self._client = client
        elif redis_url is not None:
            self._client = redis.Redis.from_url(redis_url, decode_responses=True)
        else:
            raise ValueError("GameAllocator requires either redis_url or client")

        self._shard_load_key = f"{key_prefix}:{self._SHARD_LOAD_KEY_SUFFIX}"
        self._allocate = self._client.register_script(self._ALLOCATE_SCRIPT)

    def register_shard(self, shard_id: str, initial_load: int = 0) -> None:
        """Register `shard_id` as selectable by allocate(), with an
        initial load score of `initial_load` - a shard's own load entry
        must exist before it can ever be chosen (see module docstring's
        "EXPLICIT REGISTRATION IS REQUIRED..." section).

        Idempotent (see module docstring's "REGISTER_SHARD IS
        IDEMPOTENT" section): a repeat call for an already-registered
        shard_id is a no-op - it does NOT reset that shard's own
        already-accrued load back to `initial_load`.

        Args:
            shard_id: This shard's own unique identifier.
            initial_load: The score to seed a NEW registration with
                (ignored if `shard_id` is already registered). Defaults
                to 0 - a freshly-started shard with no active matches
                yet.

        Returns:
            None.
        """

        self._client.zadd(self._shard_load_key, {shard_id: initial_load}, nx=True)

    def allocate(self) -> str:
        """Atomically select the currently lowest-scored (least-loaded)
        registered shard and increment its own score by 1, in the same
        atomic operation - see module docstring's "WHY allocate() IS A
        SINGLE ATOMIC LUA SCRIPT..." section for why this must be one
        indivisible step, not two separate Redis round trips.

        Returns:
            The chosen shard's own shard_id.

        Raises:
            NoShardsRegisteredError: If no shard is currently registered
                at all (the underlying sorted set is empty).
        """

        result = self._allocate(keys=[self._shard_load_key])
        if result is None or result is False:
            raise NoShardsRegisteredError(
                f"no shards registered under key {self._shard_load_key!r} - call register_shard() first"
            )
        return result

    def release(self, shard_id: str) -> None:
        """Decrement `shard_id`'s own score by 1 - a plain `ZINCRBY key
        -1 shard_id` (see module docstring's "EXPLICIT REGISTRATION..."
        section for why this is deliberately NOT guarded against an
        unknown shard_id). No atomicity concern here, unlike allocate():
        this only ever affects one specific, already-known shard, never
        a "find the minimum across every shard" query with a race window
        to close.

        Args:
            shard_id: The shard whose own load just decreased (e.g. a
                match it was hosting just ended).

        Returns:
            None.
        """

        self._client.zincrby(self._shard_load_key, -1, shard_id)
