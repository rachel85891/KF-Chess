# PostgreSQL failover chaos test (runbook, not a `pytest` test)

## Why this is a runbook, not a test in the suite

Implementation_Plan.md's own Stage I1 acceptance criteria names a
failover chaos test as part of this stage. A *real* version of that
test requires a genuine multi-node PostgreSQL deployment with
automated failover (e.g. Patroni + a DCS such as etcd/Consul, or a
managed offering with the equivalent), driven from a Helm chart or
similar - standing that up from scratch is real infrastructure work,
out of scope for a single stage's own `pytest` suite to build and
tear down, and it cannot be relied upon to exist (or to behave
identically) in every environment this project's tests run in (this
sandbox has no Docker daemon reachable at all, let alone a
multi-node Postgres cluster - see `I1_prompt.md`'s own Background
section).

`PostgresUserRepository` (`server/persistence/postgres_user_repository.py`)
itself intentionally does **not** contain any failover-specific logic
(no retry-with-backoff against a changing primary, no service-discovery
of a newly-promoted node) - Stage I1's own scope is a single-primary
`dsn` (plus an optional, separately-injectable `read_replica_dsn` for
`get_rating`), not an automated-failover-aware client. This document
is the accepted, documented substitute: a runnable, human-operated
script for exercising a *real* failover once a real multi-node
deployment exists, not a claim that failover is already implemented
or automatically tested in CI.

## Prerequisites

- A real multi-node PostgreSQL deployment with automated failover
  already configured (e.g. Patroni-managed primary + at least one
  replica, fronted by a stable DNS name/VIP that always resolves to
  the current primary - the same shape `Server_Design.md` §1.7/§5.4
  names as the eventual production topology).
- A `PostgresUserRepository` instance (or the real running server
  process) pointed at that stable DNS name/VIP as its `dsn`.

## Procedure

1. **Establish a baseline.** With the cluster healthy, run a small
   loop that repeatedly calls `create_account`/`verify_login`/
   `get_rating`/`update_rating` against real, distinct usernames
   (e.g. `chaos-test-user-<n>`), confirming every call succeeds and
   `get_rating` reflects the most recent `update_rating`.

   ```bash
   python - <<'PY'
   from server.persistence.postgres_user_repository import PostgresUserRepository

   repo = PostgresUserRepository(dsn="postgresql://kfchess:kfchess@<primary-dns>:5432/kfchess")
   for i in range(50):
       username = f"chaos-test-user-{i}"
       repo.create_account(username, "chaos-test-password")
       repo.update_rating(username, 1200 + i)
       assert repo.get_rating(username) == 1200 + i
   print("baseline OK")
   PY
   ```

2. **Trigger a real failover.** While the loop from step 1 is running
   continuously in a separate process/terminal, forcibly stop the
   current primary node (e.g. `patronictl failover`, or killing the
   primary's container/VM outright) and observe the DCS promote a
   replica to the new primary.

3. **Observe and record, don't assume:**
   - How many in-flight `create_account`/`update_rating` calls fail
     (raise, rather than silently succeed) during the promotion
     window - these are genuine, expected write failures during a
     real failover; `PostgresUserRepository` does not currently retry
     them automatically (see "Why this is a runbook" above), so the
     caller (a later stage's own composition-root code, not this
     class) is expected to decide how to handle a raised
     `UserRepositoryError` mid-failover.
   - Whether calls **resume succeeding automatically** once the DNS
     name/VIP starts resolving to the newly-promoted primary again,
     with no code change or process restart required - this is the
     real property being proven: the client-facing `dsn` contract
     (a stable name, not a specific node) survives a real failover,
     even though this stage's client code itself takes no special
     action during one.
   - Whether any previously-committed data (usernames created before
     the failover) is still present and correct on the new primary
     (a synchronous-replication or equivalent durability guarantee at
     the *infrastructure* layer - not something `PostgresUserRepository`
     itself can prove or enforce from the client side).

4. **Restore the original topology** (bring the old primary back up as
   a replica, or otherwise return the cluster to its pre-test
   redundancy level) before considering the chaos test complete.

## What this does NOT prove or claim

- It does not prove `PostgresUserRepository` retries or queues writes
  during a failover window - it currently does not; a caller must
  handle a raised `UserRepositoryError` itself, exactly as it must
  already handle any other repository-level failure.
- It is not run in CI and has no automated pass/fail signal - success
  is a human operator's own read of the observations in step 3,
  against whatever specific multi-node topology is actually in use at
  the time.
- It does not exercise Citus or any other write-throughput scale-out
  path - `Server_Design.md` §1.7 item 4 names Citus as the future
  scale-out story once single-primary write throughput becomes a real
  ceiling; that is explicitly out of scope for this stage too (see
  `I1_prompt.md`'s own Background section).
