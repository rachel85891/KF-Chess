# Server Design — Cloud Scale Plan (KF-Chess)

Living design document for the server-side cloud scale-up, per the two
architecture requirements: (1) support for the specific scale numbers given
(100M registered users, 10M concurrent players, per-user traffic profile,
30–90s match durations), and (2) the general design principles from the
technical-debt review — no magic numbers/strings, internal representation
as the source of truth rather than "just make it work," strict layer/class
boundaries, and layering as a recursive, parallel, interchangeable process.

Continuation of, and consistent with, `docs/spec.md` and `docs/client_spec.md`.

> **This is the decisions/rationale document — what was chosen and why.**
> **For the actual work plan** — ordered, buildable stages with concrete
> files, tasks, and acceptance criteria to start development from — see
> **`Implementation_Plan.md`**, in the same directory. Every stage there
> cites the section of this document it implements; read this document for
> the "why," read `Implementation_Plan.md` for the "what/when/how."

## Table of Contents

- **Part 1 — Registered-User Database (100M users)**
  - 1.1 Requirement, restated precisely
  - 1.2 Is SQLite suitable? No — and here's precisely why
  - 1.3 What the access pattern tells us about the right replacement
  - 1.4 Load estimate
  - 1.5 Architectural impact — keeping the layer boundary clean
  - 1.6 Caching layer
  - 1.7 Decisions log (resolved)
  - 1.8 Summary
- **Part 2 — Topology & Routing (10M concurrent players)**
  - 2.1 Is one server enough?
  - 2.2 Two distinct node roles
  - 2.3 Presence/routing via Redis-backed `SessionCoordinator`
  - 2.4 "Everyone can play with everyone" / "join any room" — the relay design
  - 2.5 Load estimate — roughly how many pods
  - 2.6 Redis needs to be highly available
  - 2.7 Role/responsibility summary table
  - 2.8 Decisions log
  - 2.9 Deferred / open items
- **Part 3 — Network Traffic Volume (step every 2 seconds)**
  - 3.1 Measured message sizes (from the real wire-format code, not estimates)
  - 3.2 Why one player "step" is not one message — the real amplification
  - 3.3 Per-player bandwidth — is it a lot for *one* internet connection?
  - 3.4 Fleet-wide aggregate bandwidth — is it a lot for the *infrastructure*?
  - 3.5 A real inefficiency this measurement surfaced (flagged, not fixed here)
  - 3.6 Code-level performance/efficiency recommendations
  - 3.7 Decisions log / literal answer
- **Part 4 — Match Duration (30–90s) & Node Role Implications**
  - 4.1 Requirement, restated
  - 4.2 What this means for Match-Host pods: extreme churn, not extreme duration
  - 4.3 A genuinely favorable property this creates — bounded worst case
  - 4.4 Graceful shutdown / draining pattern for Match-Host pods
  - 4.5 Match-Host pods are a strong fit for spot/preemptible instances
  - 4.6 What this means for Gateway pods — a different lifecycle entirely
  - 4.7 Pre-match waiting state does not belong on a Match-Host pod
  - 4.8 Decisions log
- **Part 5 — Failure Modes, Resilience & Traffic-Capacity Validation**
  - 5.1 Requirement, restated (two distinct questions)
  - 5.2 Match-Host pod crash — the real distinction from an ordinary disconnect
  - 5.3 Gateway pod crash — a genuine, concrete client-side gap
  - 5.4 Database (Cassandra/Scylla) node failure
  - 5.5 Redis (coordination layer) failure
  - 5.6 Disk-full scenarios, component by component
  - 5.7 Overload / traffic-spike handling (not a crash, but exceeding capacity)
  - 5.8 Does the design meet Part 3's traffic requirement in every state?
  - 5.9 Decisions log / open items

---

## Part 1 — Registered-User Database (100M users)

Answers: at 100M registered users, is SQLite suitable? If not, what replaces
it, and what does that require of the existing architecture?

Continuation of `docs/spec.md` / `docs/client_spec.md`'s conventions. This
section answers: *at 100M registered users, is SQLite suitable? If not, what
replaces it, and what does that require of the existing architecture?*

---

### 1.1 Requirement, restated precisely

100,000,000 **registered** accounts (not concurrently online — that's
Section 2). The existing persistence surface, `UserRepository`
(`server/persistence/user_repository.py`), already defines the *exact* shape
of what this DB needs to serve:

```python
create_account(username, password) -> bool
verify_login(username, password) -> bool
get_rating(username) -> int
update_rating(username, new_rating) -> None
```

**Important observation, stated first because it drives every decision
below:** every single one of these four operations is a lookup or write **by
primary key (`username`) only**. There is no join, no range query, no
"find all users where...". The access pattern is pure key-value, even though
it's currently implemented on top of a relational engine (SQLite).

---

### 1.2 Is SQLite suitable? No — and here's precisely why, not just "it doesn't scale"

SQLite's own persistence module already documents its real constraint
explicitly (`user_repository.py`'s own docstring): a single `UserRepository`
instance is only safely usable from **the one thread that constructed it**
(`sqlite3.connect`'s default `check_same_thread=True`), and the file itself
is a single OS file on a single machine's disk.

This isn't a tuning problem — it's a structural mismatch with the
requirement, on three independent axes:

| Axis | What 100M users + a global player base needs | What SQLite gives |
|---|---|---|
| **Network access** | Many server processes, on many machines, in many regions, all writing/reading the same account data | None — SQLite is an embedded, single-process, local-file engine. It was never designed to be reached over a network by independent processes at all. |
| **Concurrent writers** | Account creation and rating updates arriving continuously from every active `GameServer` instance worldwide | A single writer at a time, file-locked; concurrent writes from multiple *processes* (not just threads) routinely produce `database is locked` errors under real contention. |
| **Durability / availability** | The account store must survive a single machine's disk or process dying, without losing data or going offline | A single file on a single disk is a single point of failure with no built-in replication. |

None of this is a criticism of the existing code — `UserRepository`'s own
docstring already flags this precisely as "Stage D2 gap, deliberately
deferred." This section is that deferred decision.

---

### 1.3 What the access pattern tells us about the *right* replacement (not just "a bigger SQL database")

Because every operation is `get`/`put`/`update` by a single key, this is a
textbook fit for a **distributed key-value / wide-column store**, not
necessarily a full relational database. Before picking a specific product,
it's worth being explicit that "SQLite doesn't scale, so use Postgres" would
be solving the wrong problem — a relational engine's main strength (joins,
multi-table transactions, complex queries) isn't something this workload
uses anywhere in its current four methods.

**Two realistic families, both viable, with a real tradeoff:**

**A. Distributed relational (e.g. managed Postgres with sharding, or a
distributed-SQL engine like CockroachDB/Spanner):**
- ✅ Familiar SQL, ACID transactions, easy to reason about, existing PBKDF2 +
  salted-hash scheme carries over unchanged (same relational row shape).
- ✅ Leaves room for future features that *do* need joins (leaderboards,
  friends lists, match history queries) without a second migration later.
- ❌ Sharding-by-username still needs to be designed explicitly (which shard
  owns which username range/hash) — this doesn't come for free just by
  picking "a bigger SQL database."

**B. Distributed key-value / wide-column store (e.g. DynamoDB, Cassandra/
ScyllaDB, or a managed equivalent):**
- ✅ Horizontal partitioning by key (`username`) is the product's native
  design point — this is exactly the workload these systems are built for.
- ✅ Typically simpler to reason about at extreme write throughput (see §4).
- ❌ No joins later without adding a second, purpose-built system (e.g. a
  search/analytics index) if richer queries are ever needed.

**Decision: B (distributed KV/wide-column), specifically Cassandra or
ScyllaDB, self-hosted as containers under Kubernetes/K3s.** Rationale, in
order of weight:

1. **Access pattern fit** — every real requirement so far is pure key access;
   paying sharding-design cost for joins nothing currently needs is the wrong
   trade. If a genuinely relational feature (leaderboards, match history) is
   added later, it gets its own purpose-built read store fed from this one —
   not a reason to burden the main account store with a relational engine
   today.
2. **No cloud provider is chosen yet, and the surrounding requirement (from
   the same email) is to learn Docker/Kubernetes/K3s independently** — this
   is a real architectural signal, not just a side learning task: it implies
   the scale design needs to be **runnable and demonstrable now**, on your
   own K3s cluster, not merely described as "we'd buy a managed AWS/GCP
   service." A proprietary managed product (e.g. DynamoDB) can't be deployed
   under K3s at all and would lock the project to one provider before that
   choice is even made. Cassandra/ScyllaDB are open-source, ship official
   Helm charts, and run identically whether self-hosted on K3s today or later
   moved to a managed Kubernetes offering (EKS/GKE/AKS) on whichever provider
   is eventually chosen.
3. **This decision is fully reversible without touching a single caller**,
   because of the `Protocol` boundary in §5 — see the consistency-per-operation
   design in §7 for how the same store serves both `verify_login` (needs
   strong consistency) and `get_rating` during matchmaking (eventual
   consistency is preferable, for throughput) via per-query consistency
   levels, which Cassandra/ScyllaDB support natively.

---

### 1.4 Load estimate — why this isn't just a "big number" problem

100M *registered* accounts is not, by itself, large for either family above
(both routinely handle multi-billion-row datasets) — the number that
actually stresses the design is **write throughput from Section 2's 10M
concurrent players**, worth estimating now since it directly informs §3's
choice:

- 10M concurrent users → roughly 5M concurrent 2-player matches.
- Matches last 30–90s (per the requirement) → call it ~60s average.
- Completed-match rate ≈ 5,000,000 / 60 ≈ **~83,000 matches/second**
  finishing, worldwide, at steady state.
- Each finished match triggers (at least) 2 rating updates
  (`update_rating`, once per player) → **~166,000 writes/second**, sustained,
  just for ratings — not counting new-account creation or login traffic on
  top of that.

This confirms §3's direction: a workload that's overwhelmingly simple,
single-key writes at ~150–200K/sec is squarely inside what a properly
partitioned KV/wide-column store handles as routine, and is the kind of
number that makes "shard a relational engine yourself" a meaningfully harder
operational lift than reaching for a system built around partitioning from
the start.

---

### 1.5 Architectural impact — keeping the layer boundary clean (this is the part that matters most for your codebase specifically)

**The good news, stated plainly:** `UserRepository`'s own *method signatures*
(`create_account`/`verify_login`/`get_rating`/`update_rating`) are already
exactly the right shape — nothing about the DB choice above requires changing
what a caller of `UserRepository` does. What needs to change is that
`UserRepository` today is a **concrete class tied to one implementation**
(SQLite), not an abstraction with swappable backends. This is precisely the
"internal representation as hero" principle from your second email, applied
here: get the *interface* right once, and the backend becomes a genuinely
swappable detail rather than something that leaks into every caller.

**Concrete change required:**

```python
class UserRepository(Protocol):
    def create_account(self, username: str, password: str) -> bool: ...
    def verify_login(self, username: str, password: str) -> bool: ...
    def get_rating(self, username: str) -> int: ...
    def update_rating(self, username: str, new_rating: int) -> None: ...
```

- `SqliteUserRepository` — **the existing class, renamed, unchanged
  internally** — kept as the real implementation for local dev and the
  existing test suite (`:memory:`). This is not thrown away; it becomes one
  interchangeable implementation (LSP), exactly the same relationship
  `docs/client_spec.md` §1 already establishes between `RecordingSurface` and
  `ImgSurface`.
- A new `DistributedUserRepository` (or whatever the chosen managed service's
  SDK dictates) implements the same `Protocol` for production.
- **No caller changes.** `GameServer`/auth flow continues to depend only on
  the `Protocol`, never on which concrete class is behind it — the same DIP
  relationship the project already applies to `ProtocolHandler`.
- The PBKDF2 + per-user-salt hashing scheme itself (`user_repository.py`'s
  own well-documented reasoning) carries over unchanged regardless of which
  storage backend is chosen — hashing is orthogonal to where the row lives.

---

### 1.6 A caching layer belongs in front of this, not instead of it

Worth flagging now, ahead of Section 3's traffic analysis: `get_rating` is
called on essentially every matchmaking attempt (Section 2 territory) —
almost certainly the single hottest read against this store. A read-through
cache (e.g. Redis) in front of the durable store, keyed by `username`, is a
near-mandatory addition at this scale — not to replace the durable store
(ratings must still be correctly persisted), but so that the *steady-state*
read load hitting the actual database is far lower than 10M concurrent
players would otherwise imply. This will be designed properly once Section 2
(routing/coordination) is worked out, since the two share infrastructure.

---

### 1.7 Decisions log (resolved)

1. **Family/product:** Cassandra or ScyllaDB (final pick between the two is a
   secondary, low-risk decision — both satisfy everything above; ScyllaDB is
   API-compatible with Cassandra but generally lower-latency per node,
   Cassandra has the larger ecosystem/community). Self-hosted as containers
   under Kubernetes/K3s, not a managed proprietary service, since no cloud
   provider is chosen yet and the project needs this runnable independent of
   that choice (§3.2).
2. **Cloud provider:** confirmed still open/unknown. This is exactly why §3.2
   matters — the store choice above does not require this decision to be made
   first, and stays fully portable once it is.
3. **Consistency — resolved as *per-operation*, not one system-wide setting:**
   - `create_account` / `verify_login`: **strong consistency required.**
     Staleness here risks a race allowing two accounts with the same
     username, or a login succeeding against an out-of-date password record.
     Correctness outweighs latency for these two, low-frequency-per-user
     operations.
   - `get_rating` during matchmaking: **eventual consistency preferred.**
     Worst case, a player is matched against a rating that's a fraction of a
     second stale (their previous match just ended) — self-correcting on the
     very next match, and this is the single hottest read path (§4, §6), so
     the throughput/latency win is worth it here specifically.
   - `update_rating`: write-side, not read-side — durability matters (a
     rating update must not be lost), but does not need to be *immediately*
     visible to every replica before returning success. Cassandra/ScyllaDB
     express this per-query via tunable consistency levels (e.g. `QUORUM` for
     auth-related operations, `ONE`/`LOCAL_ONE` for rating reads), so this is
     a query-level setting, not an architectural fork.

---

### 1.8 Summary answer to the literal question asked

**No, SQLite does not suit 100M registered users** — not primarily because of
row count, but because it is a single-file, single-machine, single-writer
embedded engine with no network access, incompatible with multiple
`GameServer` processes worldwide needing to read/write the same account data.

**Decided replacement:** Cassandra or ScyllaDB, partitioned by `username`,
self-hosted as containers under Kubernetes/K3s (portable to a managed
Kubernetes offering once a cloud provider is chosen), with per-operation
consistency (strong for `create_account`/`verify_login`, eventual for
`get_rating` reads during matchmaking). The concrete code change required is
turning `UserRepository` into a `Protocol`, with the existing SQLite class
demoted to "one interchangeable implementation, used for local dev/tests,"
not deleted.
---

## Part 2 — Topology & Routing (10M Concurrent Players)

Answers the four sub-questions from the requirement: is one server enough;
how do we know which node a player is on; how do "everyone can play with
everyone" and "join any room from anywhere" actually work; how are roles
divided between node types.

Continuation of Section 1. Answers the four sub-questions from the
requirement: is one server enough; how do we know which node a player is on;
how do "everyone can play with everyone" and "join any room from anywhere"
actually work; how are roles divided between node types.

---

### 2.1 Is one server enough? No — and here's the actual capacity argument

The current server is a **single asyncio process**: one event loop, running
every `GameSession`'s tick loop, every WebSocket connection's I/O, and all
matchmaking/room logic, in one thread.

Two independent limits, either one of which already rules this out at 10M
concurrent players:

- **CPU**: the tick loop (per `docs/client_spec.md`'s ~30 FPS convention)
  means every live `GameSession` needs its state advanced on a predictable
  cadence. A single-threaded event loop shares one CPU core across *all* of
  them — at 5M concurrent matches (10M players, paired), no single core comes
  close, by orders of magnitude, regardless of how efficient the per-tick
  work is. *(Exact per-core capacity needs a real benchmark — flagged as an
  open item in §9, but the conclusion — "one process is nowhere near enough"
  — doesn't depend on the precise number.)*
- **Connections**: 10M simultaneous long-lived WebSocket connections on one
  OS process is already past practical single-machine limits (file
  descriptors, memory per connection, kernel network stack tuning) well
  before CPU becomes the bottleneck.

**Conclusion: horizontal partitioning across many processes/pods is
mandatory**, not an optimization.

---

### 2.2 Two distinct node roles — the recursive-layering principle applied at the infrastructure level

Your second email's principle — *"layering is a recursive process; layers
co-exist in parallel and are interchangeable"* — applies here directly, one
level up from the code: today, one process contains
presentation/application/persistence layers together. At the infrastructure
level, we split **by role**, without duplicating any logic — the same
composition roots (`GameServer`, `SessionCoordinator`, `GameSession`) get
redeployed differently depending on which role a given pod plays, not
rewritten.

**Role A — Lobby/Gateway nodes:**
- Terminate the client's WebSocket connection.
- Own AUTH (via `UserRepository`, Section 1).
- Own matchmaking/room decisions (`SessionCoordinator`, Play/Create/Join) —
  but the *state* behind those decisions now lives in Redis (§4), not in this
  pod's memory, so any Gateway pod can serve any client.
- Do **not** run a `GameSession` tick loop themselves.
- Stateless from the game-logic perspective → trivially horizontally
  scalable behind a normal Kubernetes `Service` (standard round-robin/
  least-connection load balancing is fine — any Gateway pod can handle any
  new connection).

**Role B — Match-Host nodes:**
- Run actual `GameSession` tick loops — the CPU-bound, stateful part.
- Never speak the wire protocol directly to end clients (see §5) — they only
  need to be reachable *inside* the cluster, from Gateway pods.
- Each pod hosts many concurrent matches (bounded by the same CPU limit
  discussed in §1) — but far fewer processes total than "one process per
  match" would require, since a single asyncio process already hosts many
  `GameSession`s concurrently today.

This split is exactly a **recursive re-application of the same boundary the
project already draws inside one process** — `GameServer` is documented as
"the one class that knows about both networking and game hosting"; at
infrastructure scale, that single responsibility is deliberately split into
two node *roles*, each of which is simpler (and independently scalable) than
the combined thing, without inventing new logic to do it.

---

### 2.3 How do we know which player is on which node — Redis-backed `SessionCoordinator`

This directly extends the `SessionCoordinator` design already agreed for
Stage F2: the `Protocol` (`create_room`/`join_room`/`find_match`) doesn't
change. What changes for production is *only* the concrete implementation
behind it — from the in-memory `Dict` (correct for local dev/tests, same as
`MatchmakingQueue`'s own current form) to a **Redis-backed implementation**:

| Concern | Redis structure |
|---|---|
| Matchmaking queue (rating-based pairing) | Sorted set, scored by rating — `ZADD`/`ZRANGEBYSCORE` for the ±100 window, same semantics `MatchmakingQueue` already implements, just shared across all Gateway pods instead of private to one process |
| Room registry (`room_code → occupants/state`) | Hash, keyed by `room_code` |
| Presence/routing map (`match_id → hosting pod address`) | Simple key-value entry, written once when a Match-Host pod is allocated a session, read by whichever Gateway pod needs to route to it |

**No caller changes** — `GameServer` (or its Gateway-role successor) still
talks only to the `SessionCoordinator` `Protocol`, exactly as decided for F2.
This is the same DIP relationship applied a second time: Redis is simply the
backend that makes the *existing* interface visible across many processes
instead of one.

---

### 2.4 "Everyone can play with everyone" / "join any room from anywhere" — the relay design

This is the part that actually needs a real design decision, not just "use
Redis." The question underneath it: once a client is connected to *some*
Gateway pod, and their match ends up hosted on *some* Match-Host pod, how do
the client's messages actually reach the right pod?

**Two real options:**

**A. Direct-connect (the "GameLift/Agones-style" production pattern):**
Matchmaking returns a specific Match-Host pod's address; the client
disconnects from the Gateway and opens a *new* WebSocket connection directly
to that pod. No relay hop, lowest latency.
- ❌ Requires each Match-Host pod to be individually, publicly reachable
  (its own routable address) — on Kubernetes this needs either a dedicated
  game-server allocator (e.g. Agones) or per-pod `NodePort`/`LoadBalancer`
  management, which is real operational complexity beyond plain
  Deployments/Services.
- ❌ Meaningfully harder to stand up and demonstrate on a self-managed K3s
  cluster within this project's scope.

**B. Relay/proxy through the Gateway (recommended for this project):**
The client's WebSocket connection to its Gateway pod never changes. Once the
Gateway learns (via §3's presence map) which Match-Host pod owns the match,
it opens its **own** internal connection to that Match-Host pod (through a
plain Kubernetes `ClusterIP` `Service` — standard, no special game-server
tooling needed) and relays frames in both directions.
- ✅ Buildable with ordinary Kubernetes primitives — fits the "learn
  Docker/K8s/K3s independently" scope of this stage without requiring a
  specialized game-server allocator.
- ✅ **Session affinity for the match is automatic**: one Gateway↔Match-Host
  link persists for the whole match, and all of that match's frames flow
  over it — no sticky-session configuration needed anywhere.
- ❌ One extra network hop per message (client → Gateway → Match-Host)
  versus (A)'s direct path — real latency cost, but for a project at this
  stage, buildable-and-demonstrable outweighs shaving a few milliseconds.

**Decision: B (relay through Gateway).** Flagging A explicitly as the
"how this is really done at massive commercial scale" answer, and a
legitimate future upgrade once/if a specific cloud provider and its
game-server tooling are chosen — but not the right starting point here.

**Why this answers "everyone can play with everyone" / "any room from
anywhere":** because the *decision* of where to route (§3, Redis) is
decoupled from *which* Gateway pod a client happens to be connected to. A
client connected to Gateway pod #3 can be matched with, or join a room
created by, a client on Gateway pod #47 — both Gateways read the exact same
shared Redis state, and each independently opens its own relay link to
whichever Match-Host pod actually owns that session.

---

### 2.5 Load estimate — roughly how many pods

- **Match-Host pods**: 5M concurrent matches ÷ (some per-pod concurrent-match
  capacity, TBD by real benchmark — see §9) — the *shape* of this number
  matters more than its exact value right now: it scales with **concurrent
  matches**, not with registered users or even total online players directly.
- **Gateway pods**: 10M concurrent WebSocket connections ÷ (some
  per-pod connection capacity, largely memory/FD-bound rather than
  CPU-bound, since Gateways don't run tick loops) — scales with **concurrent
  connections**, a different metric from Match-Host's.

**This is precisely why the two roles need separate autoscaling policies**
(different Horizontal Pod Autoscaler metrics — connection count for
Gateways, active-match count for Match-Hosts) — conflating them into one
role/one scaling policy would force both to scale on whichever metric fits
worse. §4's Section-4-of-the-email question (30–90s match duration) sharpens
this further for Match-Host pods specifically — very short-lived work units
mean Match-Host capacity can (and should) be scaled and bin-packed far more
aggressively/reactively than Gateway capacity, whose connections may sit idle
in a lobby far longer than any single match lasts. *(Full treatment of this
is Section 4's job — flagged here only because the numbers in this section
depend on it.)*

---

### 2.6 Redis itself needs to be highly available

Once Redis holds the matchmaking queue, room registry, and presence map, it
becomes a **single point of coordination failure** for the whole fleet if
run as one instance — a different risk profile than "a cache that's merely
slow to warm up again." Requires Redis Cluster or Sentinel-based
replication, not a single pod, before this is production-real. Flagged
explicitly rather than left implicit.

---

### 2.7 Role/responsibility summary table

| | Gateway/Lobby nodes | Match-Host nodes |
|---|---|---|
| Terminates client WebSocket | ✅ | ❌ (never talks to clients directly) |
| Runs AUTH | ✅ | ❌ |
| Runs `SessionCoordinator` (matchmaking/room decisions) | ✅ (reads/writes shared Redis) | ❌ |
| Runs `GameSession` tick loop | ❌ | ✅ |
| Scales on | concurrent connections | concurrent active matches |
| Statefulness | stateless (any pod serves any client) | stateful for the life of each match it hosts |
| Typical pod lifetime | long-lived | short-lived (bounded by 30–90s match duration) |

---

### 2.8 Decisions log

1. **Topology:** two node roles (Gateway, Match-Host), not one uniform
   server image — required by the CPU/connection math in §1, not a
   preference.
2. **Coordination backend:** Redis, reusing the same instance already
   proposed as a cache in Section 1 §6 — one new infra component serving two
   related, ephemeral-state jobs, not two separate ones.
3. **Routing model:** relay-through-Gateway (option B, §4), not
   direct-connect — chosen for buildability on self-managed K3s within this
   project's scope; direct-connect flagged as a valid future upgrade once a
   cloud provider and its game-server tooling are chosen.
4. **`SessionCoordinator` Protocol unchanged** — Redis is a swapped backend
   behind the exact interface already agreed for Stage F2, no caller changes.

---

### 2.9 Deferred / open items

- **Real per-pod capacity numbers** (concurrent matches per Match-Host pod,
  concurrent connections per Gateway pod) — needs an actual load test/
  benchmark once F-stage code exists to benchmark; this document's estimates
  are structural (what scales on what), not numeric predictions.
- **Redis Cluster/Sentinel topology specifics** (§6) — how many
  shards/replicas, cross-region behavior — deferred until a cloud provider
  is chosen, since managed Redis offerings differ meaningfully here.
- **Full Match-Host autoscaling policy** — the real subject of Section 4
  (average match duration 30–90s); this section only establishes that it
  needs its *own* policy, separate from Gateway's.
---

## Part 3 — Network Traffic Volume (Step Every 2 Seconds)

Answers: an active player steps roughly every 2 seconds — how much network
traffic does that cause, and is it a lot or a little for an internet
network?

**Method used here, stated up front:** rather than guessing typical
message sizes, every number below was measured by actually running this
project's real wire-format code (`kungfu_chess/notation/*_wire_format.py`,
`kungfu_chess/io/board_printer.py`) against realistic inputs — a standard
8x8 starting position, a real `MoveAccepted`/`PieceArrived` event pair, and
a real `MovesLogSnapshot` at various lengths. These are actual byte counts
this codebase produces today, not estimates.

### 3.1 Measured message sizes (from the real wire-format code, not estimates)

| Message | Direction | Real measured size |
|---|---|---|
| Move command, e.g. `WQe2e4` | Client → Server | **6 bytes** |
| `EVT:MOVE:...` (MoveAccepted) | Server → each connection | **21 bytes** |
| `EVT:ARRIVED:...` (PieceArrived) | Server → each connection | **22 bytes** |
| Full board text (`BoardPrinter`, 8×8, starting position) | Server → each connection | **159 bytes** |
| `STATE:...` snapshot, 1 move-log entry | Server → each connection | **30 bytes** |
| `STATE:...` snapshot, 10 entries | Server → each connection | **202 bytes** |
| `STATE:...` snapshot, 30 entries | Server → each connection | **602 bytes** |
| `STATE:...` snapshot, 60 entries | Server → each connection | **1,202 bytes** |

The `STATE:` row is deliberately shown at four lengths, not one — see §3.2:
this message's size is **not constant**, and that turns out to matter.

### 3.2 Why one player "step" is not one message — the real amplification

Reading `server/application/game_server.py`'s own `_broadcast_event`
directly (not assuming): **a single accepted move triggers two separate
broadcast events, not one** — `MoveAccepted` fires immediately when the
server accepts the move command; `PieceArrived` fires again, separately,
once the piece's travel animation actually completes
(`duration_ms` later). Each of those two events independently triggers:

1. The `EVT:...` message for that specific event.
2. The **entire current board**, resent in full (`_current_board_text`) —
   not a diff of what changed.
3. For `MoveAccepted`/`PieceArrived` specifically (not every event type),
   the `STATE:...` snapshot — which, per §3.1, **carries the entire
   move/capture log accumulated so far in the match**, resent in full every
   single time, not incrementally.

...and every one of those three messages is sent to **both connections in
the match** (`match.colors.keys()` — both players; a future Viewer, per
Section-F's design, would receive the same three messages too, multiplying
this further for a viewed room).

**So one player's single "step" (one accepted move) produces:**

```
2 events (MoveAccepted, PieceArrived)
  × 3 messages per event (EVT + board + state)
  × 2 connections (both players)
= 12 outgoing server messages per single player step
  (plus the 1 incoming 6-byte command from the player who moved)
```

**Using a representative mid-match average** (STATE at ~30 entries, i.e.
roughly halfway through a 60-entry match — see Part 4 for why matches
produce on this order of log entries): each event's payload ≈
21 (EVT) + 159 (board) + 602 (state) ≈ **782 bytes**, sent to 2 connections,
twice (MoveAccepted + PieceArrived) ≈ **~3,130 bytes of server egress per
single player step**, at this representative point in a match. Early-match
steps are lighter (~840 bytes total, STATE still small); late-match steps
are heavier (~5,500 bytes total, STATE near its match-end size) — the true
figure ramps up over a match's lifetime rather than staying constant (§3.5
explains why, and flags it as worth fixing).

### 3.3 Per-player bandwidth — is it a lot for *one* internet connection?

Using the ~3,130-byte representative figure from §3.2, over the 2-second
step interval: **≈ 1,565 bytes/sec ≈ 12.5 kbps downstream, per player.**
Upstream (the player's own move commands) is even smaller: 6 bytes / 2s =
3 bytes/sec, effectively negligible.

**This is trivially small for any real internet connection** — for
comparison, a single voice call needs roughly 24–64 kbps, and video calling
needs several hundred kbps to multiple Mbps; this game's per-player traffic
sits meaningfully *below* a voice call, let alone video. **For an individual
player, the answer is unambiguously "very little."**

### 3.4 Fleet-wide aggregate bandwidth — is it a lot for the *infrastructure*?

This is a different question from §3.3, and the answer is different too.
10,000,000 concurrent players, each stepping every 2 seconds, is
**5,000,000 steps/second, worldwide, at steady state.**

- At the ~3,130-byte representative per-step figure: **5,000,000 ×
  3,130 bytes ≈ 15.65 GB/sec ≈ ~125 Gbps sustained, worldwide, at peak.**
- The realistic range, using the early-match/late-match bounds from §3.2
  instead of the single representative point, is roughly **30–220 Gbps**,
  depending on where in their matches the fleet's players happen to be at
  any given instant.
- This is **raw application payload only** — real wire traffic (WebSocket
  framing, TCP/IP headers, TLS record overhead for `wss://`) adds a further
  20–50% on top as a rule of thumb, so a genuinely conservative planning
  figure is closer to **150–250 Gbps sustained**, worldwide, at 10M
  concurrent players.

**Is that a lot?** Genuinely — yes, at the infrastructure level, though not
unprecedented for cloud-scale live services: it's well beyond what a single
machine or even a handful of machines push, and requires real multi-region
network engineering (this is exactly why Section 2's Gateway/Match-Host
split and geographic distribution matter) — but it is the same order of
magnitude many real large-scale online services and CDNs already operate
at, not something categorically impossible. **The honest, complete answer
is: negligible per individual player (§3.3), genuinely significant at fleet
scale (this section) — these are two different questions with two different
answers, and the requirement as phrased is really asking both.**

### 3.5 A real inefficiency this measurement surfaced (flagged, not fixed here)

Worth surfacing explicitly, in the spirit of "internal representation as
hero, not just making it work": **§3.1's numbers show the `STATE:` message
growing linearly with match length because the entire move/capture log is
resent, in full, on every single motion event — even though the client
already received every earlier entry incrementally, the moment each one
happened.** The same is true of the full board resend. Over a match, this
makes total STATE-message bytes sent grow roughly with the **square** of
the number of moves (each of N events resends an average of ~N/2 entries'
worth of data), not linearly — §3.2's early-vs-late-match spread is that
effect, directly measured.

**This is not a Section-3 fix** (changing it would mean changing
`format_game_state_snapshot`'s own wire contract, a real design decision
with its own tradeoffs — e.g. sending only the newest entry each time
means a client that briefly missed one message now has a genuinely
incomplete log, which the current full-resend design deliberately avoids).
Flagging it here because §3.4's aggregate bandwidth figure is directly
downstream of this design choice, and it's exactly the kind of thing worth
a deliberate decision later, rather than an accidental byproduct nobody
chose on purpose.

### 3.6 Code-level performance/efficiency recommendations

Direct answer to "are there code changes worth making for speed/efficiency
over a wide network, or is this already factored into the plan": **Part 3's
numbers measured the protocol as it exists today — they don't yet reflect
possible protocol-level improvements.** Real measurements (using this
project's own actual wire-format output, not estimates) surfaced the
following, split by risk/effort:

**Already good, no change needed:** the project already avoids periodic
"keep the clock ticking visually" broadcasts — the client renders its own
local timer between authoritative updates (documented reasoning in
`protocol_handler.py`'s own module docstring). This is exactly the right
call and should stay as-is.

**Low-risk, transport-only, zero wire-protocol change — recommended:**
enabling WebSocket per-message compression (`permessage-deflate`, RFC 7692)
on the `websockets` server. Measured directly (via `zlib`, on the exact
payloads from §3.1) rather than estimated:

| Message | Raw | Compressed (standalone `zlib`) | Ratio |
|---|---|---|---|
| Full board (159 B) | 159 | 62 | ×2.56 |
| STATE, 10 entries | 202 | 74 | ×2.73 |
| STATE, 30 entries | 602 | 131 | ×4.6 |
| STATE, 60 entries | 1,202 | 191 | ×6.29 |
| `EVT:MOVE:...` (21 B) | 21 | 29 | *grows* |

The large, repetitive messages (board, STATE) — the exact ones dominating
§3.4's bandwidth figure — compress well; the small `EVT:` messages don't,
under **standalone** compression (each `zlib.compress` call pays its own
fixed header cost). A real WebSocket `permessage-deflate` connection uses
context takeover (a persistent compression dictionary across the whole
connection), which should do meaningfully better on small, repetitive
messages than this standalone measurement shows — real gain there needs a
live-connection benchmark to quantify precisely, but the direction is
favorable. **This is a single server-startup configuration flag — it
touches no file in `server/presentation/` or `kungfu_chess/notation/`, and
requires zero client protocol change**, making it close to a free win.

**Low-risk, process-level, unrelated to network volume but relevant to
Part 2's per-pod capacity:** replacing the default asyncio event loop with
`uvloop` (a drop-in, libuv-based replacement) for the Match-Host process —
a one-line change in `server/main.py`, no logic touched, well-established
for I/O-bound asyncio workloads exactly like this one.

**Larger change, explicitly deferred, not recommended right now:**
replacing full-board/full-log resends (§3.5's finding) with incremental
deltas would cut §3.4's bandwidth further, likely substantially, even
before compression — but changes the wire contract's own current
self-healing property (a client that missed a message currently recovers
automatically on the next full resend; a delta-based design would need its
own explicit recovery mechanism). This belongs in its own deliberate design
decision, not as a response folded into this section.

### 3.7 Decisions log / literal answer

1. **Per-player bandwidth: negligible** (~12.5 kbps downstream, ~3 bytes/sec
   upstream) — not a design concern for any individual connection.
2. **Aggregate bandwidth: genuinely significant** (~125 Gbps representative,
   ~150–250 Gbps realistic planning figure with protocol overhead, at 10M
   concurrent) — a real input to Section 2's topology (multi-region Gateway
   distribution, egress cost planning), not a number to wave away.
3. **Flagged for a future, deliberate decision (not resolved here):**
   whether to keep resending the full board/full move-log every event
   (current, simple, self-healing-against-dropped-messages design) or move
   to incremental/delta updates (meaningfully less bandwidth, more complex,
   needs its own reasoning about what happens if a client misses a delta).
   This decision directly moves §3.4's numbers, so it belongs in this
   document once made — not assumed silently either way.
4. **Recommended now, low-risk:** enable WebSocket `permessage-deflate`
   compression (transport-only, zero wire-protocol change) and `uvloop`
   for Match-Host processes (process-only, zero logic change) — both real,
   measured-where-possible (§3.6), safe to adopt without a larger design
   discussion.

---

## Part 4 — Match Duration (30–90s) & Node Role Implications

Answers: matches average 30–90 seconds — what does that say about the roles
of the different node types (Docker containers) in this fleet?

### 4.1 Requirement, restated

This section is the direct follow-through on the split already introduced
in Part 2 §2.2/§2.7 and flagged there as deferred: Gateway and Match-Host
pods were established as two distinct roles with different scaling metrics.
Match duration is exactly the number that determines *how* the Match-Host
role's capacity actually behaves in practice — not just that it needs its
own policy, but what shape that policy should take.

### 4.2 What this means for Match-Host pods: extreme churn, not extreme duration

The number to anchor on is Part 1 §1.4's own load estimate, derived the
same way here: **~83,000 matches completing per second, worldwide, at
steady state** (5,000,000 concurrent matches ÷ ~60s average duration). At
steady state, completions and starts are roughly equal — so a Match-Host
pod isn't hosting a small number of long-lived matches; it's continuously
creating and tearing down `GameSession` instances at a very high rate.

**This is a fundamentally different capacity problem from "how many
matches fit in memory at once."** A single Match-Host pod's real workload
is better described as a *throughput* figure (matches started/finished per
second it can sustain) than a *standing inventory* figure (matches it holds
at any instant) — both matter, but the short duration means the *turnover*
rate is the number worth designing around, not just peak concurrency.

### 4.3 A genuinely favorable property this creates — bounded worst case

Short match duration isn't only an operational burden — it bounds risk in
a way worth stating explicitly, because it directly shapes §4.4 and §4.5:

- **Under-provisioning self-corrects fast.** If Match-Host capacity is
  briefly insufficient during a demand spike, the worst case isn't an
  open-ended queue (as it would be for, say, a video-call service where
  sessions run for hours) — it's a wait of, at most, the time until the
  *next* batch of matches (bounded by 90s) finishes and frees capacity.
- **Disruption blast radius is bounded to ≤90 seconds per affected match.**
  If a Match-Host pod is lost unexpectedly (node failure, spot-instance
  reclaim — see §4.5), the damage is contained to whatever matches that
  one pod happened to be hosting at that moment, each already ≤90s from
  finishing on its own regardless.

### 4.4 Graceful shutdown / draining pattern for Match-Host pods

This is the concrete mechanism that makes §4.3's bounded-risk property
real rather than theoretical, and it directly answers a gap flagged back in
the very first review of this project (before any of Parts 1–3 were
written): a Match-Host pod being scaled down or replaced during a rolling
deploy must not simply be killed.

**Pattern:** cordon-then-drain, using the match-duration bound directly:

1. On scale-down/deploy, mark the pod **not accepting new matches**
   (stop advertising it as a valid target in the Redis presence map from
   Part 2 §2.3 — new matchmaking/room-join results simply never route here
   again).
2. Let currently-hosted matches finish naturally — bounded to **at most
   90 seconds** (the requirement's own upper bound), not an unbounded
   wait, because match duration is short by design.
3. In Kubernetes terms: a `preStop` hook that flips the "not accepting new
matches" flag and blocks (up to a 90–120s grace period, matching the
requirement's own bound plus margin) until the pod's own active-match count
reaches zero, combined with `terminationGracePeriodSeconds` set to match.

**Correction to an earlier claim in this section (originally written
here, corrected after checking the code directly):** this document
previously asserted the existing Stage E2 disconnect-countdown/auto-resign
mechanism would transparently cover an *ungraceful* Match-Host pod loss
(a crash, not this drain). Re-reading `game_server.py`'s own Stage E2
docstring directly shows that's not accurate — it states explicitly that
the mechanism depends on "`GameSession` itself never stopped running
during a countdown (only the WebSocket needed swapping back in)," and
names "resuming after a server restart" as an *explicitly out-of-scope,
accepted gap*. A crashed Match-Host pod loses the `GameSession` itself
(in-memory, unreplicated) — a fundamentally different, NOT-yet-covered
failure mode. See Part 5 §5.2 for the accurate treatment and the real
recommendation.

### 4.5 Match-Host pods are a strong fit for spot/preemptible instances

Following directly from §4.3's bounded blast radius and §4.4's existing
recovery mechanism: **Match-Host pods are unusually well-suited to cheaper
spot/preemptible cloud instances**, specifically *because* of the short
match duration — an instance reclaim interrupts, at most, ≤90s-old matches
that already have a real, existing recovery path (§4.4). This is a
meaningfully different risk profile from running a database, a long-lived
stateful service, or even the Gateway role (§4.6) on spot capacity, where
an interruption's damage isn't naturally time-bounded. **Recommendation:**
Match-Host node pools are a good candidate for spot instances; Gateway node
pools are not (see §4.6) — this is exactly the kind of role-specific
infrastructure decision the Part 2 split was designed to make possible.

### 4.6 What this means for Gateway pods — a different lifecycle entirely

Gateway pods hold the actual client WebSocket connection (Part 2 §2.2),
which is **not bounded by a single match's duration** — a player who
finishes one match and immediately queues for another keeps the same
Gateway connection throughout, potentially for a session lasting far longer
than 90 seconds. Consequences:

- Gateway pod churn/draining needs a **connection-based** drain (stop
  accepting new connections, wait for existing ones to naturally
  disconnect or reach a safe point), not a match-duration-based one —
  there is no equivalent short upper bound to lean on here.
- Gateway pods are a **weaker fit for spot instances** than Match-Host
  pods — losing one mid-session drops a player's live connection with no
  90-second bound on how "fresh" that loss is, unlike a Match-Host loss.

This is the same conclusion Part 2 §2.7's table already stated structurally
("long-lived" vs "short-lived, bounded by 30–90s match duration") — this
section is what justifies that row with a concrete mechanism and a real
infrastructure recommendation, rather than leaving it as an assertion.

### 4.7 Pre-match waiting state does not belong on a Match-Host pod

Worth confirming explicitly, since it touches the Stage-F Room design
discussed earlier: a room created via "Create Room," waiting for a second
player to join via code, has **no active `GameSession` yet** — per the
Stage F1 design, `Room` only becomes `is_ready_to_start` once both a White
and Black occupant are present, and only then does an actual `GameSession`
get created and handed to a Match-Host pod. **The 30–90s figure applies to
active play only, not to however long a room code sits unused** — a
half-empty room's placeholder state lives entirely in the Part 2 §2.3
Redis-backed `SessionCoordinator`/room registry, never occupying any
Match-Host pod capacity. This is a direct confirmation that the F1/F2
design already agreed on is consistent with this section's conclusions,
not a new constraint being retrofitted onto it.

### 4.8 Decisions log

1. **Match-Host autoscaling metric:** active-match-count-per-pod (a custom
   metric), reflecting §4.2's throughput/churn framing — not raw CPU alone,
   though CPU remains a secondary signal.
2. **Graceful shutdown:** cordon-then-drain, bounded by the requirement's
   own 90s upper bound plus margin (§4.4) — a concrete `preStop`/
   `terminationGracePeriodSeconds` pattern, not left implicit.
3. **Spot/preemptible instances:** recommended for the Match-Host node
   pool specifically; not recommended for the Gateway node pool (§4.5,
   §4.6) — a role-specific infrastructure decision enabled directly by the
   Part 2 topology split.
4. **Correction, not a decision:** an earlier draft of this section
   claimed the existing Stage E2 mechanism covers an ungraceful Match-Host
   pod loss — checking the code directly showed this is wrong; see Part 5
   §5.2 for the accurate failure mode and its actual recommendation.
  5. **Confirmed, not newly decided:** pre-match Room waiting state (Stage
   F1/F2) already lives outside any Match-Host pod's resource footprint,
   consistent with this section without requiring any change to that
   earlier design.

---

## Part 5 — Failure Modes, Resilience & Traffic-Capacity Validation

Answers two distinct questions asked together: what happens under load
spikes and real component failures (server crashes, database crashes, disks
filling up), and separately — does the design proposed in Parts 1–4 actually
sustain Part 3's required traffic volume *in every one of those states*, not
just in the steady-state, nothing-ever-fails case those earlier parts
described.

### 5.1 Requirement, restated (two distinct questions)

1. **Failure-mode question:** for each real thing that can go wrong (a
   Match-Host or Gateway pod crashing, the database going down, disk
   filling up), what actually happens, and is it handled?
2. **Capacity-validation question:** does the proposed topology (Part 2)
   still meet Part 3's ~150–250 Gbps traffic requirement while any of those
   failures are happening, or only in the failure-free case those numbers
   were computed against?

### 5.2 Match-Host pod crash — the real distinction from an ordinary disconnect

**Correcting Part 4 §4.4 here, as flagged there:** an ordinary
opponent-disconnect (Stage E2) and a Match-Host pod crash are **not** the
same failure mode, even though both look identical to a still-connected
client at first (their opponent's messages stop arriving). The difference
is what survives:

| | Opponent disconnects (Stage E2, existing) | Match-Host pod crashes (new, not yet handled) |
|---|---|---|
| What's lost | Only the WebSocket connection | The `GameSession` itself — in-memory, unreplicated, per Part 2 §2.2 |
| What's still alive | The `GameSession`, still ticking | Nothing — the process that owned it is gone |
| Recovery mechanism | Same username re-authenticates within the 20s countdown, gets swapped back onto the SAME live session (`game_server.py`'s own Stage E2 docstring) | **None exists today** — the docstring itself names "resuming after a server restart" as an explicitly out-of-scope, accepted gap |

**Recommendation, given Part 4 §4.3's bounded-blast-radius property:**
rather than building real session replication/checkpointing (a large
engineering investment most real-time competitive games deliberately avoid
for exactly this reason — a session is cheap and short-lived, replicating
its live state on every tick is not proportionate), **treat a Match-Host
pod crash as ending the match**, not resuming it:

- Whichever Gateway pod(s) were relaying to the crashed Match-Host detect
  the broken internal connection (Part 2 §2.4's relay link errors out).
- Both clients receive a new, honest wire message for this specific case
  — **not** the existing `opponent_disconnected` (that message's whole
  premise is "the *other* player's connection dropped, yours is fine,"
  which is factually wrong here — both players are equally affected by a
  server-side failure, not each other's connection). A small, real protocol
  addition is needed: something like `match_aborted:<reason>`, following
  the exact same colon-delimited convention every other wire message in
  this project already uses.
- No rating penalty to either player for a server-side match abort — this
  is a correctness requirement, not just fairness: `update_rating` (Part 1)
  must not fire based on a match that ended due to infrastructure failure
  rather than actual play.

This is a real, small scope addition to Stage F/the wire protocol — flagged
here, not designed in full, since it's a protocol decision that deserves
its own review rather than being folded into this failure-mode section.

### 5.3 Gateway pod crash — a genuine, concrete client-side gap

Checked directly in `kungfu_chess/client/network/network_game_client.py`:
today, `_receive_loop`'s `ConnectionClosed` handling and
`_ignore_connection_closed` **swallow the disconnect silently — there is no
automatic reconnect attempt.** This matters specifically for the
Gateway-crash case, because — unlike §5.2 — **the underlying `GameSession`
is fine here**: a Gateway pod crash only severs the client↔Gateway leg; the
Match-Host pod and its live session are untouched, and Part 2 §2.3's Redis
presence map still knows exactly which Match-Host pod owns that match. This
means the existing Stage E2 reconnect-within-countdown mechanism *would*
actually apply here, correctly, **if** the client ever tried reconnecting —
but today it doesn't.

**Recommendation:** add client-side auto-reconnect-with-backoff to
`NetworkGameClient` — on `ConnectionClosed`, attempt a new
`websockets.connect(uri)` to the (load-balanced, any-Gateway-pod-is-fine,
per Part 2 §2.2) Gateway endpoint, then re-run the existing AUTH flow. If
that reconnect lands within Stage E2's existing 20-second countdown window,
the *already-existing* server-side mechanism resumes the match with zero
server-side changes required. **This is the one concrete, currently-missing
piece of code standing between "the server already supports this" and "it
actually works end-to-end" for the Gateway-crash case** — worth
prioritizing precisely because the hard part (server-side) is already done.

### 5.4 Database (Cassandra/Scylla) node failure

Directly addressed by the Part 1 design, not a new gap: a distributed
wide-column store's whole reason for existing here is that losing one node
doesn't lose data or availability, **provided** replication factor and
consistency levels are set deliberately, not left at defaults:

- **Replication factor ≥ 3**, with replicas placed across separate failure
  domains (availability zones, not just separate physical nodes in the same
  AZ) — a single AZ outage must not take out every replica of the same
  partition.
- Part 1 §1.7's per-operation consistency levels are exactly what make this
  survivable in practice: `QUORUM` for `create_account`/`verify_login`
  tolerates one replica being down (out of 3) with zero correctness impact;
  `get_rating` reads at `ONE`/`LOCAL_ONE` keep working even more
  permissively during a partial outage, at the cost the design already
  accepted (brief staleness).
- **What this doesn't cover:** correlated failure (losing multiple
  replicas of the same partition simultaneously, e.g., a full-region
  outage) — genuinely out of scope for this document, belongs in a future
  multi-region disaster-recovery discussion once a cloud provider (still
  open, per Part 1 §1.7) is chosen.

### 5.5 Redis (coordination layer) failure

Part 2 §2.6 already flagged Redis needs Sentinel/Cluster, not a single
instance — this section states what actually happens during that failover,
and why it's an acceptable risk *specifically because* of what Redis holds
here (matchmaking queue, room registry, presence map — all Part 2 §2.3):

- During a Sentinel failover (typically single-digit seconds), a small
  window of recently-written entries can be lost — an in-flight
  matchmaking-queue entry, a room awaiting its second player, a presence-map
  entry for a match that just started.
- **This is a bounded, self-healing loss, not a durability incident** — a
  lost matchmaking entry means that one player's client simply needs to
  retry (already the normal timeout-and-retry path, Stage E1); a lost room
  entry before both players joined means the room code needs recreating,
  not implying data corruption. This is precisely *why* Redis (weaker
  durability, higher throughput/latency profile) was the right choice for
  this specific job in Part 2 §2.3/2.6, and *not* the right choice for
  Part 1's account data (where the same kind of loss would be unacceptable)
  — the two stores' different durability guarantees match their two
  genuinely different jobs, not an oversight.
- **What this doesn't cover:** an *already-active* match's presence-map
  entry being lost during failover, right as a Viewer (Stage F5/F6) tries
  to join via room code — a real, narrow edge case worth a specific test
  once Stage F's Viewer feature and this section are both implemented, not
  resolved further here.

### 5.6 Disk-full scenarios, component by component

| Component | Disk risk | Mitigation |
|---|---|---|
| Cassandra/ScyllaDB nodes | **Real** — durable SSTable storage grows with registered-user count and, more significantly, compaction overhead | Monitoring + alerting on disk usage (an operational requirement, not an architecture one — deferred to a real ops runbook); horizontal scale-out (adding nodes redistributes partitions) as the primary long-term mitigation, not just bigger disks |
| Redis | Low, if run **without** RDB/AOF persistence — a legitimate option here specifically because §5.5 already established this store's data is bounded-loss-tolerant; if persistence IS enabled for faster failover recovery, same monitoring principle as Cassandra applies | Recommend evaluating persistence-off as the default, given §5.5's reasoning — removes this risk entirely for this component, not just mitigates it |
| Match-Host / Gateway pods | **Should be zero, by explicit design constraint** — these pods must never write anything correctness-critical to local disk (ephemeral pod storage is wiped on restart in Kubernetes anyway) | Logs shipped to centralized/streamed logging, never local files — this is a design rule worth stating explicitly, not an incidental fact, precisely so "a pod's local disk filled up" can never become a correctness incident for either role |

### 5.7 Overload / traffic-spike handling (not a crash, but exceeding capacity)

A real, distinct failure mode from an outright crash: demand exceeding
current capacity, faster than autoscaling can react. Checked the code
directly rather than assuming a mechanism exists: `SERVER_FULL_MESSAGE`
(`"server_full"`) **is still defined** in `protocol_handler.py`, but
`game_server.py`'s own docstring confirms the connection-count policy that
used to trigger it was **removed** when dynamic matchmaking replaced the
old fixed-single-match design — so today, nothing in the codebase actually
sends it. This is a real, existing gap, not a hypothetical one.

**Recommendation — two speeds of protection, not one:**
1. **Fast, local safety valve:** reintroduce an active per-Gateway-pod
   connection cap, returning the *already-existing* `server_full` wire
   message when a pod is at its configured local capacity. Immediate (no
   waiting on autoscaling), reuses an existing, already-understood wire
   convention — a small, well-scoped code change.
2. **Slower, cluster-level response:** Part 2's HPA-based autoscaling
   (connection count for Gateways, active-match count for Match-Hosts) —
   reacts over tens of seconds to minutes, not instantly, which is exactly
   why (1) is needed underneath it as a first line of defense during the
   gap before new capacity comes online.

### 5.8 Does the design meet Part 3's traffic requirement in every state?

**Direct answer: not automatically — only if explicit redundancy headroom
is designed in, which Parts 1–4 did not yet specify as a number.** Part 3's
~150–250 Gbps figure was computed for the failure-free, steady-state case.
Under any of §5.2–§5.7's real conditions (a rolling deploy draining
Match-Host pods per Part 4 §4.4, an AZ outage, a spot-instance reclaim
wave), total serving capacity is *temporarily lower* than the fully-healthy
fleet — and Part 3's traffic doesn't pause to wait for that capacity to
return.

**What this requires, concretely:**
- Fleet sizing for both Gateway and Match-Host node pools needs to target
  Part 3's peak figure **plus a redundancy margin**, not exactly Part 3's
  number — a common starting planning figure for this kind of headroom is
  **N+20%**, sized so that losing a single AZ's worth of capacity (a
  realistic single-failure-domain event) doesn't drop the fleet below
  what's actually needed. This specific percentage is a real cost/risk
  trade-off, not a purely technical answer — **flagged as an open decision
  requiring your input**, not decided unilaterally here.
- Geographic distribution of Gateway pods (already implied by Part 2's
  topology) is itself a resilience mechanism for this question, not just a
  latency optimization — it means no single region's network capacity or
  a single upstream provider link becomes the one place all 150–250 Gbps
  has to fit through.
- **Part 3's figure is client-facing (north-south) traffic only.**
  Database replication traffic (Cassandra/Scylla inter-node), Redis
  replication, and the internal Gateway↔Match-Host relay link (Part 2 §2.4)
  are a separate, smaller, internal (east-west) traffic pool with its own
  capacity needs — dramatically smaller in absolute terms (Part 1 §1.4's
  ~166K writes/sec are tiny payloads, nowhere near Part 3's per-step
  numbers), but still real and still needs its own — much lighter —
  headroom, not zero.

### 5.9 Decisions log / open items

1. **Match-Host pod crash:** treated as match-abort, not resume — a small,
   real wire-protocol addition (`match_aborted:<reason>`) is needed, no
   rating impact on either player. Flagged for its own protocol-design
   pass, not designed in full here.
2. **Gateway pod crash:** the server-side recovery mechanism (Stage E2)
   already exists and is correct for this case — the missing piece is
   entirely client-side (auto-reconnect-with-backoff in
   `NetworkGameClient`, currently absent). This is the highest-leverage,
   lowest-risk concrete code change identified across Parts 1–5: it unlocks
   an already-built server capability rather than requiring new server
   logic.
3. **Database node failure:** covered by Part 1's own design (replication
   factor ≥3, multi-AZ placement, per-operation consistency) — no new
   decision needed, correlated/regional failure explicitly out of scope
   for now.
4. **Redis failure:** acceptable bounded loss, consistent with why Redis
   was chosen for this specific job in Part 2 — recommend evaluating
   running without RDB/AOF persistence at all, removing §5.6's disk risk
   for this component entirely.
5. **Disk-full:** real risk only for Cassandra/Scylla (needs monitoring +
   horizontal scale-out, an operational concern deferred to a future ops
   runbook) — explicitly ruled out by design for Match-Host/Gateway pods
   (no critical local disk state, ever).
6. **Overload handling:** reintroduce the already-existing (but currently
   unused) `server_full` message as a fast local safety valve, layered
   under Part 2's slower cluster-level autoscaling — a small, concrete code
   change, not a new mechanism.
7. **Traffic-capacity validation: open decision required.** Confirmed the
   design does *not* automatically meet Part 3's requirement under failure
   without an explicit redundancy margin — recommended a starting figure of
   N+20% fleet headroom, but this trade-off needs your input, not a
   unilateral answer.
