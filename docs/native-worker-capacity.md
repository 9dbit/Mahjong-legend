# Native worker capacity

The serving application's startup reads `NATIVE_THREAD_TOKENS` once and sets
the existing default AnyIO thread limiter on that same event loop.

| Configuration | Effective tokens |
|---|---:|
| Variable absent | 40 |
| Exact string `40` | 40 |
| Exact string `80` | 80 |

All other values, including empty strings, surrounding whitespace and other
integers, fail startup with `NATIVE_THREAD_TOKENS_INVALID`. Validation occurs
before native database initialization and recovery or backup thread startup.
A configuration change requires a process restart.

This is the shared default limiter used by Starlette's existing synchronous
offload and synchronous routes. It is not a limit on all process threads:
background recovery and backup threads retain their existing behavior. The
`run_observed` wrapper, cancellation semantics, per-player locks, financial
state machine, commit-before-network ordering, SQLite FULL/WAL settings and
callback transport are unchanged. The callback pool remains bounded at 40.

## Readback and qualification

Use the existing `/health` field `anyio_thread_limiter.total_tokens` to observe
the actual serving-loop limit. The adjacent `borrowed_tokens` and
`tasks_waiting` fields are snapshots. For synchronous health, the async
dependency observes the pool before the health body waits for its own token.
No configuration value is substituted for this live limiter observation.

An 80-token cohort may overlap blocking work more effectively; it can also move
waiting into the callback pool or SQLite writer boundary. Compare complete,
closed telemetry intervals with stable source/boot identities, exact workload
counts, no telemetry loss and the same qualification profile, timeout, retry,
durability and resource gates. Preserve unsuccessful results. Returning to the
explicit 40-token setting and restarting provides the configuration rollback.

The base images and dependency requirements are unchanged. Record actual
dependency/image/source versions when comparing deployments; rebuilding a
floating image or transitive dependency does not establish runtime parity.
A successful configuration test or capacity result does not activate production
or substitute for release approvals.

## Verification

`tests/test_native_worker_limits.py` checks default/explicit limits through the
actual ASGI lifespan and health route, invalid startup before initialization or
threads, and 80 active worker calls with 5 additional calls queued on the same
limiter. Existing phase, cancellation, identity, replay and accounting tests
remain in the provider workflow. The production image probe additionally
requires a mounted startup to report 80 tokens with the callback pool still 40.

