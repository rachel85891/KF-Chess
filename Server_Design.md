# KF-Chess — Scalable Server Architecture

**Scope:** Evolve the current single-process `GameServer` (asyncio +
`websockets`, in-process `SessionCoordinator`/`MatchmakingQueue`/`Room`/
`GameSession`, SQLite via `UserRepository`) into a horizontally scalable
cloud architecture supporting **100M registered users** and **10M
concurrent players**.

This document describes the target architecture: nine independently
scaled services communicating over an event bus and a shared
low-latency store, backed by PostgreSQL for durable data. Every section
below states both the target design and this project's current
implementation status, so it's clear what already exists and what's
still to be built. The concrete build order lives in
`Implementation_Plan.md` (§20).

---

## 1. System Architecture Diagram

```
                                   ┌─────────────────────────┐
                                   │        Clients            │
                                   └────┬────────────────┬─────┘
                                        │ REST/HTTP       │ WebSocket
                              (login, rooms, history)  (live moves, state)
                                        │                │
                          ┌─────────────▼───┐   ┌────────▼──────────┐
                          │   API Gateway     │   │  WebSocket Gateway │
                          │   (REST/HTTP)     │   │  (async I/O, no    │
                          │                   │   │  thread-per-client)│
                          └───┬───────────┬───┘   └─────────┬──────────┘
                              │           │                  │
                     ┌────────▼──┐  ┌─────▼─────┐            │
                     │   Auth    │  │ Rooms API │            │
                     │  Service  │  │(CRUD/hist)│            │
                     └────┬──────┘  └─────┬─────┘            │
                          │               │                  │
                          └───────┬───────┴──────────┬───────┘
                                  │                  │
                     ┌────────────▼──────────────────▼───────────┐
                     │           NATS Event Bus (control-plane)          │
                     │  (internal messages only: "matched",         │
                     │   "allocate room", "room ready")             │
                     └───┬─────────────┬─────────────┬────────────┘
                         │             │             │
                ┌────────▼───┐  ┌──────▼──────┐  ┌────▼──────────────┐
                │ Matchmaker │─►│Game Allocator│─►│  writes mapping    │
                │(ELO queue) │  │(picks shard) │  │  into Redis         │
                └────────────┘  └──────┬───────┘  └────────────────────┘
                                        │
                     ┌──────────────────▼───────────────────────┐
                     │        Redis Cluster (single store)         │
                     │  • room_id → {shard_ip:port, worker_pid}     │
                     │    (this IS the registry — not a service)   │
                     │  • sessions, presence, matchmaking queue,    │
                     │    reconnect state, room command queues      │
                     └───┬──────────────────────────────┬──────────┘
                         │                              │
             ┌───────────▼────────┐          ┌──────────▼─────────┐
             │ Game Server Shard A │   ...    │ Game Server Shard N │
             │ (Docker, K8s Deploy │          │                      │
             │  or Agones-managed) │          │                      │
             │ N worker processes  │          │  N worker processes  │
             │ (multiprocessing),  │          │                      │
             │ authoritative        │          │                      │
             │ GameEngine per room  │          │                      │
             └───────────┬─────────┘          └──────────┬───────────┘
                         │                                │
         ┌───────────────┴────────────────┬───────────────┴─────────┐
         │                                │                          │
┌────────▼─────────┐           ┌──────────▼─────────┐     ┌──────────▼─────────┐
│   PostgreSQL       │           │  (same Redis        │     │    Observability     │
│ users, games,       │           │   cluster above,     │     │ logs, metrics,       │
│ results, move       │           │   used for hot state)│     │ alerts, traces,      │
│ history             │           │                      │     │ load tests           │
└────────────────────┘           └──────────────────────┘     └──────────────────────┘

  One Region = one Kubernetes / K3s cluster. Everything above is containerized
  and runs on it. For very large scale, this whole region is replicated across
  multiple regions with geographic client routing in front of the API/WS
  Gateways (see §19, "Geography-aware matchmaking/allocation," still open).

  GATEWAY ROLE, EXPLICITLY: neither Gateway ever decides game rules — the
  client doesn't, and the Gateway doesn't either. The GameEngine inside each
  Game Server Shard (this project's existing `game_session.py`) remains the
  single source of truth, exactly as `docs/spec.md` already establishes for
  the single-process case. Both Gateways are stateless connection edges.
```

---

## 2. Services and Responsibilities

| Service | Responsibility | This project's current codebase equivalent |
|---|---|---|
| **API Gateway** | Non-real-time HTTP/REST: login, room CRUD, match history queries. Stateless, scales on request rate. | **Does not exist as a separate service today** — `server/application/game_server.py` handles AUTH and room choice over the same WebSocket as live gameplay |
| **WebSocket Gateway** | Terminates the client's live WebSocket, checks the session, relays moves/state in both directions. Holds no room/game state. | `server/application/game_server.py` + `server/presentation/protocol_handler.py` (the live-connection half) |
| **Auth Service** | Validates credentials, issues sessions, reads/writes user identity + rating. | `server/persistence/user_repository.py` — **still a concrete `UserRepository` class today, not yet a `Protocol`** (see §12) |
| **Rooms API** | Non-real-time room CRUD/history — distinct from live allocation. | **Not split out** — today, `create_room`/`join_room` (below) do both room bookkeeping *and* what §5 calls allocation, in one call |
| **Matchmaker** | ELO-based search queue, pairs players. | `server/application/matchmaking_queue.py` (Stage E1, already implemented and unit-tested in isolation) |
| **Game Allocator** | Decides which Game Server Shard a new room runs on. | **Does not exist as a distinct concept today** — see §5, the single biggest gap between this project's current single-process code and this architecture |
| **Game Server Shards** | Run the authoritative `GameEngine`/`GameSession` per active room. | `server/application/game_session.py` |
| **Rating Service** | Computes ELO updates at game end, persists them. | `server/application/elo_rating.py`, called today directly from `game_server.py`/`UserRepository.update_rating` — **not yet its own service** |
| **Redis** | Hot, short-lived state: room→shard mapping, sessions, presence, matchmaking queue, room command queues. | **Does not exist today** — `SessionCoordinator`'s only implementation so far is `InMemorySessionCoordinator` (Stage F2, in-process) |
| **PostgreSQL** | Durable storage: users, games, results, move history. | **Does not exist today** — persistence is SQLite via `UserRepository`, and move/game history is not persisted at all yet |
| **NATS + Redis** | Internal control-plane messaging (Gateway↔Matchmaker↔Allocator↔Shards) via NATS; Redis stays dedicated to hot-state lookups (§7). | **Does not exist today** — decided: both, together, not either/or |
| **Observability** | Logs, metrics, health checks, alerting, traces, load testing. | **Does not exist today** |

**Rooms/Viewers — the one area meaningfully *ahead* of this architecture
today:** `server/application/room.py` (Stage F1, pure/headless
`RoomCode`+`Room`), `server/application/session_coordinator.py` (Stage F2,
the `SessionCoordinator` `Protocol` unifying `MatchmakingQueue` and `Room`),
`server/presentation/room_choice_command.py` (Stage F3, PLAY/CREATE_ROOM/
JOIN_ROOM wire grammar), and `game_server.py`'s own room-choice handling
(Stages F4–F6: wiring, Viewer role rejection, broadcast-correctness audit
for a variable number of viewers) are **already fully implemented and
tested**, ahead of the rest of this architecture. See §6 for what this
means for "Joining Any Room" specifically.

**Why split Rooms API from Game Allocator:**
CRUD/history is request/response, low-frequency, cacheable; allocation is
latency-sensitive, triggered by an event, done once per match. Splitting
them lets each scale independently — a spike in players browsing history
can't affect a burst of new matches needing shards. **Current gap:** this
project's `SessionCoordinator.create_room`/`join_room` do not yet make any
shard-assignment decision at all (single process, nothing to assign to) —
this split becomes a real, necessary refactor once §5 is actually built.

---

## 3. Client Connection Flow

1. **Non-real-time calls** (login, room browsing, history) go over
   REST/HTTP to the **API Gateway** — not built yet; today AUTH shares the
   same WebSocket as gameplay.
2. **Live gameplay** opens a WebSocket to the **WebSocket Gateway** (via a
   public load balancer, not directly to any shard) — this part already
   matches today's `game_server.py` connection-acceptance flow closely.
3. WebSocket Gateway checks the session with Auth Service, then relays:
   client messages forward to whichever backend currently owns the
   player's state (Matchmaker while searching, the assigned shard while
   playing); server-originated messages relay back down the same socket.
4. Neither Gateway ever holds game logic or game state.

| | API Gateway | WebSocket Gateway |
|---|---|---|
| Does | Login, room CRUD, history queries | Terminate WebSocket, relay moves/state |
| Does | Forward to Auth / Rooms API | Look up `room_id → shard` in Redis |
| Does NOT | Hold a live connection | Validate a move against chess rules |
| Does NOT | Decide matchmaking or allocation | Store `GameSession` or room state |

Because neither Gateway carries state, a client can reconnect through a
*different* WebSocket Gateway pod mid-game and resume seamlessly — the new
pod re-resolves the same `room_id` in Redis and reconnects to the same
worker. This is the same mechanism the server side already implements via
Stage E2's disconnect-countdown/resume path — the one missing piece is
client-side auto-reconnect (`Implementation_Plan.md` Stage G1), since
Gateway statelessness is what makes seamless resume possible once the
client actually retries the connection.

---

## 4. Inter-Service Communication

| From → To | Transport | Purpose |
|---|---|---|
| Client → API Gateway | REST/HTTP | Login, room CRUD, history |
| Client → WebSocket Gateway | WebSocket | Live moves, state updates |
| API Gateway → Auth Service | Sync RPC | Login/session validation |
| API Gateway → Rooms API | Sync RPC | Room CRUD, history queries |
| WebSocket Gateway → Auth Service | Sync RPC | Validate session on connect |
| WebSocket Gateway → Matchmaker | Pub/Sub request/event | Submit play request, receive match-found event |
| Matchmaker → Game Allocator | Pub/Sub event | "players X,Y matched" → allocate room |
| Game Allocator → Redis | Redis `SET` | Register `room_id → shard` |
| WebSocket Gateway → Redis | Redis `GET` | Resolve `room_id → shard` on every join/reconnect |
| WebSocket Gateway → Game Server Shard | Direct routed connection (address resolved via Redis) | Forward gameplay moves, receive state updates |
| Game Server Shard → Rating Service | Sync RPC / Pub/Sub event | Report match result for ELO update |
| Game Server Shard → Redis | Room command queues, presence | Buffer/relay per-room commands, track active rooms |
| All services → Observability | Metrics/log/trace export | Health checks, dashboards, alerting |

Pub/Sub carries **control-plane** messages only (low volume, short-lived:
"matched," "allocate room"). Live gameplay traffic flows on the direct
WebSocket Gateway ↔ Game Server Shard path, resolved via Redis — kept
outside the coordination channel so the highest-frequency traffic in the
system never adds a Pub/Sub hop.

---

## 5. Assigning Players to Game Servers — the real gap in this project today

- Game Server Shards **do not self-select**; the **Game Allocator** owns
  the assignment decision. **This does not exist in this project's code
  yet** — `SessionCoordinator.create_room`/`join_room`/`find_match` today
  only decide *who's playing whom*, never *which process runs it*, because
  there's only ever been one process to run it on.
- Each shard periodically reports load (active rooms, CPU) into Redis as a
  lightweight heartbeat key per worker.
- On a "matched" event, the Game Allocator reads those heartbeat keys and
  picks the least-loaded shard (consistent hashing is an alternative if
  session affinity across reconnects is preferred over pure load-balance).
- The chosen shard/worker address is written to Redis, keyed by `room_id`.
- Both players' WebSocket Gateways are told which shard to route to.

**What building this actually requires of this project's existing code:**
extending `SessionCoordinator`'s `Protocol` (today: `find_match`/
`create_room`/`join_room`) with a shard-assignment step — either as a
fourth method or as a natural consequence of a future Redis-backed
implementation of the same three methods. The `Protocol` boundary this
project already built (Stage F2's own explicit reasoning: "a future
distributed implementation... none of this changes the Protocol's own
method signatures") is exactly what makes this addable without touching
`game_server.py`'s calling code.

---

## 6. Joining Any Room

- Rooms are **global**, not tied to any single Gateway pod. `room_id` (this
  project's `RoomCode`, Stage F1) is a cluster-wide identifier.
- A `JOIN_ROOM:<code>` (this project's actual wire message, Stage F3 —
  `room_choice_command.py`) resolves via a single Redis `GET` in the target
  architecture — there's no separate registry service; Redis *is* the
  registry.
- The WebSocket Gateway opens (or reuses) an internal connection to that
  shard and relays the join request.
- **Where this project is already ahead:** the *logic* of "who's in a room,
  what role do they get (White/Black/Viewer)" is already fully built and
  tested (`Room.add_occupant`, Stage F1; `SessionCoordinator.join_room`,
  Stage F2) — entirely independent of *where* that room physically runs.
  Going from single-process to distributed changes only how the *shard* is
  found, not this project's existing room/role logic at all.

---

## 7. Room ID → Game Server Mapping

- Storage: a single Redis hash/key-value entry,
  `room:{room_id} -> {shard_ip, port, worker_pid}` — the registry,
  deliberately not its own microservice (would add a network hop in front
  of a lookup Redis already serves in sub-millisecond time).
- Written once at room creation by the Game Allocator; deleted by the shard
  on game termination.
- **TTL as a safety net** (e.g. 2 hours) to auto-evict orphaned entries if
  a shard crashes without explicit cleanup.
- Redis over PostgreSQL for this mapping: sub-ms lookups on every
  join/reconnect at 10M-concurrent scale; PostgreSQL is reserved for
  durable, less latency-sensitive data.

---

## 8. Docker Container Organization

| Container image | Contains | Scaling unit |
|---|---|---|
| `api-gateway` | REST/HTTP handling, thin routing | Deployment, N replicas, stateless |
| `ws-gateway` | WebSocket terminator, async I/O relay | Deployment, N replicas, stateless |
| `auth-service` | `user_repository.py` (once split out), PostgreSQL client | Deployment, N replicas, stateless |
| `rooms-api` | Room CRUD/history (new split, §2) | Deployment, N replicas, stateless |
| `matchmaker` | `matchmaking_queue.py` logic against a Redis queue, Pub/Sub producer | Deployment, N replicas, stateless |
| `game-allocator` | Shard-selection logic (new, §5), Redis writer, Pub/Sub consumer | Deployment, N replicas, stateless |
| `game-server-shard` | `game_session.py`, authoritative `GameEngine` | Deployment (or Agones-managed); **one process per CPU core internally** (§10) |
| `rating-service` | `elo_rating.py` (once split out) | Deployment, N replicas, stateless |
| `redis` | Room registry, presence, matchmaking/command queues | Managed cluster |
| `postgres` | Users, games, results, move history | Managed cluster with read replicas |
| `nats` | Internal control-plane event bus | Clustered NATS deployment |
| `observability` | Metrics, logs, traces, alerting, load-test tooling | Deployed alongside, scraping every pod |

Every service ships as its own image with its own `Dockerfile` — no shared
"mega-container." This lets each layer scale, deploy, and roll back
independently.

---

## 9. Local Development: Docker Compose

Before any Kubernetes/K3s work, a minimal `docker-compose.yml` proves the
service split works end-to-end on one machine:

```
services:
  api-gateway, ws-gateway        (1 replica each)
  auth-service, rooms-api        (1 replica each)
  matchmaker, game-allocator     (1 replica each)
  game-server-shard              (1 replica, multiple worker processes)
  redis                          (single instance)
  postgres                       (single instance)
  nats                           (single instance)
```

No HPA, no multi-region, no managed-cloud Redis/Postgres — just enough
wiring to validate that a client can log in, get matched, get allocated to
a shard, play a full game, and see the result persisted. This is
`Implementation_Plan.md`'s Stage I0 — the "something small that works"
milestone, before any K3s/Kubernetes work begins.

---

## 10. Where Multiprocessing Is Used, and Why

```
                       Game Server Shard  (container, e.g. 4 vCPUs)
        ┌───────────────────────────────────────────────────────────┐
        │                     Supervisor (main process)              │
        │        heartbeats load to Redis, spawns/monitors workers   │
        └───────┬───────────────┬───────────────┬───────────────┬────┘
                │               │               │               │
        ┌───────▼──────┐┌───────▼──────┐┌───────▼──────┐┌───────▼──────┐
        │  Worker proc 0 ││  Worker proc 1 ││  Worker proc 2 ││  Worker proc 3 │
        │  (own asyncio  ││  (own asyncio  ││  (own asyncio  ││  (own asyncio  │
        │   event loop)  ││   event loop)  ││   event loop)  ││   event loop)  │
        │  Rooms: R101,  ││  Rooms: R102,  ││  Rooms: R103,  ││  Rooms: R105,  │
        │  R104, R108... ││  R107, R111... ││  R109, R112... ││  R110, R113... │
        └───────────────┘└───────────────┘└───────────────┘└───────────────┘
                │               │               │               │
                └───────────────┴───────┬───────┴───────────────┘
                          Redis: room:{id} → worker_pid (port)
```

**Why this matters:** a single asyncio process shares one CPU core — even
on a multi-core VM, one process is still limited to one core by Python's
GIL. Adding more Match-Host *pods* alone doesn't fix this within a single
pod. **Fix:** each Game Server Shard container runs one OS process per CPU
core, each with its own event loop, each owning a disjoint set of rooms
for their entire (30–90s) lifetime — multiplying room capacity per
container by core count, not just by pod count. Redis's mapping stores
`worker_pid`/port, not just the shard's address, so the WebSocket Gateway
routes to the exact process.

---

## 11. Where Kubernetes (and Agones) Fit

- Every service in §8 is a Kubernetes `Deployment` with its own HPA,
  scaling on CPU/connection-count metrics (connection-count for Gateways,
  active-match-count for shards — `Implementation_Plan.md` Phase 4).
- The public LB is a `Service` (`LoadBalancer` type) in front of the
  API/WebSocket Gateway pods.
- Game Server Shards scale on active-room count, not raw CPU alone, since
  games are short-lived and bursty.
- **Agones (optional fleet manager):** a natural upgrade over a generic
  `Deployment` specifically for Game Server Shards — allocates a *ready*
  shard rather than any pod, and supports graceful shutdown that waits for
  an in-progress game rather than killing it mid-match, the same
  cordon-then-drain idea this project's own `preStop`-based design
  already implements by hand — Agones is a real, off-the-shelf
  implementation of that exact pattern, worth adopting rather than
  maintaining the hand-built version once it exists.
- K3s: development/staging/edge; full Kubernetes (EKS/GKE/AKS): production
  multi-region — following the same Docker Compose → K3s → managed-K8s
  phasing as the rest of this plan.
- **Multi-region:** one region = one cluster (§1); at large scale this
  stack repeats per region with geo-aware routing — geography-aware
  matchmaking/allocation (how two far-apart players actually get matched,
  and which region's shard hosts them) is flagged as an open, undecided
  item — see §19. This section gives it a structural home (per-region
  cluster replication) without yet resolving that question itself.

---

## 12. Replacing SQLite

**SQLite is not viable** at this scale — single-file, single-writer, no
network access from multiple hosts, no horizontal scaling; it cannot be
shared safely across dozens of Auth/Rating Service pods.

**PostgreSQL**, deployed as a managed cluster, with:
- A **primary** for writes (new users, rating updates, match history).
- **Read replicas** for read-heavy queries (profile lookups, leaderboard
  queries).
- **Sharding by user-ID range** (or Citus) once 100M users exceed a single
  primary's comfortable capacity.

PostgreSQL over a NoSQL store because accounts/ratings/match history are
strongly relational and need transactional integrity (e.g., atomic ELO
updates for two players in one game) — a genuinely relational requirement
once "games, results, move history" is named as durable data this store
must hold, not just the four original `UserRepository` methods in
isolation.

**Current gap:** `server/persistence/user_repository.py`'s `UserRepository`
is still a concrete class, not yet a `Protocol` — the refactor
`Implementation_Plan.md` names as Stage H1 is a prerequisite for plugging
in `PostgresUserRepository` at all, and hasn't been done yet (Stage F,
Rooms, was prioritized first instead).

---

## 13. Database Usage by Service

| Service | Reads | Writes |
|---|---|---|
| Auth Service | User credentials, profile on login | New user registration |
| Rating Service | Current ELO before a match | Updated ELO after a match ends |
| Matchmaker | Player rating (to bucket search) | — |
| Rooms API / Game Server Shard | Room/match history | Match history record on game end |
| (Everything hot-path) | Room→shard mapping, presence, matchmaking queue | *(via Redis, not PostgreSQL)* |

Redis is the **hot path** store; PostgreSQL is the **durable path** store —
kept deliberately separate: ephemeral, sub-millisecond coordination state
in one, durable relational data in the other.

**A read-through cache belongs in front of `get_rating` specifically:**
this is the single hottest read against PostgreSQL — called on essentially
every matchmaking attempt across the fleet. A Redis cache keyed by
username, populated on read and invalidated/updated by the Rating Service
on write, keeps steady-state read load against the actual database far
lower than 10M concurrent players would otherwise imply — the durable
store still holds the authoritative value, this only reduces how often
it's asked.

**Current gap, worth naming explicitly:** this project does not persist
match/move history *at all* today — `GameSession` state is entirely
in-memory and discarded at game end, aside from the final ELO update. Any
"Rooms API" reading match history needs this written somewhere first; not
yet built.

---

## 14. Network Traffic Calculation

**Method:** rather than assuming a generic per-move message size, real byte
sizes were measured directly from this project's actual wire-format code
(`kungfu_chess/notation/*_wire_format.py`), against a real starting board
and real event payloads.

**What the current (pre-optimization) wire protocol actually sends:**
every accepted move triggers **two** events (`MoveAccepted` +
`PieceArrived`), and **three** messages per event (EVT + the full board +
the full, ever-growing move log) — measured at 21–1,202 bytes per
message, growing over a match's length. At 10M concurrent players
stepping every 2 seconds, this comes to a **~150–250 Gbps** fleet-wide
aggregate.

**This surfaced a real inefficiency worth fixing, not just noting:**
resending the *entire* board and *entire* move log on every single event,
when only a couple of squares and one new log entry actually changed.

**Decision: fix it now.** A lean wire protocol is adopted — sequence
numbers per match, `BOARD_DELTA` (only the squares that changed, usually
2) and `LOG_DELTA` (only the newest log entry, not the accumulated
history), with the existing full-board/full-log messages kept as a
`RESYNC_REQUEST`-triggered recovery path rather than sent on every event
(Stage G4 in `Implementation_Plan.md`).

| | Before (measured, current codebase) | After G4 (design estimate, not yet measured) |
|---|---|---|
| Per-event payload | ~782 bytes representative (21 EVT + 159 full board + up to 1,202 growing log) | ~70 bytes (small EVT + ~2-square delta + single log entry) |
| Fleet-wide aggregate | **~150–250 Gbps** (measured from real wire-format code) | **~11 Gbps** (design estimate) |

The ~11 Gbps figure is a *design* estimate, not a measurement, since G4's
code doesn't exist yet — Phase 6's L3 load test is what validates it
against reality once built.

**Either way, distributed across hundreds of WS Gateway/Game Server Shard
pods**, the per-pod bandwidth lands easily inside normal cloud networking
limits — the real number only matters for *how many* pods and *how much
total egress capacity* to provision, not whether the horizontal-scaling
architecture itself works.

**Two further, lower-risk wins worth adopting alongside G4:**
- **WebSocket `permessage-deflate` compression** — a transport-only
  configuration flag on the WebSocket Gateway, zero wire-protocol change.
  Board and log payloads compress well (measured: full-board text
  compresses roughly 2.5×, a 60-entry move log over 6×) since both are
  repetitive ASCII text — a near-free reduction on top of G4's delta
  protocol, not a substitute for it.
- **`uvloop`** as the event-loop implementation for Game Server Shard
  worker processes — a one-line, drop-in replacement for the default
  asyncio event loop, well-established for I/O-bound workloads exactly
  like this one, improving per-worker throughput independent of anything
  else in this section.

---

## 15. Supporting the Scale Requirements

| Requirement | How the architecture supports it |
|---|---|
| **100M registered users** | PostgreSQL cluster with replicas/sharding stores accounts durably; Auth Service is stateless and scales independently of active-player count |
| **10M concurrent players** | Load spread across many stateless API/WebSocket Gateway pods and many multiprocess Game Server Shards; Redis handles high-frequency lookup/presence traffic a relational DB couldn't sustain |
| **Network traffic (§14)** | Horizontal fan-out across hundreds of small pods keeps per-pod bandwidth trivial regardless of which traffic estimate is used |
| **30–90s match duration** | Short-lived work units are exactly what makes aggressive shard bin-packing/spot-instance use viable — losing a shard mid-match risks, at most, a match that was already close to ending |
| **Horizontal scaling** | Every service is a separate, independently-scaled Deployment; none holds cluster-wide state in-process — shared state lives in Redis/PostgreSQL |
| **Fault tolerance** | Stateless services restart freely; shard loss only affects its own rooms; Redis TTL cleans up stale mappings; Matchmaker/Allocator retry logic re-queues affected players; Redis/PostgreSQL/Pub-Sub run as managed/replicated clusters, not single instances |

---

## 16. Game Lifecycle

1. **Matchmaking** — Player sends a play request → WebSocket Gateway →
   Matchmaker enqueues by ELO bucket (this project's existing
   `MatchmakingQueue`, Stage E1) → pairs two players → emits a "matched"
   event.
2. **Room Creation** — Game Allocator (§5, not yet built) consumes the
   "matched" event, generates a `room_id` (this project's existing
   `RoomCode`, Stage F1), selects the least-loaded shard, writes
   `room_id → shard` into Redis.
3. **Game Execution** — The shard's worker instantiates the authoritative
   `GameSession` (this project's existing `game_session.py`); both
   players' Gateways route moves directly to that worker; state broadcasts
   flow back the same path; expected duration 30–90s.
4. **Game Termination** — `GameSession` ends on checkmate/timeout/
   resignation; the shard reports the result to Rating Service (this
   project's existing `elo_rating.py`) and writes match history to
   PostgreSQL (not yet built — see §13).
5. **Resource Cleanup** — The shard deletes the room's in-memory state and
   removes the `room_id` entry from Redis; the worker becomes available
   for a new room immediately.

**Where this project's actual code already implements this lifecycle
differently (Rooms path):** Steps 1–2 above describe the **auto-matchmaking**
path. This project's already-built **Rooms** path (Stage F1–F6) is a
second, parallel lifecycle: a player creates a room, receives a `RoomCode`
immediately (no matchmaking wait), a second player joins by code, and
any further joiners become **Viewers** (`Role.VIEWER`) rather than being
rejected — a real, tested capability this architecture diagram doesn't
show a box for yet. Both lifecycles already converge on the same
`SessionCoordinator` `Protocol` in this project's actual code (Stage F2's
own explicit design goal) — the diagram in §1 should be read as covering
both paths through the same Matchmaker-or-Rooms → Allocator → Shard route.

---

## 17. Failure Flow

Different components fail differently because only some hold state.

```
   Client              WS Gateway            Matchmaker /              Game Server
                          Pods                Game Allocator              Shard
     │                     │                        │                        │
     │   WS Gateway dies    │                        │                        │
     │───────X              │                        │                        │
     │   LB detects failed   readiness probe,          │                        │
     │   health check, reconnects client to a          │                        │
     │   different WS Gateway pod ─────────────────────►│                        │
     │   New pod re-resolves room_id in Redis,          │                        │
     │   reconnects to the SAME worker ─────────────────────────────────────────►│
     │                     │                        │                        │
     │                     │   Shard dies             │                        X
     │                     │   (worker + its rooms)   │                        │
     │                     │◄── Redis TTL / missed     │                        │
     │                     │    heartbeat marks shard  │                        │
     │                     │    stale                  │                        │
     │◄── Game Allocator / │                        │                        │
     │    shard detects     │                        │                        │
     │    the orphaned      │                        │                        │
     │    room, sends       │                        │                        │
     │    clients a "game   │                        │                        │
     │    aborted" event     │                        │                        │
     │                     │                        │                        │
     │                     │   Redis node dies        │                        │
     │                     │   (replica promoted)      │                        │
     │                     │   brief lookup failures    │                        │
     │                     │                        │                        │
     │                     │   PostgreSQL primary dies │                        │
     │                     │   (managed failover)       │                        │
     │                     │   Gameplay unaffected       │                        │
     │                     │   (hot path is Redis)       │                        │
```

| Failure | Detection | Blast radius | Recovery |
|---|---|---|---|
| **WebSocket Gateway pod crashes** | K8s liveness/readiness probe fails | Only clients currently connected to that pod | LB reconnects them; new pod re-resolves `room_id` in Redis, reattaches to the same shard worker — no game state lost, since the Gateway never held any. The server-side mechanism (Stage E2) is already built and correct; the one remaining concrete gap is client-side — `network_game_client.py` does not yet attempt reconnect automatically (`Implementation_Plan.md` Stage G1) |
| **Game Server Shard/worker crashes** | Missed Redis heartbeat / pod restart | Only the rooms owned by that shard/worker | Affected clients get a "game aborted" message via their still-connected Gateway, routed back to Matchmaker/Allocator for a fresh room; stale `room_id` entries expire via TTL. Genuinely different from a Gateway crash: the `GameSession` itself — unreplicated — is lost here, not just a connection |
| **Auth/Matchmaker/Allocator pod crashes** | K8s restarts it; stateless | Only in-flight requests to that pod | Routed to a different replica; no persistent state to reconcile |
| **Redis node/shard fails** | Cluster/Sentinel detects, promotes a replica | Brief latency spike or failed lookups during failover | Short retry/reconnect — acceptable, bounded loss, precisely *because* of what Redis holds here (ephemeral coordination state, not durable records) |
| **PostgreSQL primary fails** | Managed failover (seconds-scale) | ELO/history writes queue or briefly fail; live gameplay unaffected | Standby promoted; queued writes flush |

**Design takeaway:** the only genuinely cluster-wide single point of
failure is Redis, mitigated by running it as a replicated cluster — every
other component's failure is isolated to the slice of players it was
serving.

### Preserving an in-progress game across a shard crash

The design above deliberately does **not** attempt session replication for
a crashed shard — it treats the crash as a match-abort instead, since
real-time state replication on every tick isn't proportionate for a
30–90s session. This is a two-phase plan, not a single decision:
**Phase 1 (current):** abort and return to matchmaking, no replication.
**Phase 2 (a named, deferred upgrade, not decided now):** periodic
checkpointing to Redis (snapshot the board/timers after every move or few
moves; on crash, a new
worker loads the last snapshot and resumes) — recovering all but the
single move right before the crash, at low added latency. A stronger
event-sourcing alternative (every move logged via Pub/Sub, replayed for
zero-loss recovery) remains a further, even-later option if a "zero lost
moves" guarantee ever becomes a hard requirement.

### Disk-full scenarios

A distinct failure mode from an outright crash — worth naming explicitly,
component by component:

| Component | Disk risk | Mitigation |
|---|---|---|
| PostgreSQL primary/replicas | Real — durable table/WAL (write-ahead log) storage grows with registered-user count; WAL specifically can grow quickly if a replica falls behind | Monitoring + alerting on both data-disk and WAL-disk usage; horizontal scale-out (Citus) is the escape valve if vertical scaling (bigger disks) stops being enough |
| Redis | Low, if run without RDB/AOF persistence — legitimate here given §17's own established bounded-loss tolerance for this store's data | Evaluate persistence-off as the default |
| API/WS Gateway, Matchmaker, Allocator, Game Server Shard pods | **Should be zero, by explicit design rule** — these must never write anything correctness-critical to local disk (ephemeral pod storage is wiped on restart anyway) | Logs shipped to centralized/streamed logging, never local files — this is a design rule stated explicitly, not an incidental fact |

### Overload handling — demand exceeding capacity, not a crash

A real, distinct failure mode: demand arriving faster than autoscaling can
react. Two speeds of protection, not one:
1. **Fast, local safety valve:** each WebSocket Gateway pod enforces a
   configurable connection cap; once at capacity, new connections receive
   a `server_full` response and are closed immediately — no waiting on
   autoscaling.
2. **Slower, cluster-level response:** HPA-based autoscaling (§11) reacts
   over tens of seconds to minutes — (1) is the first line of defense
   during the gap before new capacity actually comes online.

---

## 18. Observability

| Concern | What's collected | Where |
|---|---|---|
| **Logs** | Structured logs from every service (request IDs, room IDs, error traces) | Centralized log aggregation |
| **Metrics** | Per-service request rate/latency/error rate; Redis/Pub-Sub/PostgreSQL throughput; active-room/worker counts per shard | Prometheus-style scraping + dashboards |
| **Health checks** | Liveness/readiness probes per pod | Kubernetes probes |
| **Alerts** | Shard heartbeat gaps, Redis failover events, elevated reconnect rate | Routed to on-call notification |
| **Traces** | Cross-service request traces for slow-path debugging | Distributed tracing |
| **Load tests** | Scripted simulations validating §14's traffic estimates before relying on them in production | Run against staging, gating capacity claims |

Observability isn't optional tooling bolted on later — at 10M-concurrent
scale, it's the only way to know a shard is silently overloaded, a Redis
failover is degrading reconnects, or a region is trending toward
saturation before players notice.

---

## 19. Open Decisions Requiring Input

These items are flagged deliberately rather than decided unilaterally —
each is either a genuine cost/risk trade-off or a question this document
doesn't yet have enough information to close:

- **Geography-aware matchmaking/allocation.** §11 flags multi-region
  replication structurally, without resolving *how* cross-region
  matchmaking or shard selection actually works when two players are far
  apart. Still open.
- **Fleet redundancy margin (headroom percentage).** A cost/risk business
  decision, not a purely technical one — a starting figure of N+20% has
  been proposed elsewhere in this project's planning but not confirmed.
- **Exact PostgreSQL write-throughput ceiling.** A real concern once
  traffic approaches the ~166K writes/sec peak estimate (§13); Citus is
  the named escape valve, not yet needed or built.
- **Cloud provider.** Everything in this document is deliberately
  provider-agnostic (self-hosted, open-source components) so nothing here
  blocks on this choice — but it remains open, and affects which managed
  equivalents (managed Postgres, managed Redis, managed Kubernetes) become
  available later.

---

## 20. Relationship to `Implementation_Plan.md`

This document describes the target architecture and the reasoning behind
it. The concrete, ordered, buildable work — which files to touch, in what
sequence, with what acceptance criteria for each stage — lives in
`Implementation_Plan.md`, organized as Stages G through L. Read this
document for *what* the system should look like and *why*; read
`Implementation_Plan.md` for *how* to get there, one verifiable step at a
time.
