# KF-Chess Cloud Scale — Implementation Plan

**Relationship to `Server_Design.md`:** that document is the *decisions*
record — what was chosen and why, organized by requirement (Parts 1–5).
**This document is the *execution* plan** — organized by buildable stage,
in dependency order, so work can actually start. Every stage below cites
the `Server_Design.md` section it implements; go there for the reasoning,
come here for the task list. Stage letters continue this project's own
existing convention (Stages B1→E2 already exist in the codebase; Stage F,
Rooms, is already planned separately) — this plan uses **G onward**.

---

## 0. Phase overview

| Phase | Stages | What it delivers | Depends on |
|---|---|---|---|
| 0 | G1–G3 | Immediate, zero-dependency wins — no infra needed | Nothing — start today |
| 1 | H1–H2 | Foundational `Protocol` abstractions, in-memory only | Nothing — pure refactor |
| 2 | *(F1–F7)* | Rooms + Viewers feature (already planned separately) | H2 (`SessionCoordinator`) |
| 3 | I1–I3 | Real distributed backends stood up | H1, H2, K3s/Docker learning |
| 4 | J1–J4 | Gateway/Match-Host topology split, on K8s | I1–I3 |
| 5 | K1–K4 | Resilience hardening | J1–J4 |
| 6 | L1–L3 | Operations, monitoring, capacity validation | J1–J4, K1–K4 |

**Why this order:** Phase 0 and Phase 1 need nothing but this repo and a
Python environment — they can start in parallel, today, before any cloud
provider or K8s cluster exists. Phase 2 (Rooms) only needs Phase 1's
`SessionCoordinator` interface to exist, not its production backend, so it
can proceed in parallel with Phase 3. Phases 3–6 are strictly sequential —
each needs the previous phase's infrastructure actually running.

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
- **Acceptance criteria:** existing test suite passes unchanged (this is a
  pure runtime swap, no application-level behavior change); note in this
  plan once done that this becomes the default for both the Gateway and
  Match-Host entry points once Phase 4 splits them.

---

## Phase 1 — Foundational `Protocol` abstractions (in-memory only)

Pure refactors — no new infrastructure, no behavior change for any existing
caller. These unlock every later phase without needing a cloud provider,
Cassandra, or Redis to exist yet.

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

### H2 — `SessionCoordinator` `Protocol` + in-memory implementation (`Server_Design.md` §2.3, ties directly to the already-agreed Stage F2 design)

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

**Already planned in detail separately** (the F-stage brief and F1 design
document already produced) — listed here only to show where it sits in the
overall dependency graph: **F1 has no dependency on this plan at all**
(pure, headless — can start immediately, in parallel with Phase 0/1). **F2
onward depends on H2's `SessionCoordinator` `Protocol` existing** — F2's
own `RoomRegistry`/coordinator work should target the *same* `Protocol`
defined in H2, not a second, parallel one. Cross-reference: keep F2 and H2
as one coordinated implementation effort, not two.

---

## Phase 3 — Real distributed backends

**Prerequisite:** a K3s (or equivalent) cluster available to deploy to —
this is where the "learn Docker/K8s/K3s independently" requirement
directly gates further progress. Also prerequisite: cloud-provider choice
remains open (`Server_Design.md` §1.7) — everything in this phase is
provider-agnostic by design (self-hosted, open-source components), so it
does **not** block on that decision.

### I1 — Cassandra/ScyllaDB deployment + `UserRepository` production backend (`Server_Design.md` §1.3, §1.7, §5.4)

- **Infra:** deploy Cassandra or ScyllaDB via its official Helm chart onto
  the K3s cluster; configure **replication factor ≥3** across available
  failure domains (`Server_Design.md` §5.4).
- **Code:** new `server/persistence/cassandra_user_repository.py`
  implementing the `UserRepository` `Protocol` from H1 — `create_account`/
  `verify_login` at `QUORUM` consistency, `get_rating` at
  `ONE`/`LOCAL_ONE` (per the decided per-operation consistency,
  `Server_Design.md` §1.7 item 3). Same PBKDF2 hashing scheme, unchanged.
- **Acceptance criteria:** the *exact same* `UserRepository` `Protocol`
  test suite from H1 (parameterized/re-run against this new
  implementation, not a new test file) passes unchanged — proves the
  swap is truly transparent to callers, the entire point of H1's
  refactor. Add a chaos test: kill one Cassandra/Scylla node mid-test-run,
  confirm `QUORUM` operations still succeed with 3 replicas.

### I2 — Redis deployment + caching layer + `SessionCoordinator` production backend (`Server_Design.md` §1.6, §2.3, §2.6, §5.5)

- **Infra:** deploy Redis via Sentinel or Cluster mode (not a single
  instance) on K3s. Per §5.5/§5.9's recommendation, evaluate running
  **without** RDB/AOF persistence given this store's bounded-loss-tolerant
  data.
- **Code:**
  - `server/persistence/cached_user_repository.py` — a decorator
    implementing the same `UserRepository` `Protocol`, wrapping any other
    implementation with a Redis read-through cache in front of
    `get_rating` specifically (§1.6).
  - `server/application/redis_session_coordinator.py` implementing the
    `SessionCoordinator` `Protocol` from H2: matchmaking queue as a Redis
    sorted set, room registry as a Redis hash, presence map as simple
    key-value entries (`Server_Design.md` §2.3's table, implemented
    directly).
- **Acceptance criteria:** the *same* `SessionCoordinator` `Protocol` test
  suite from H2 passes against this Redis-backed implementation unchanged.
  Add a Sentinel-failover chaos test: trigger a failover mid-test, confirm
  behavior matches §5.5's documented bounded-loss expectation (a
  in-flight queue entry may be lost and must be retryable, not that the
  system stays fully available through the failover).

### I3 — `server_full` safety valve reinstated (`Server_Design.md` §5.7)

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

---

## Phase 4 — Gateway/Match-Host topology split (`Server_Design.md` Part 2, Part 4)

**Prerequisite:** Phase 3's backends deployed and reachable from the K3s
cluster.

### J1 — Split composition roots

- **Files:** new `server/main_gateway.py` and `server/main_match_host.py`,
  replacing (or branching from) the single existing `server/main.py`.
- **Task:** `main_gateway.py` wires `ConnectionManager` + `AUTH` handling +
  `SessionCoordinator` (I2's Redis-backed implementation) — no
  `GameSession`/tick loop. `main_match_host.py` wires `GameSession`
  creation/tick-loop hosting only, reachable *internally* (not
  client-facing) — no `ConnectionManager`, no AUTH.
- **Acceptance criteria:** each new entry point has its own smoke test
  confirming it starts and exposes only the responsibilities described
  above (e.g. a Match-Host instance refuses/has no code path for a raw
  client AUTH message).

### J2 — Internal Gateway↔Match-Host relay (`Server_Design.md` §2.4)

- **New module:** `server/application/relay.py` (or similar) — the
  Gateway-side component that, once `SessionCoordinator` resolves a
  match/room to a specific Match-Host address (via I2's presence map),
  opens its own internal connection to that Match-Host and pipes frames
  bidirectionally between it and the real client connection.
- **Acceptance criteria:** an integration test with one Gateway process
  and one Match-Host process (both local, real network sockets between
  them) confirming a full move round-trip (client → Gateway → Match-Host
  → Gateway → client) produces identical wire output to the current
  single-process design's own existing integration tests.

### J3 — Dockerfiles + Kubernetes manifests

- **New directory:** `deploy/` (or `infra/`) containing:
  - `deploy/docker/gateway.Dockerfile`, `deploy/docker/match-host.Dockerfile`
  - `deploy/k8s/gateway-deployment.yaml` (`Service` type as appropriate for
    external client access), `deploy/k8s/match-host-deployment.yaml`
    (`ClusterIP` `Service`, internal-only)
  - HPA manifests: Gateway scaling on connection count (custom metric),
    Match-Host scaling on active-match count (custom metric) — per
    `Server_Design.md` §2.5/§4.8 item 1.
- **Acceptance criteria:** both images build successfully; a local K3s
  deployment (`kubectl apply -f deploy/k8s/`) brings up both roles and a
  manual end-to-end game (two local clients) completes successfully
  through the full Gateway→Match-Host relay path.

### J4 — Graceful shutdown (`Server_Design.md` §4.4, §4.8 item 2)

- **File:** `server/main_match_host.py`, plus the corresponding K8s
  manifest's `preStop`/`terminationGracePeriodSeconds` fields.
- **Task:** implement the cordon-then-drain sequence: on `SIGTERM`, stop
  advertising this pod as available in the presence map (I2), wait (up to
  the configured grace period, ≥90s + margin) for the pod's own active
  `GameSession` count to reach zero, then exit.
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
  detect the internal Match-Host connection breaking, send
  `match_aborted` to both real clients via the Gateway).
- **Task:** confirm no `update_rating` call fires for a match ended this
  way (Part 5's correctness requirement) — likely means the abort path
  bypasses whatever code path normally calls `update_rating` on
  `GameOver`, not reuses it.
- **Acceptance criteria:** an integration test that kills the Match-Host
  process mid-match and asserts both connected clients receive
  `match_aborted`, and that no rating-update call occurred for either
  player (mockable/verifiable against I1's `UserRepository`).

### K2 — Redis presence-map staleness handling (`Server_Design.md` §5.5's flagged edge case)

- **Task:** a specific test for a Viewer (Stage F5/F6) joining via room
  code right as a Sentinel failover loses that room's presence-map entry
  — confirm the failure mode is "room not found, try again" (a normal,
  understood error), not a hang or crash.
- **Acceptance criteria:** the above test, passing with a clear, expected
  error path.

### K3 — Disk-full mitigations (`Server_Design.md` §5.6)

- **Task:** confirm (by inspection/config review, not new application
  code) that Match-Host and Gateway pods write nothing to local disk —
  logs configured to ship to stdout/stderr only (standard for K8s
  centralized logging pickup), no local log files. Add Cassandra/Scylla
  disk-usage alerting (infra/ops config, e.g. a Prometheus alert rule)
  per §5.6/§5.9 item 5.
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

- Cassandra/Scylla disk-usage alerts (K3 above).
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
G1, G2, G3 ──────────────────────────────┐  (no dependencies, start now)
                                          │
H1 ───────────────────────┐              │
H2 ─────────┬─────────────┼──────────────┤
            │             │              │
   (F1..F7) │             │              │
            │             ▼              ▼
            │            I1 ── I2 ── I3   (Phase 3: real backends)
            │                   │
            └───────────────────┼──> J1 ─ J2 ─ J3 ─ J4  (Phase 4: topology)
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
