# Native health diagnostics

`GET /health` includes three content-free diagnostic fields. Existing database,
deployment-identity, source, callback-transport, boot, and uptime checks remain.

| Field | Meaning | Unavailable value |
| --- | --- | --- |
| `cpu_usage_microseconds.user` | Cumulative user-mode CPU time for this process, including its threads | Parent field is `null` |
| `cpu_usage_microseconds.system` | Cumulative system-mode CPU time for this process, including its threads | Parent field is `null` |
| `memory_rss_bytes` | Current Linux resident-page counter multiplied by the operating-system page size | `null` |
| `anyio_thread_limiter.total_tokens` | Capacity of the serving event loop's actual default thread limiter | Parent field is `null` |
| `anyio_thread_limiter.borrowed_tokens` | Tokens borrowed at the sampling instant | Parent field is `null` |
| `anyio_thread_limiter.tasks_waiting` | Tasks waiting for that limiter at the sampling instant | Parent field is `null` |

CPU values come from `getrusage(RUSAGE_SELF)`. They are cumulative counters,
not percentages. Compare differences over a measured collection interval only
when `process_boot_id` matches. Background work in this process contributes.
RSS comes from a bounded 256-byte read of `/proc/self/statm`; `ru_maxrss` is
deliberately not used because it is a historical maximum. Linux updates these
resident-page counters asynchronously, so RSS is an approximate current sample.
No platform limit, percentage of quota, or container-wide total is inferred.

An async FastAPI dependency reads the default limiter before health-handler
worker admission. UNO's existing async health handler stays async. Mahjong's
existing synchronous handler keeps its database checks in the worker pool; its
response can therefore wait behind other worker tasks after the limiter sample
has been taken. CPU/RSS are sampled inside the handler. These fields need not
represent one simultaneous instant. A missed or delayed health response alone
does not identify CPU, disk, event-loop, or thread-pool saturation.

The dependency does not acquire a token, alter the default 40-token capacity,
change the 40-slot outbound callback pool, or wrap gameplay requests. Only the
three integer limiter counts are serialized; borrower/task objects, identities,
request data, URLs, headers, and credentials are excluded. Diagnostics have no
background sampler, retained samples, player labels, or unbounded output.

These samples help distinguish hypotheses during a capacity run. Platform
resource measurements and the existing qualification gates remain required.
This patch does not establish capacity, security, or certification approval.

## Phase-registry identity

The existing `native_phases` diagnostic includes `registry_id`, a UUID created
once per `_PhaseMetrics` collector, and `reset_count`, an integer that is zero
for that collector's lifetime. Repeated health reads, completed requests,
request-slot reuse, and recovery operations preserve that registry identity.
The aggregate counters have no in-place reset API. Clearing aggregate storage
must construct a new collector with a new `registry_id`; individual request
buffers are cleared on slot reuse without clearing the aggregate counters.
A fresh service process also constructs a fresh registry.

Qualification interval subtraction requires matching registry, process, source,
and deployment identities, `reset_count == 0` at both boundaries, and valid
quiescent snapshots. A replaced registry invalidates the interval even if its
counters have already grown beyond the earlier values. These fields do not
make snapshots from an earlier deployment comparable retroactively.

If snapshot collection fails, health retains that collector's registry identity
and reset count while reporting `available: false` and `telemetry_error: true`.
If UUID creation fails, the identity is `null` and telemetry reports an error;
business work still runs, while the qualification consumer rejects comparison.
Registry identity is content-free and does not contain a player, request,
wallet, or database identifier. Gameplay, RNG, wallet durability, and the
configured worker-token capacity are unchanged.

## Native admission partition

The Mahjong collector follows the deployed UNO admission observation at commit
`5a9c322b806d7add539052ccc70091235fc0d0d3`. It delegates to the serving event
loop's **existing default limiter** inside a single AnyIO offload. It does not
acquire a second token, create a separate limiter, add a checkpoint or shield,
change cancellation defaults, or retry a business callable. The configured
default remains 40 tokens. Synchronous functions and their keyword arguments
remain bound before offload, matching Starlette's `run_in_threadpool` semantics;
business keyword names such as `limiter` are not consumed by AnyIO.

| Fixed phase | Boundaries and interpretation |
| --- | --- |
| `dispatch_to_admission` | Recorded dispatch to the start of the backend's existing limiter acquisition. Includes the backend's preparation/checkpoint before acquisition. |
| `admission_wait` | Acquisition entry to its successful return. Includes waiting for capacity and the limiter's own await/checkpoint/wake-up; not a pure queue metric. |
| `admission_to_worker` | Successful acquisition return to observed worker entry. Includes telemetry recording, dispatch, thread creation/reuse, and scheduling; not an isolated OS scheduler metric. |
| `dispatch_to_worker` | Existing inclusive dispatch-to-worker interval, retained unchanged. |

For a successful observed dispatch, each of the three components has one
invocation. Their additive microsecond totals partition `dispatch_to_worker`
within rounding loss of at most two microseconds per dispatch. This relationship
applies to sums with matching operation/invocation populations, not to sums of
histogram percentiles. A cancelled or failed acquisition does not fabricate a
successful admission. Failure after admission but before worker entry can expose
the first two components without `admission_to_worker`; it is not a complete
partition. Background recovery runs directly on its existing thread and does
not acquire or report a request admission token.

AnyIO's asyncio/uvloop backend delegates context-manager acquisition/release;
its Trio backend delegates acquisition/release on behalf of its existing
borrower. Borrower identities are forwarded, never retained in metrics. Telemetry
setup failure falls back before executing the worker; recording failure after
admission still returns control to AnyIO so its normal release can run. No
telemetry fallback repeats a callable that already started. Existing capture
generation, cancellation cleanup, registry/reset and unavailable-snapshot guards
remain in force.

## Work performed while the worker is active

`worker_total` is inclusive wall time from observed worker entry through the
business callable's return or exception. `worker_cpu` uses the same thread's
CPU clock. Their difference is not a direct measurement of a particular wait:
it can include database, callbacks, locks, GIL contention and scheduling. Final
telemetry cleanup and backend token release occur after the observed worker end,
so this is not a complete token-holding-time measurement.

Two bounded phases fill existing attribution gaps:

- `ticket_read` measures each existing operational ticket `SELECT` through its
  `fetchone()` return. It covers reads in `get_ticket`, spin validation and round
  advancement, without changing SQL text, parameter values, query count, order,
  or returned row. Session/history/recovery-scan queries retain their existing
  labels. Query text, parameters and row contents are never exported.
- `manifest_prepare` wraps the existing manifest function: configuration JSON
  parsing, allowed-bet/scale checks, hashes and result construction. It does not
  change the manifest, call RNG, or alter the approved game sources.

The existing spans also matter when interpreting worker time:

| Phase | Containment and limitations |
| --- | --- |
| `db_open_total` | Includes path preparation, `open_bound_total`, and `connection_pragmas`; do not add these children to the parent. |
| `open_bound_total` | Includes the existing read-only binding precheck and subsequent read/write open and binding verification. No connection or identity check is removed. |
| `session_validation` | Includes cookie/session lookup, JSON parsing and redeemed-session validation. |
| `player_lock_acquire`, `round_lock_acquire` | Acquisition only, possibly multiple invocations for reentrant calls in one operation. |
| `autocommit_intent_execute` | Existing outcome/intent write remains durable before a wallet callback. Parameter preparation and JSON serialization before `execute_write` are outside this span. |
| `autocommit_result_execute` | A new successful spin normally invokes it twice: reserved result, then settled result. The histogram is the sum per operation. |
| `autocommit_ticket_execute` | Existing ticket insert/expiry writes, including a next ticket created during state assembly; seed/config preparation before SQL execution is outside this span. |
| `local_prepare` | Existing game calculation and amount preparation; approved RNG/math and their invocation order are unchanged. |
| `callback_status`, `callback_reserve`, `callback_settle` | Include wallet-client preparation, signing, transport and response handling. These are not pure network timings. |
| `response_assembly_inclusive` | The complete existing `state()` call, including its ticket/manifest work, status callback and history queries. A spin/replay calls it while building its response. |
| `history_read`, `db_close` | Existing history SQL and connection close respectively; a close may also perform SQLite work. |

In the bounded normal-round fixture, a new spin records eight `ticket_read`
invocations and four `manifest_prepare` invocations. A completed replay records
five and three respectively. These are fixture expectations, not universal
counts for expiry, rejection, pending recovery or failure paths. Repeated
manifest construction is observed as it exists; this patch does not remove it.
The new spans overlap their containing state/worker spans. Summing every phase
would double-count time. Uninstrumented preparation, serialization, Python work
and telemetry overhead still exist; no complete exclusive worker partition is
claimed.

The phase-label set is fixed. The existing 1,024 capture slots, bounded arrays,
nesting limit, counters and histogram buckets remain. No per-request samples or
dynamic labels are added. Registry identity must match across valid quiescent
before/after boundaries, with the same source, deployment, process and reset
identity. A rollout starts a fresh registry; old and new phase totals are not a
before/after performance experiment.

### Source and rollout scope

This candidate starts from deployed Mahjong commit
`1740a12a3a3cc845990b1df1d41a9a69cb8bc8f2`. It changes telemetry, its call-site
wrappers, tests, documentation and the exact CI branch trigger
`feat/mahjong-admission-20261110`. Production requirements, 40-token configuration,
callback pool size, SQLite pragmas, queries, durable ordering, wallet protocol,
RNG, UI and approved source-lock inputs are unchanged. Trio `0.35.0` is a test
dependency for the alternate AnyIO delegation path; it is not added to the
production requirements or image. Publication, deployment, load and soak are
separate gated steps; local tests do not establish a latency improvement.

## Focused validation

Run `python -m pytest -q tests/test_native_observability.py` in the repository.
The tests measure real CPU progress, allocate and unmap resident pages in a
disposable subprocess, and saturate the actual default limiter with 40 blocked
workers plus five waiting tasks. They call the real native `/health` route,
verify its pre-admission queue sample, then release the workers and verify zero
borrowed/waiting tokens. Identity mismatch still fails the request without
altering the bound database. Unavailable diagnostics serialize as explicit null.

Run `python -m pytest -q tests/test_native_phase_observability.py` for the phase
collector. Identity tests verify request-slot reuse, collector replacement,
fresh subprocesses, entropy failure, and snapshot failure. The real native
health/round/replay test verifies identity continuity alongside exactly one
debit and one credit for the round.

The admission tests use the real 40-token default limiter on asyncio, uvloop
and Trio: 40 occupied workers plus five queued requests, cancellation while
queued/admitted/running, a controlled delay after admission, and execution with
only one default token remaining. They verify context propagation, original
return/exception identity, no duplicate calls, cleanup and response headers.
Telemetry lookup/setup/recording/clock failures are injected without leaking
tokens. Asyncio/uvloop also exercise failure to start a worker thread. Install
the CI test dependencies, including `trio==0.35.0`, to run all backend cases.
The ticket-read probe verifies execute/fetch boundaries and original exception
identity without retaining query content. Actual round/replay tests verify the
new phase counts, unchanged SQL durability and exactly-once wallet movement.
Existing fixed-memory and worst-case health-response bounds remain enforced.

## API references

- [Python resource usage](https://docs.python.org/3/library/resource.html)
- [Linux proc and current resident pages](https://docs.kernel.org/filesystems/proc.html)
- [AnyIO capacity-limiter statistics](https://anyio.readthedocs.io/en/stable/api.html#anyio.CapacityLimiterStatistics)
- [AnyIO default thread limiter](https://anyio.readthedocs.io/en/stable/api.html#anyio.to_thread.current_default_thread_limiter)
