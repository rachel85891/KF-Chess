# KF-Chess Cloud Scale — Implementation Plan

**Relationship to `Server_Design.md`:** that document is the *decisions*
record — what was chosen and why, organized by requirement (Parts 1–5).
**This document is the *execution* plan** — organized by buildable stage,
in dependency order, so work can actually start. Every stage below cites
the `Server_Design.md` section it implements; go there for the reasoning,
come here for the task list. Stage letters continue this project's own
existing convention (Stages B1→E2 already exist in the codebase; Stage F,
Rooms, is already planned separately) — this plan uses **G onward**.

> **Updated for the external design review** (PostgreSQL instead of
> Cassandra/ScyllaDB; NATS + Redis, decided together rather than left as an
> either/or; a full nine-service split — API Gateway, WebSocket Gateway,
> Auth Service, Rooms API, Matchmaker, Game Allocator, Match-Host/Game
> Server Shard, Rating Service — rather than three consolidated roles;
> one-worker-process-per-CPU-core multiprocessing inside each Match-Host
> pod; and a Docker Compose milestone before full Kubernetes) — see
> `Server_Design.md` §19 for the full reasoning behind each change. Also
> includes Stage G4, a lean delta-based wire protocol decided independently
> of the review, cutting the project's own measured traffic estimate from
> ~150–250 Gbps to a ~11 Gbps design estimate (`Server_Design.md` §14).
> Every stage below that changed as a result is marked *(revised)*.

---

## 0. Phase overview

> **Status, checked directly against the current codebase:** Phase 2
> (F1–F7) is **✅ done** — `room.py`, `session_coordinator.py`,
> `room_choice_command.py` all exist and match this plan's own design.
> **H2 is also ✅ done** — F2 *is* H2, the same piece of work, already
> implemented as part of Stage F. **The real next starting point is H1**
> (`UserRepository` → `Protocol`), still a concrete class today — in
> parallel with G1–G4, which have no dependency on anything.
>
> **Also flagged:** the `Server_Design.md` §-references throughout this
> plan (e.g. `§1.5`, `§5.3`) cite that document's *previous* Part 1–5
> numbering. `Server_Design.md` has since been rebuilt as 20 flat
> sections (§1–§20); these citations are stale pointers, not wrong
> content — a full remap is pending (tracked for the next joint cleanup
> pass) but doesn't block starting work on any stage below, since each
> stage's files/tasks/acceptance-criteria are unchanged either way.

| Phase | Stages | What it delivers | Depends on |
|---|---|---|---|
| 0 | G1–G4 | Immediate, zero-dependency wins — no infra needed | Nothing — start today |
| 1 | H1–H2 | Foundational `Protocol` abstractions, in-memory only | Nothing — pure refactor. **H2: ✅ done** (see status note above) |
| 2 | F1–F7 | Rooms + Viewers feature, fully detailed below | **✅ done** (see status note above) |
| 3 | I0–I9 | *(revised)* Docker Compose small working version, then real distributed backends (PostgreSQL, Redis, NATS) plus the full service split (Auth/Rooms-API/Matchmaker/Game-Allocator/Rating Service) and per-shard multiprocessing | H1 (not yet done), H2 (✅ done); I0 needs only Docker, not K3s |
| 4 | J1–J5 | *(revised)* Full nine-service topology split, on K8s | I0–I9 |
| 5 | K1–K4 | Resilience hardening | J1–J5 |
| 6 | L1–L3 | Operations, monitoring, capacity validation | J1–J5, K1–K4 |

**Why this order:** Phase 0 and Phase 1 need nothing but this repo and a
Python environment — they can start in parallel, today, before any cloud
provider or K8s cluster exists. **Phase 2 is already complete** — it's
listed here for dependency-graph completeness, not as remaining work.
**Phase 3 now starts with I0, a Docker Compose milestone that needs only
Docker** (not a K3s cluster) — matching the priority of shipping
"something small that works" before the full Kubernetes topology. Phases
3–6 remain otherwise sequential — each needs the previous phase's
infrastructure actually running.

---

## Phase 0 — Immediate, zero-dependency wins

No cloud infra, no new abstractions — small, isolated, high-value changes
identified in `Server_Design.md` Parts 3 and 5.

### G1 — Client auto-reconnect (`Server_Design.md` §5.3)

**Highest-leverage single change in this whole plan** — the server-side
recovery mechanism (Stage E2) already exists and is correct; this is the
one missing piece that activates it.

- **File:** `kungfu_chess/client/network/network_game_client.py`
- **Task:** in `_receive_loop`'s `ConnectionClosed` handling, instead of
  silently swallowing the exception, trigger a reconnect attempt:
  reopen `websockets.connect(uri)` with exponential backoff (e.g. 0.5s,
  1s, 2s, capped), then re-run the existing AUTH flow
  (`_do_connect`/AUTH message) automatically.
- **Acceptance criteria (headless, no real network needed if a fake
  `ServerConnection`/test double is used — matches this project's existing
  test conventions):**
  - A test that closes the underlying connection mid-match and asserts a
    new connection attempt is made within the backoff window.
  - An integration test (real local server, Stage E2's own existing
    countdown-window test pattern) confirming a client that reconnects
    within 20s resumes the same match/color, using the mechanism that
    already exists server-side.
  - A test confirming reconnect attempts stop (or surface a clear error)
    once the Stage E2 countdown window has actually expired server-side.

### G2 — WebSocket compression (`Server_Design.md` §3.6)

- **File:** `server/main.py` (wherever `websockets.serve(...)` is called).
- **Task:** pass `compression="deflate"` (or the equivalent
  `permessage-deflate` extension configuration for the installed
  `websockets` version) to the server's `serve()` call. Verify the client
  side (`websockets.connect(...)` in `network_game_client.py`) negotiates
  the same extension — usually automatic if both sides support it.
- **Acceptance criteria:** existing integration tests still pass unchanged
  (compression is transparent to the wire format); optionally, a manual
  check confirming the negotiated extension appears in the WebSocket
  handshake headers during a real connection.

### G3 — `uvloop` for the server process (`Server_Design.md` §3.6)

- **File:** `server/main.py`, `requirements.txt`.
- **Task:** add `uvloop` to `requirements.txt`; at the top of `main.py`'s
  entry point, call `uvloop.install()` (or use
  `asyncio.run(..., loop_factory=uvloop.new_event_loop)` depending on the
  Python version in use) before starting the event loop.
### G4 — Lean wire protocol: sequence numbers + delta board/log (`Server_Design.md` §3.5/§3.8 — chosen after comparison against the colleague's ~16 Gbps estimate)

**Why this is in Phase 0, not deferred:** no cloud infra needed — this is a
pure protocol/application-layer change, buildable and testable today,
exactly like G1–G3.

- **Files:**
  - `server/presentation/protocol_handler.py` — three new message types:
    - `BOARD_DELTA:<seq>:<cell>:<token>,<cell>:<token>,...` — only the
      squares that changed since the last broadcast in this match (usually
      2: the from-cell and to-cell), not the full 64-square board.
    - `LOG_DELTA:<seq>:<entry>` — only the single newest move/capture-log
      entry, not the full accumulated history.
    - `RESYNC_REQUEST` (client → server) — "I detected a gap in `seq`,
      send me a full state."
  - `server/application/game_server.py` — each match tracks its own
    monotonically-increasing `seq` counter; `_broadcast_event` computes the
    diff between the previous broadcast's board and the current one
    (instead of re-printing the full board every time), and sends only the
    newest log entry (instead of the full accumulated `MovesLogSnapshot`).
  - **The existing full-board/full-log messages are kept, not deleted** —
    reused as the "keyframe" response to `RESYNC_REQUEST`, so a client that
    ever loses sync can always recover fully.
  - `kungfu_chess/client/network/network_game_client.py` — track the last
    `seq` received per room; on a gap (received `seq` isn't exactly
    `last_seq + 1`), send `RESYNC_REQUEST` and apply the returned full
    board/log as a fresh baseline before resuming delta application.
- **Acceptance criteria:**
  - Unit test: given a previous board and a new board differing in exactly
    2 squares, the delta-computation function returns exactly those 2
    squares, nothing else.
  - Unit test: `LOG_DELTA` contains only the newest entry, regardless of
    how many entries the match has accumulated (this is the test that
    directly proves the quadratic-growth problem from §3.5 is gone — the
    message size must stay constant as match length grows, not increase).
  - Integration test: simulate a dropped message (skip a `seq` on the
    client side deliberately) and confirm the client sends
    `RESYNC_REQUEST` and correctly resumes from the returned keyframe.
  - Regression test: a client that never drops a message ends up with the
    exact same final board/log state as today's full-resend design would
    produce — this change must be invisible in outcome, only smaller on
    the wire.
- **Expected result (a design estimate, not yet a measurement — validate
  against Phase 6's L3 load test once this is built):** roughly ~70 bytes
  per broadcast event instead of the current ~782-byte representative
  figure — bringing the fleet-wide aggregate from Part 3's measured
  ~150–250 Gbps down to a design estimate of **~11 Gbps**, converging with
  the colleague's own ~16 Gbps estimate (see `Server_Design.md` Part 3 for
  the full before/after comparison).

---

## Phase 1 — Foundational `Protocol` abstractions (in-memory only)

Pure refactors — no new infrastructure, no behavior change for any existing
caller. These unlock every later phase without needing a cloud provider,
PostgreSQL, or Redis to exist yet.

### H1 — `UserRepository` becomes a `Protocol` (`Server_Design.md` §1.5)

- **Files:**
  - `server/persistence/user_repository.py` — rename the existing concrete
    class `UserRepository` → `SqliteUserRepository`. No internal logic
    changes (PBKDF2 scheme, salt handling, schema — all unchanged).
  - New file `server/persistence/user_repository_protocol.py` (or add to
    an `__init__.py` if preferred) defining:
    ```python
    class UserRepository(Protocol):
        def create_account(self, username: str, password: str) -> bool: ...
        def verify_login(self, username: str, password: str) -> bool: ...
        def get_rating(self, username: str) -> int: ...
        def update_rating(self, username: str, new_rating: int) -> None: ...
    ```
  - Update every import site (`GameServer`/auth flow) to import the
    `Protocol`, not `SqliteUserRepository`, for type hints — the concrete
    class passed in at composition-root time (`server/main.py`) is the
    only place that still names `SqliteUserRepository` directly.
- **Acceptance criteria:** the entire existing test suite for
  `UserRepository` passes unchanged against `SqliteUserRepository` (proves
  the rename didn't change behavior); a new, trivial test asserts
  `SqliteUserRepository` satisfies the `Protocol` (e.g. via
  `isinstance(repo, UserRepository)` if using `@runtime_checkable`, or a
  static type-check pass with `mypy`/`pyright`).

### H2 — `SessionCoordinator` `Protocol` + in-memory implementation — ✅ DONE (identical work to F2 below)

This is the single most structurally important stage in this plan — it's
the shared foundation both the Rooms feature (Phase 2/Stage F) and the
production topology (Phase 3) build on.

- **Files:**
  - New `server/application/session_coordinator.py`:
    ```python
    class SessionCoordinator(Protocol):
        def find_match(self, username: str, rating: int) -> Optional[MatchResult]: ...
        def create_room(self, host: TOccupant) -> RoomCode: ...
        def join_room(self, code: RoomCode, occupant: TOccupant) -> JoinResult: ...
    ```
  - New `server/application/in_memory_session_coordinator.py` —
    **adapts, doesn't rewrite**, the existing `MatchmakingQueue` (E1) for
    `find_match`, and Stage F1's `Room`/`RoomCodeGenerator` for
    `create_room`/`join_room`, unified behind this one `Protocol`.
  - `GameServer` (`server/application/game_server.py`) refactored to
    depend only on `SessionCoordinator`, injected at construction —
    **careful, incremental refactor**, per the risk already flagged when
    this stage was first planned: requires safety-net tests *before* the
    change, covering existing E1 matchmaking behavior exactly as it works
    today, so the refactor can be verified to change nothing observable.
- **Acceptance criteria:**
  - Safety-net test suite (written *first*, against current `GameServer` +
    `MatchmakingQueue` behavior, before any refactor) — must pass
    unchanged after the refactor.
  - New unit tests for `InMemorySessionCoordinator` in isolation (no
    `GameServer`, no networking) covering `find_match` (existing E1
    semantics), `create_room`/`join_room` (Stage F1's `Room` semantics).
  - `GameServer`'s own existing integration test suite passes unchanged.

---

## Phase 2 — Rooms + Viewers (Stage F1–F7)

**F1 has no dependency on this plan at all** (pure, headless — can start
immediately, in parallel with Phase 0/1). **F2 IS H2** — not a second,
parallel effort — the `SessionCoordinator` `Protocol` and its in-memory
implementation are one piece of work, shared by both this feature and the
production topology in Phase 3/4. F3 onward proceeds only after F2/H2 is
in place.

### F1 — `RoomCode` + `Room` (pure, headless — no networking, no `GameServer`) — ✅ DONE

- **Files:**
  - `server/application/room_code.py` — `RoomCode` value object; named
    constants `ROOM_CODE_LENGTH`, `ROOM_CODE_ALPHABET` (no magic
    numbers/strings); validates length/alphabet in `__post_init__`; does
    **not** check uniqueness (that's F2's job).
  - `server/application/room_code_generator.py` — `RoomCodeGenerator`,
    single job: produce one candidate `RoomCode`. Constructor injects a
    `random_source` callable (default backed by `secrets`, matching the
    convention `UserRepository` already established) — same
    inject-the-callable pattern this project already uses for `clock` in
    `MatchmakingQueue`, so tests can supply a deterministic stub.
  - `server/application/room.py` — `RoomOccupantRole` enum
    (`WHITE`/`BLACK`/`VIEWER`, all three defined now even though enforcing
    `VIEWER`'s rejection is F5's job) and `Room[TOccupant]` — generic over
    an opaque occupant type so it never imports `ServerConnection`;
    `add_occupant()` assigns White → Black → Viewer in join order;
    `is_ready_to_start` property.
  - `tests/unit/server/application/test_room_code.py`,
    `test_room_code_generator.py`, `test_room.py`.
- **Acceptance criteria:**
  - `RoomCode`: equal values compare equal; wrong length/alphabet rejected;
    readable `repr`.
  - `RoomCodeGenerator`: real default produces a code of the configured
    length from the configured alphabet; a stubbed `random_source` produces
    a deterministic, exactly-assertable code.
  - `Room`: 1st occupant → White, 2nd → Black, 3rd+ → Viewer;
    `is_ready_to_start` false until both colors filled, true after; a
    negative test confirming `Room` never references any external registry
    or other `Room` instance.
- **Open decision blocking this stage's completion (not its start):**
  exact `ROOM_CODE_LENGTH` and whether to exclude visually-ambiguous
  characters (O/0, I/1, L) — flagged, not decided unilaterally; assume 6
  characters, ambiguous-excluded, until confirmed.

### F2 — `SessionCoordinator` (identical work item to Phase 1's H2 — see there for full detail) — ✅ DONE

This is the stage where `MatchmakingQueue` (existing, Stage E1) and F1's
`Room` get unified behind one `Protocol`
(`find_match`/`create_room`/`join_room`). **Do this once, in H2, not
twice.** The one F-specific addition on top of H2's own content: the
in-memory `create_room`/`join_room` implementation must use F1's
`RoomCodeGenerator` for new codes and retry on collision — this is
precisely the uniqueness check F1 §deliberately left out, and the reason
it belongs at the coordinator level, not inside `Room` or
`RoomCodeGenerator` themselves.

- **Acceptance criteria (in addition to H2's own):** a test that forces a
  collision (stub `RoomCodeGenerator` to return the same code twice) and
  asserts the coordinator retries and produces a second, distinct code
  rather than silently overwriting the first room.

### F3 — Wire protocol messages (Create/Join) — presentation layer only — ✅ DONE

- **File:** `server/presentation/protocol_handler.py`.
- **Task:** add parsing for the post-AUTH choice
  (`PLAY` / `CREATE_ROOM` / `JOIN_ROOM:<code>`), and formatting for the
  server's responses (`room_created:<code>`, `room_joined:<role>`,
  `room_not_found`, etc.), following the exact same
  `"prefix:<detail>"` colon-delimited convention every other message in
  this project already uses. **No `SessionCoordinator`/`GameServer` logic
  touched here** — this stage is parsing/formatting only, exactly like the
  existing split between `ProtocolHandler` and `GameServer`.
- **Acceptance criteria:** unit tests for `ProtocolHandler` alone (no
  networking, no `GameServer`) — round-trip parse/format for each new
  message, malformed-input handling (e.g. a `JOIN_ROOM:` with no code,
  or a code that fails F1's own alphabet/length validation).

### F4 — Real wiring into `GameServer` — ✅ DONE

- **File:** `server/application/game_server.py`.
- **Task:** after AUTH, branch on the client's F3 choice; `PLAY` calls
  `SessionCoordinator.find_match` (existing E1 behavior, unchanged);
  `CREATE_ROOM`/`JOIN_ROOM` call the corresponding F2/H2 methods. When a
  room's `is_ready_to_start` becomes true, create the actual `GameSession`
  exactly the same way today's matchmaking path already does — reusing
  that construction logic, not duplicating it.
- **Acceptance criteria:** integration test with real local WebSocket
  connections: two clients, one creates a room and receives a code, the
  second joins with that code, both end up in the same live `GameSession`
  with correct colors; a third, independent client using `PLAY` still
  matchmakes exactly as today (non-regression check against the Phase 1
  H2 safety-net suite).

### F5 — Viewer role enforcement — ✅ DONE

- **Files:** `server/application/game_server.py` (move/jump handling),
  reusing the existing rejection path already used for `wrong_color`.
- **Task:** when a `move`/`jump` command arrives from an occupant whose
  `RoomOccupantRole` is `VIEWER` (F1), reject it via the same rejection
  mechanism `wrong_color` already uses — a third value on an existing
  mechanism, not a new one.
- **Acceptance criteria:** a room with 2 players + 1 viewer; the viewer's
  move/jump attempts are rejected with the same rejection-reason shape as
  an existing `wrong_color` test; the viewer still receives all normal
  broadcasts (board, events).

### F6 — Broadcast correctness for a variable number of viewers — ✅ DONE

- **File:** `server/application/game_server.py` (`_broadcast_event` and
  any other iteration over "connections in this match").
- **Task:** audit every broadcast loop to confirm it iterates over
  *all* connections currently in the room (both players plus however many
  viewers), never a hardcoded assumption of exactly 2. This is a
  correctness audit more than new logic — Part 2 §2.4 of `Server_Design.md`
  already flagged this exact fan-out concern for the cloud topology; get
  it right here, once, rather than fixing it twice later.
- **Acceptance criteria:** a test with 2 players + 3 viewers (5
  connections) in one room; assert all 5 receive every broadcast
  identically; a second test with 0 viewers confirms no regression for the
  common case.

### F7 — Client: room menu + viewer mode — ✅ DONE

- **Files:**
  - `kungfu_chess/client/.../home_screen.py` — add a Play / Create Room /
    Join Room menu, sending the corresponding F3 wire message.
  - `kungfu_chess/client/loop/network_game_loop_runner.py` — a viewer
    mode: when the server assigns `VIEWER` (F5), skip constructing
    `MouseAdapter`/`NetworkClickController` entirely — there's nothing for
    a viewer to click, so the input layer simply isn't built for this
    session, rather than being built and then blocked.
- **Acceptance criteria:** a client-side test confirming no
  `MouseAdapter`/`NetworkClickController` instance exists when running in
  viewer mode; a `home_screen.py` test confirming each menu choice sends
  the correct F3 wire message.

---

## Phase 3 — Docker Compose milestone, then real distributed backends *(revised)*

**This phase now has two parts, not one** — directly reflecting the
external review's own instruction: *"something small that works"* before
the full topology. I0 needs **only Docker** (not a K3s cluster); I1
onward needs K3s and is where the "learn Docker/K8s/K3s independently"
requirement gates further progress. Cloud-provider choice remains open
(`Server_Design.md` §1.7) — everything in this phase is provider-agnostic
by design (self-hosted, open-source components), so nothing here blocks
on that decision.

### I0 — Docker Compose: small, working, end-to-end version (new, `Server_Design.md` §1.9/§2.10's "small that works" principle)

**Do this stage first, before I1–I4.** Goal: one `docker-compose.yml`
that brings up a minimal but *real* version of every backend component,
runs locally, and plays one full game end-to-end — proving the
architecture works before investing in the full K3s topology.

- **File:** new `deploy/docker-compose.yml` at the repo root.
- **Task:** define services for: `postgres` (official image, one
  container, no replication yet — that's I1), `redis` (official image,
  single instance, no Sentinel/Cluster yet — that's I2), the existing
  server process (`server/main.py`, unchanged — Phase 4's role split
  hasn't happened yet at this stage), built from a single `Dockerfile`
  at the repo root.
- **Task:** wire the existing `UserRepository`/`SessionCoordinator`
  composition root (`server/main.py`) to read connection strings from
  environment variables (`POSTGRES_URL`, `REDIS_URL`) rather than
  hardcoded paths, so the same code runs against Docker Compose's
  services instead of local SQLite/in-memory defaults.
- **Acceptance criteria:** `docker-compose up` brings up all containers
  healthy; a manual end-to-end test (two real clients, or the existing
  integration test suite pointed at the Compose stack via environment
  variables) completes one full match, with the account created via
  Postgres and matchmaking coordinated via Redis. **This is the
  milestone to demo, not Phase 4's full K3s topology** — smaller scope,
  proves the architecture, satisfies the review's explicit preference.

### I1 — PostgreSQL deployment + `UserRepository` production backend (`Server_Design.md` §1.3, §1.7, §1.9, §5.4) *(revised: PostgreSQL, not Cassandra/ScyllaDB)*

- **Infra:** deploy PostgreSQL onto the K3s cluster (a Helm chart, e.g.
  `bitnami/postgresql`, or the Postgres Operator if HA is set up directly)
  with **streaming replication** to at least one standby, and automated
  failover tooling (e.g. Patroni) per `Server_Design.md` §5.4's revised
  failure-mode design.
- **Code:** new `server/persistence/postgres_user_repository.py`
  implementing the `UserRepository` `Protocol` from H1 — ordinary SQL
  (`INSERT`/`SELECT`/`UPDATE` against a `users` table);
  `create_account`/`verify_login`/`update_rating` routed to the primary,
  `get_rating` eligible to read from a replica (§1.7's per-operation
  routing). Same PBKDF2 hashing scheme, unchanged.
- **Acceptance criteria:** the *exact same* `UserRepository` `Protocol`
  test suite from H1 (parameterized/re-run against this new
  implementation, not a new test file) passes unchanged — proves the
  swap is truly transparent to callers, the entire point of H1's
  refactor. Add a failover chaos test: kill the primary mid-test-run,
  confirm the standby is promoted and writes resume within the
  configured failover window; confirm `get_rating` (routed to a
  replica) is largely unaffected throughout, per §5.4's own reasoning.
- **Flagged, not resolved in this stage:** the single-primary
  write-throughput ceiling against the ~166K writes/sec peak estimate
  (`Server_Design.md` §1.7 item 4) — Citus is the named scale-out path,
  not implemented here, per the review's own "small that works first"
  priority.

### I2 — Redis deployment + caching layer + `SessionCoordinator` production backend, now with pub/sub (`Server_Design.md` §1.6, §2.3, §2.4, §2.6, §5.5) *(revised: adds NATS/Redis Pub/Sub)*

- **Infra:** deploy Redis via Sentinel or Cluster mode (not a single
  instance) on K3s. Per §5.5/§5.9's recommendation, evaluate running
  **without** RDB/AOF persistence given this store's bounded-loss-tolerant
  data. **Decide NATS vs. Redis Pub/Sub for the message relay here**
  (`Server_Design.md` §2.9's flagged open item) — Redis Pub/Sub reuses
  this same deployment (fewer moving parts); NATS is a separate
  deployment with stronger delivery guarantees (JetStream). Default to
  Redis Pub/Sub for I2/I0's "small that works" scope unless a concrete
  reason to add NATS emerges.
- **Code:**
  - `server/persistence/cached_user_repository.py` — a decorator
    implementing the same `UserRepository` `Protocol`, wrapping any other
    implementation with a Redis read-through cache in front of
    `get_rating` specifically (§1.6).
  - `server/application/redis_session_coordinator.py` implementing the
    `SessionCoordinator` `Protocol` from H2: matchmaking queue as a Redis
    sorted set, room registry as a Redis hash, Match-Host ownership
    records as key-value entries used by I3's Game Allocator
    (`Server_Design.md` §2.3's table, implemented directly).
- **Acceptance criteria:** the *same* `SessionCoordinator` `Protocol` test
  suite from H2 passes against this Redis-backed implementation unchanged.
  Add a Sentinel-failover chaos test: trigger a failover mid-test, confirm
  behavior matches §5.5's documented bounded-loss expectation (an
  in-flight queue entry may be lost and must be retryable, not that the
  system stays fully available through the failover).

### I3 — Game Allocator (new, `Server_Design.md` §2.3, adopted from the external design review)

- **File:** new `server/application/game_allocator.py`.
- **Task:** implement least-loaded Match-Host selection as a second Redis
  sorted set, scored by each Match-Host pod's current active-match count
  (not rating — a distinct sorted set from I2's matchmaking queue, same
  Redis primitive reused). Called by the WebSocket Gateway role (Phase 4)
  at the moment `SessionCoordinator` resolves a match/room as ready.
- **Acceptance criteria:** a unit test with several stubbed Match-Host
  "load" entries confirms the allocator always returns the currently
  lowest-scored pod; a test confirms the allocator updates a pod's score
  correctly as matches start/end on it (increment on allocation,
  decrement on completion — this decrement needs a corresponding call
  from Match-Host's own `GameSession`-teardown path, a small addition to
  Phase 4's J1).

### I4 — `server_full` safety valve reinstated (`Server_Design.md` §5.7)

- **File:** `server/application/game_server.py`,
  `server/presentation/protocol_handler.py` (message already exists,
  needs an active caller again).
- **Task:** add a configurable per-process connection cap; on a new
  connection once at cap, send the existing `SERVER_FULL_MESSAGE` and
  close, rather than accepting.
- **Acceptance criteria:** a test that fills a `GameServer` instance to its
  configured cap and asserts the next connection receives `server_full`
  and is closed, mirroring the *removed* old test this project's own
  history already had for the fixed-single-match design (same assertion
  shape, new trigger condition).

### I5 — Split Auth Service out of the API Gateway (new, `Server_Design.md` §2, §19.2)

- **File:** new `server/application/auth_service.py` — wraps I1's
  `UserRepository` (`create_account`/`verify_login`/`get_rating`) behind
  its own internal RPC boundary, called by the API Gateway rather than
  the Gateway holding a `UserRepository` reference directly.
- **Task:** the API Gateway (J1) is refactored to call this service
  instead of `UserRepository` directly — a thin network hop internally,
  matching the reviewed architecture's own service boundary (§2's table).
- **Acceptance criteria:** the existing `UserRepository` `Protocol` test
  suite is unaffected (this is a caller-side change only); a new
  integration test confirms the API Gateway's AUTH flow works identically
  through the new internal call, not directly.

### I6 — Split Rooms API (CRUD/history) from live allocation (new, `Server_Design.md` §2, §19.2)

- **File:** new `server/application/rooms_api.py` — room create/list/
  inspect and match-history queries, backed by I1's PostgreSQL (once
  match history is actually persisted — see I8) and I2's Redis (for
  currently-active room lookups).
- **Task:** `SessionCoordinator.create_room`/`join_room` (Stage F2) is
  refactored so room *bookkeeping* (this stage) is distinct from the
  *allocation decision* (I3's `GameAllocator`) — today both are conflated
  in one call, correct for a single process, but not once these become
  two separate deployables.
- **Acceptance criteria:** the existing `SessionCoordinator` `Protocol`
  test suite (Stage F2/H2) passes unchanged against the refactored split;
  a new test confirms `create_room` no longer makes any shard-assignment
  decision itself — that call now goes through I3 explicitly.

### I7 — Matchmaker as its own explicit component, distinct from Game Allocator (new, `Server_Design.md` §2, §19.2)

- **File:** new `server/application/matchmaker.py` — wraps the existing
  `MatchmakingQueue` (Stage E1, unchanged internally) behind its own
  service boundary; on a successful pairing, emits a "matched" event
  (via NATS, once I2's pub/sub choice is wired — see I2) rather than
  returning the result directly to whatever called `find_match`.
- **Task:** `SessionCoordinator.find_match` becomes a thin adapter that
  publishes to the Matchmaker rather than containing the pairing logic
  itself directly.
- **Acceptance criteria:** `MatchmakingQueue`'s own existing unit test
  suite (Stage E1) passes completely unchanged (proves this is a pure
  wrapping, not a rewrite); a new test confirms a successful pairing
  produces exactly one "matched" event, consumed once.

### I8 — Rating Service as its own event-driven component (new, `Server_Design.md` §2, §16, §19.2)

- **File:** new `server/application/rating_service.py` — wraps the
  existing `elo_rating.py` (unchanged internally); subscribes to a
  "match completed" event (NATS) rather than being called directly from
  `game_server.py`/`GameSession` teardown.
- **Task:** `GameSession`'s own end-of-match path (checkmate/timeout/
  resignation) is changed to *publish* the match result rather than call
  `UserRepository.update_rating` inline — the Rating Service is what
  actually performs that write, and additionally persists match history
  to PostgreSQL (the first real implementation of "games, results, move
  history" from `Server_Design.md` §1.9/§12).
- **Acceptance criteria:** `elo_rating.py`'s own existing unit tests pass
  unchanged; a new integration test confirms a completed match produces
  exactly one rating update and one match-history row, even if the event
  is (harmlessly) delivered twice — an idempotency test, since at-least-
  once delivery is a real property of most pub/sub systems, not
  something to assume away.

### I9 — Multiprocessing per Game Server Shard: one worker process per CPU core (new, `Server_Design.md` §10, §19.2 — the concrete fix for the Part 2 §2.1 CPU bottleneck this project's own earlier analysis flagged but never resolved)

- **Files:** `server/main_match_host.py` restructured into a
  **supervisor** process that spawns and monitors **N worker
  processes** (`multiprocessing`, N = configured CPU core count), each
  running its own independent `asyncio` event loop and owning a disjoint
  subset of the pod's active rooms — not one asyncio process trying to
  share a single core across every room the pod hosts.
- **Task:** the supervisor heartbeats aggregate pod load (sum of all its
  workers' active-match counts) into I3's Game Allocator sorted set,
  same as before — but the *routing* now needs one more level of
  precision: the pub/sub topic name (J2) or presence record must include
  the specific worker's identifier, not just the pod's, so a message
  reaches the exact process hosting that room, bypassing the supervisor
  on the hot path.
- **Acceptance criteria:** a load test confirming total rooms hosted by
  one pod scales close to linearly with configured worker count (proving
  real parallelism, not just concurrency) — this is the first stage that
  can actually produce a *measured* per-pod capacity number, closing the
  open item flagged repeatedly since Part 2 §2.9/§3.9 of the earlier
  document. A supervisor-crash test confirms workers are re-spawned
  without losing already-in-progress rooms hosted by *other* still-alive
  workers.

---

## Phase 4 — Full nine-service topology split (`Server_Design.md` Part 2, Part 4, §2, §19.2) *(revised: nine services, pub/sub relay, multiprocessing — not three roles)*

**Prerequisite:** Phase 3's backends (I0–I9) deployed and reachable from
the K3s cluster.

### J1 — Split composition roots *(revised: entry points for all nine services, not three)*

- **Files:** new `server/main_api_gateway.py`, `server/main_ws_gateway.py`,
  `server/main_auth_service.py` (I5), `server/main_rooms_api.py` (I6),
  `server/main_matchmaker.py` (I7), `server/main_game_allocator.py` (I3),
  `server/main_match_host.py`, and `server/main_rating_service.py` (I8) —
  seven new entry points total, replacing the single existing
  `server/main.py`.
- **Task:**
  - `main_api_gateway.py` calls I5's Auth Service internally (not
    `UserRepository` directly) for AUTH; forwards room CRUD/history
    requests to I6's Rooms API. No WebSocket handling, no
    `SessionCoordinator`, no `GameSession` knowledge at all
    (`Server_Design.md` §2's Role A0).
  - `main_ws_gateway.py` wires `ConnectionManager`, calls I7's Matchmaker
    and I6's Rooms API (not `SessionCoordinator` directly — that class is
    now split across I6/I7/I3, see those stages), and J3's relay to reach
    whichever Match-Host is allocated. No `GameSession`/tick loop, no
    direct `UserRepository` access (AUTH now belongs to the API Gateway;
    the WebSocket Gateway trusts a session token issued by it — a small,
    real protocol addition worth scoping explicitly when this stage
    starts).
  - `main_auth_service.py`, `main_rooms_api.py`, `main_matchmaker.py`,
    `main_game_allocator.py`, `main_rating_service.py` each wire exactly
    one of I5–I8/I3's own components and nothing else — no networking
    beyond their own internal RPC/pub-sub surface.
  - `main_match_host.py` becomes I9's supervisor entry point (worker
    processes, not a single asyncio loop) — reachable *internally* only,
    via J2's pub/sub, never client-facing.
- **Acceptance criteria:** each new entry point has its own smoke test
  confirming it starts and exposes only the responsibilities described
  above (e.g. a Match-Host instance has no code path for a raw client AUTH
  message; an API Gateway instance has no code path for a `move`/`jump`
  message; the Rating Service has no code path reachable from a client at
  all, only from the "match completed" event).

### J2 — Gateway↔Match-Host pub/sub relay (`Server_Design.md` §2.4, §2.10) *(revised: pub/sub, not direct TCP)*

- **New module:** `server/application/relay.py` — the WebSocket-Gateway-side
  component that, once `SessionCoordinator` + the Game Allocator (I3)
  resolve a match to a specific `match_id`/Match-Host pairing, **publishes**
  each client message to a `match.<match_id>.client_to_server` topic
  (Redis Pub/Sub, per I2's decision) and **subscribes** to
  `match.<match_id>.server_to_client` — no address resolution, no held
  connection to a specific pod.
- **Task (Match-Host side):** the corresponding subscriber/publisher pair
  in `main_match_host.py`'s own composition — subscribes to the
  `client_to_server` topic for each `GameSession` it hosts, publishes to
  the matching `server_to_client` topic.
- **Acceptance criteria:** an integration test with one WebSocket Gateway
  process and one Match-Host process (both local, against a real Redis
  instance — I0's Docker Compose stack is the natural place to run this)
  confirming a full move round-trip (client → WebSocket Gateway →
  Match-Host → WebSocket Gateway → client) produces identical wire output
  to the current single-process design's own existing integration tests.
  A second test with **multiple subscribers** to the same
  `server_to_client` topic (simulating Stage F5/F6 Viewers) confirms
  identical fan-out to all of them — directly exercising the "solves
  Viewer fan-out for free" property named in `Server_Design.md` §2.4.

### J3 — Game Allocator wiring into the WebSocket Gateway (new, companion to I3)

- **File:** `server/main_ws_gateway.py`.
- **Task:** call I3's `GameAllocator` at the moment `SessionCoordinator`
  resolves a match/room as ready; pass the resulting `match_id` to J2's
  relay so it knows which pub/sub topics to use.
- **Acceptance criteria:** an integration test confirming a new match is
  allocated to the currently-least-loaded Match-Host pod among several
  running instances (extends I3's own unit tests to a real multi-pod
  scenario).

### J4 — Dockerfiles + Kubernetes manifests *(revised: nine services)*

- **New directory:** `deploy/` (already has `docker-compose.yml` from
  I0) containing one `Dockerfile` + one K8s `Deployment`/`Service`/HPA
  manifest set per service: `api-gateway`, `ws-gateway`, `auth-service`,
  `rooms-api`, `matchmaker`, `game-allocator`, `match-host`
  (`game-server-shard`), `rating-service` — each its own image, no shared
  "mega-container" (`Server_Design.md` §8's own stated rationale).
  `match-host`'s `Service` is `ClusterIP`, internal-only (reached only via
  J2's Pub/Sub, never directly); the rest are reached via the public LB
  or internal RPC as appropriate to each (§4's transport table).
- **HPA manifests, one metric per service, not one generic policy:** API
  Gateway/Auth/Rooms-API/Rating-Service on request rate; WebSocket
  Gateway on connection count; Matchmaker/Game-Allocator on queue depth/
  allocation-request rate; Match-Host on active-match count (all custom
  metrics, per `Server_Design.md` §2.5/§2.7/§4.8 item 1).
- **Acceptance criteria:** all nine images build successfully; a local
  K3s deployment (`kubectl apply -f deploy/k8s/`) brings up every service
  and a manual end-to-end game (two local clients) completes successfully
  through the full API Gateway (AUTH via Auth Service) → WebSocket
  Gateway → Matchmaker → Game Allocator → Match-Host pub/sub relay path,
  with a match-history row appearing via the Rating Service at game end.

### J5 — Graceful shutdown (`Server_Design.md` §4.4, §4.8 item 2)

- **File:** `server/main_match_host.py`, plus the corresponding K8s
  manifest's `preStop`/`terminationGracePeriodSeconds` fields.
- **Task:** implement the cordon-then-drain sequence: on `SIGTERM`, stop
  advertising this pod as available in I3's Game Allocator sorted set
  (remove it or set its load score to a sentinel "not accepting" value),
  wait (up to the configured grace period, ≥90s + margin) for the pod's
  own active `GameSession` count to reach zero, then exit.
- **Acceptance criteria:** an integration test sends `SIGTERM` to a
  Match-Host process mid-match and asserts (a) it stops accepting new
  match assignments immediately, (b) the in-progress match is allowed to
  finish normally, (c) the process exits only after that match ends.

---

## Phase 5 — Resilience hardening (`Server_Design.md` Part 5)

**Prerequisite:** Phase 4's topology actually running (these failure modes
only exist once there's more than one process).

### K1 — `match_aborted` wire message + Match-Host-crash handling (`Server_Design.md` §5.2)

- **Files:** `server/presentation/protocol_handler.py` (new
  `format_match_aborted(reason: str) -> str` following the existing
  `"prefix:<detail>"` convention), `server/application/relay.py` (J2 —
  detect the Match-Host side going silent on its
  `server_to_client` pub/sub topic, e.g. via a heartbeat/liveness
  convention on the topic itself since pub/sub has no "connection closed"
  event the way a direct TCP relay would; send `match_aborted` to both
  real clients via the WebSocket Gateway).
- **Task:** confirm no `update_rating` call fires for a match ended this
  way (Part 5's correctness requirement) — likely means the abort path
  bypasses whatever code path normally calls `update_rating` on
  `GameOver`, not reuses it.
- **Acceptance criteria:** an integration test that kills the Match-Host
  process mid-match and asserts both connected clients receive
  `match_aborted`, and that no rating-update call occurred for either
  player (mockable/verifiable against I1's `UserRepository`).

### K2 — Redis staleness handling for Match-Host ownership records (`Server_Design.md` §5.5's flagged edge case)

- **Task:** a specific test for a Viewer (Stage F5/F6) joining via room
  code right as a Sentinel failover loses that room's Match-Host
  ownership record (I3) — confirm the failure mode is "room not found,
  try again" (a normal, understood error), not a hang or crash. Note this
  is a narrower risk under the pub/sub design (J2) than the original
  direct-relay design: a lost ownership record affects new joiners
  resolving *which* topic to use, not an already-established relay link
  (which doesn't exist as a distinct thing under pub/sub).
- **Acceptance criteria:** the above test, passing with a clear, expected
  error path.

### K3 — Disk-full mitigations (`Server_Design.md` §5.6)

- **Task:** confirm (by inspection/config review, not new application
  code) that Match-Host and Gateway pods write nothing to local disk —
  logs configured to ship to stdout/stderr only (standard for K8s
  centralized logging pickup), no local log files. Add PostgreSQL
  disk-usage alerting (data disk + WAL disk specifically, per
  `Server_Design.md` §5.6's revised table — infra/ops config, e.g. a
  Prometheus alert rule) per §5.6/§5.9 item 5.
- **Acceptance criteria:** a config review checklist item, not a code
  test — confirmed as part of Phase 6's monitoring setup (L1).

### K4 — Client-side handling of `match_aborted` (companion to K1)

- **File:** `kungfu_chess/client/loop/network_game_loop_runner.py` — a new
  handler for the `match_aborted` message, mirroring the existing
  `opponent_disconnected`/`GameOver` handling pattern already in this
  file, ending the local game view with an honest "match ended due to a
  server issue" state (not styled as either player's win/loss).
- **Acceptance criteria:** a client-side unit test asserting the correct
  UI-facing event fires on receiving `match_aborted`, distinct from the
  existing `GameOver` event's own rendering path.

---

## Phase 6 — Operations & capacity validation (`Server_Design.md` §5.8, §5.9)

### L1 — Monitoring & alerting

- PostgreSQL disk-usage alerts, data + WAL separately (K3 above).
- Custom metrics export for HPA: active-match-count per Match-Host pod,
  connection-count per Gateway pod (needed by J3's HPA manifests — build
  this alongside, not after).
- Redis Sentinel failover events surfaced as alerts, not silent.

### L2 — Fleet headroom decision (`Server_Design.md` §5.8, §5.9 item 7 — open decision)

- **Not a code task — a capacity-planning decision requiring your input,**
  flagged and not resolved in `Server_Design.md`: confirm a target
  redundancy margin (starting proposal: N+20%) for both Gateway and
  Match-Host node pools, sized against Part 3's ~150–250 Gbps figure.
  Once decided, encode it as the HPA manifests' minimum replica counts
  and/or cluster-autoscaler headroom configuration.

### L3 — Load testing against Part 3's real numbers

- **Task:** once Phase 4 is deployed, run a real load test (not a
  simulation) reproducing Part 3 §3.2's per-step traffic pattern at
  whatever scale the test environment allows, to validate the *measured*
  (not estimated) per-pod capacity numbers `Server_Design.md` §2.9/§3
  explicitly left as open/unbenchmarked. Feed real results back into
  `Server_Design.md` as a correction, the same way this plan's own G1
  finding corrected an earlier claim in Part 4.

---

## 7. Master dependency graph (quick reference)

```
G1, G2, G3, G4 ──────────────────────────┐  (no dependencies, start now)
                                          │
H1 ───────────────────────┐              │
H2 ─────────┬─────────────┼──────────────┤
            │             │              │
   F1 (no dep) │             │              │
   F2=H2 ──────┘             │              │
   F3 ─ F4 ─ F5 ─ F6 ─ F7 ───┘              │
            │             ▼              ▼
            │        I0 ─ I1 ─ I2 ─ I3 ─ I4   (Phase 3: backends)
            │             │  I5 ─ I6 ─ I7 ─ I8 ─ I9  (service split + multiprocessing)
            │             │
            └───────────────────┼──> J1 ─ J2 ─ J3 ─ J4 ─ J5  (Phase 4: nine-service topology)
                                              │
                                              ▼
                                  K1 ─ K2 ─ K3 ─ K4      (Phase 5: resilience)
                                              │
                                              ▼
                                       L1 ─ L2 ─ L3       (Phase 6: ops)
```

## 8. Consolidated open decisions (pulled from every part of `Server_Design.md`)

These are the items this plan cannot resolve unilaterally — flagged again
here, in one place, since several gate specific stages above:

1. **Room code length/alphabet** (Stage F1) — needed before F1 ships.
2. **Cloud provider** (`Server_Design.md` §1.7) — does not block Phases
   0–5 (self-hosted, provider-agnostic), but blocks any eventual move from
   self-hosted K3s to a managed Kubernetes offering.
3. **Fleet redundancy margin** (§5.8/§5.9, L2 above) — blocks finalizing
   HPA minimum-replica configuration in J3.
4. **Redis persistence on/off** (§5.6/§5.9) — a recommendation was made
   (off), needs confirmation before I2's Helm values are finalized.
