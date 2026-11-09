# Native actor history queries

The native database retains settled tickets and idempotency records. A returning
player's last round, history, and spin count must stay scoped to that actor as
unrelated players' retained history grows.

`tickets_settled_history` is a non-unique index on
`tickets(actor,state,finished_at DESC)` with the predicate `state='settled'`.
It supports the existing last-round and history ordering and covers the
existing settled-ticket count. The actor's count still examines that actor's
settled entries; no cached counter or financial aggregate is introduced.

The settled-only predicate keeps this index out of active-ticket lookups.
Those retain the existing unique `one_open` index. The `one_open` and
`request_once` definitions and all native request queries are unchanged.
This patch does not optimize the separate global pending-recovery scan.

Startup adds the index with `IF NOT EXISTS` to new or already bound databases.
It does not rewrite outcomes, requests, sessions, identity bindings, or identity
guards. Index construction needs disk space and a startup write lock
proportional to retained settled tickets; include it in deployment headroom and
startup planning. Ordinary request opens do not rebuild it.

WAL and FULL synchronous durability, committed-intent-before-callback ordering,
status requests, replay handling, worker and callback limits, seed generation,
game configuration, and payout rules are unchanged. No runtime-capacity result
is asserted here.

## Validation

`python -m pytest -q tests/test_native_history_queries.py` exercises the actual
state and last-round dispatch paths using disposable data. The tests capture
their SQL, check real `EXPLAIN QUERY PLAN` output after unrelated history grows
from 1,000 to 10,000 tickets, and compare results against independent table
scans. They verify the active-ticket plan, returning-player history and count,
both unique guards, and repeatable startup migration preserving stored data,
identity rows, and trigger definitions. Assertions do not depend on elapsed-time
ratios. The provider workflow also runs the existing wallet, concurrency,
isolation, disaster-recovery, backup, and math suites.
