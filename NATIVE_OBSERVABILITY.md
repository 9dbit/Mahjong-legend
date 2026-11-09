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

## Focused validation

Run `python -m pytest -q tests/test_native_observability.py` in the repository.
The tests measure real CPU progress, allocate and unmap resident pages in a
disposable subprocess, and saturate the actual default limiter with 40 blocked
workers plus five waiting tasks. They call the real native `/health` route,
verify its pre-admission queue sample, then release the workers and verify zero
borrowed/waiting tokens. Identity mismatch still fails the request without
altering the bound database. Unavailable diagnostics serialize as explicit null.

## API references

- [Python resource usage](https://docs.python.org/3/library/resource.html)
- [Linux proc and current resident pages](https://docs.kernel.org/filesystems/proc.html)
- [AnyIO capacity-limiter statistics](https://anyio.readthedocs.io/en/stable/api.html#anyio.CapacityLimiterStatistics)
- [AnyIO default thread limiter](https://anyio.readthedocs.io/en/stable/api.html#anyio.to_thread.current_default_thread_limiter)
