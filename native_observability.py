"""Bounded, content-free process and AnyIO diagnostics for native health.

These process-local samples do not replace platform resource-gate evidence.
No request, player, borrower, environment, or credential values are returned.
"""
import math
import os
import sys
import threading
import time
from array import array
from contextvars import ContextVar
from functools import partial, wraps
from uuid import uuid4

from starlette.concurrency import run_in_threadpool

from anyio.to_thread import current_default_thread_limiter, run_sync

try:
    import resource
except ImportError:  # Explicitly unavailable on platforms without getrusage.
    resource = None


def _cpu_usage_microseconds():
    if resource is None:
        return None
    try:
        usage = resource.getrusage(resource.RUSAGE_SELF)
        values = (usage.ru_utime, usage.ru_stime)
        if not all(math.isfinite(value) and value >= 0 for value in values):
            return None
        return {'user': int(values[0] * 1_000_000),
                'system': int(values[1] * 1_000_000)}
    except (AttributeError, OSError, TypeError, ValueError, OverflowError):
        return None


def _memory_rss_bytes():
    # ru_maxrss is a historical peak, not current RSS. Linux statm reports
    # current resident pages; its kernel counters are diagnostic estimates.
    if not sys.platform.startswith('linux'):
        return None
    try:
        with open('/proc/self/statm', 'rb') as statm:
            resident_pages = int(statm.read(256).split()[1])
        page_size = os.sysconf('SC_PAGE_SIZE')
        if resident_pages < 0 or page_size <= 0:
            return None
        return resident_pages * page_size
    except (AttributeError, OSError, IndexError, TypeError, ValueError):
        return None


def process_health():
    """Cumulative CPU for this process and current Linux RSS, or explicit null."""
    return {'cpu_usage_microseconds': _cpu_usage_microseconds(),
            'memory_rss_bytes': _memory_rss_bytes()}


async def thread_limiter_health():
    """Sample the serving event loop's default limiter without acquiring it.

    Used as an async health dependency so a synchronous health handler can
    include a real queue snapshot taken before its own worker admission.
    Never serialize CapacityLimiterStatistics.borrowers (task identities).
    """
    try:
        stats = current_default_thread_limiter().statistics()
        values = (stats.total_tokens, stats.borrowed_tokens, stats.tasks_waiting)
        if not all(isinstance(value, (int, float)) and not isinstance(value, bool)
                   and math.isfinite(value) and value >= 0 and int(value) == value
                   for value in values):
            return {'anyio_thread_limiter': None}
        sample = dict(zip(('total_tokens', 'borrowed_tokens', 'tasks_waiting'),
                          map(int, values)))
    except (AttributeError, OSError, RuntimeError, TypeError, ValueError, OverflowError):
        sample = None
    return {'anyio_thread_limiter': sample}


# Fixed process-local storage. No SQL, payload, actor, URL, cookie, exception
# text, task identity, or per-request sample is retained or exported.
PHASE_SCHEMA = 1
CAPTURE_LIMIT = 1024
MAX_VALUE = (1 << 53) - 1
MAX_NESTING = 8
BUCKET_UPPER_US = (250, 500, 1000, 2000, 4000, 8000, 16000, 32000,
                   64000, 128000, 256000, 512000, 1000000, 2000000,
                   4000000, 8000000, 16000000, 30000000, 60000000, None)
OPERATIONS = ('state', 'pick1', 'pick2', 'pick3', 'replay_completed',
              'replay_pending', 'replay_failed', 'spin_new', 'spin_resume',
              'request_unclassified', 'request_rejected', 'recovery')
PHASES = ('arrival_to_dispatch', 'dispatch_to_worker', 'worker_total',
          'worker_cpu', 'worker_to_response_complete', 'operation_total',
          'db_open_total', 'open_bound_total', 'connection_pragmas',
          'session_validation', 'player_lock_acquire', 'round_lock_acquire',
          'begin_immediate_wall', 'explicit_tx_body', 'explicit_commit_wall',
          'noop_commit_wall', 'explicit_dml_execute',
          'autocommit_intent_execute', 'autocommit_result_execute',
          'autocommit_ticket_execute', 'autocommit_failure_execute',
          'history_read', 'local_prepare', 'callback_status',
          'callback_reserve', 'callback_settle',
          'response_assembly_inclusive', 'db_close', 'recovery_scan',
          'explicit_rollback', 'dispatch_to_admission', 'admission_wait',
          'admission_to_worker', 'ticket_read', 'manifest_prepare')
COUNTERS = ('explicit_transactions_started', 'explicit_transactions_zero_dml',
            'explicit_transactions_with_dml', 'explicit_commit_active',
            'explicit_commit_noop', 'explicit_commit_failed',
            'closed_transaction', 'dml_success', 'dml_failure',
            'invalid_clock', 'dropped_spans')
_OP = {name: i for i, name in enumerate(OPERATIONS)}
_PHASE = {name: i for i, name in enumerate(PHASES)}
_COUNTER = {name: i for i, name in enumerate(COUNTERS)}
CALLBACK_PHASES = {'status': 'callback_status', 'reserve': 'callback_reserve',
                   'settle': 'callback_settle'}
_SCOPE_KEY = 'softtech.native_phase_lease'
_CURRENT = ContextVar('native_phase_lease', default=None)
_USE_CURRENT = object()
_TELEMETRY_FAILED = False


def _safe(function, *args):
    """Only telemetry runs here; the financial callable is never retried."""
    global _TELEMETRY_FAILED
    try:
        return function(*args)
    except Exception:
        _TELEMETRY_FAILED = True
        return None


def _clock():
    return _safe(time.perf_counter_ns)


def _cpu_clock():
    return _safe(time.thread_time_ns)


def _elapsed(start, end):
    if type(start) is not int or type(end) is not int or start < 0 or end < start:
        return None
    return (end - start) // 1000


class _Capture:
    __slots__ = ('lock', 'generation', 'finished', 'operation', 'arrival',
                 'dispatch', 'admitted', 'worker_end', 'worker_state', 'http_done',
                 'error', 'aborted', 'depth', 'tx_start', 'tx_dml',
                 'calls', 'totals', 'maxima', 'counters', 'saturated')

    def __init__(self):
        self.lock = threading.Lock()
        self.generation = 0
        self.finished = True
        self.calls = array('Q', [0]) * len(PHASES)
        self.totals = array('Q', [0]) * len(PHASES)
        self.maxima = array('Q', [0]) * len(PHASES)
        self.counters = array('Q', [0]) * len(COUNTERS)

    def reset(self, generation, operation, arrival):
        self.generation, self.operation, self.arrival = generation, operation, arrival
        self.finished = self.http_done = self.error = self.aborted = self.saturated = False
        self.dispatch = self.admitted = self.worker_end = self.tx_start = None
        self.worker_state, self.depth, self.tx_dml = 'none', 0, 0
        for values in (self.calls, self.totals, self.maxima, self.counters):
            for i in range(len(values)):
                values[i] = 0

    def add(self, values, index, amount=1):
        value = values[index] + amount
        if value > MAX_VALUE:
            self.saturated = True
        values[index] = min(value, MAX_VALUE)

    def record(self, phase, start, end):
        elapsed = _elapsed(start, end)
        if elapsed is None:
            self.add(self.counters, _COUNTER['invalid_clock'])
            return
        self.add(self.calls, phase)
        self.add(self.totals, phase, elapsed)
        self.maxima[phase] = min(MAX_VALUE, max(self.maxima[phase], elapsed))
        self.saturated |= elapsed > MAX_VALUE


class _PhaseMetrics:
    def __init__(self):
        # Aggregate counters never reset in place: clearing their storage must
        # construct a new registry and identity. reset_count stays zero for this
        # registry's lifetime; reusing an individual request slot is not a reset.
        self.registry_id = _safe(lambda: str(uuid4()))
        self.lock = threading.Lock()
        self.slots = [_Capture() for _ in range(CAPTURE_LIMIT)]
        self.free = list(range(CAPTURE_LIMIT))
        self.generation = self.active = self.completed = self.dropped = 0
        self.saturated = False
        # requests, invocations, total_us, max_request_us, max_invocation_us,
        # followed by fixed histogram buckets of per-operation phase sums.
        self.cells = [array('Q', [0]) * (5 + len(BUCKET_UPPER_US))
                      for _ in range(len(OPERATIONS) * len(PHASES))]
        self.counts = [array('Q', [0]) * (3 + len(COUNTERS)) for _ in OPERATIONS]

    def start(self, operation):
        operation = _OP.get(operation)
        if operation is None:
            return None
        with self.lock:
            if not self.free or self.generation == MAX_VALUE:
                self.dropped = min(MAX_VALUE, self.dropped + 1)
                self.saturated |= self.generation == MAX_VALUE or self.dropped == MAX_VALUE
                return None
            index = self.free.pop()
            self.generation += 1
            generation = self.generation
            self.active += 1
        capture = self.slots[index]
        with capture.lock:
            capture.reset(generation, operation, _clock())
        return (index, generation)

    def capture(self, lease):
        if (not isinstance(lease, tuple) or len(lease) != 2
                or type(lease[0]) is not int or not 0 <= lease[0] < CAPTURE_LIMIT):
            return None
        return self.slots[lease[0]]

    @staticmethod
    def valid(capture, lease):
        return capture.generation == lease[1] and not capture.finished

    def update(self, lease, function, *args):
        capture = self.capture(lease)
        if capture is not None:
            with capture.lock:
                if self.valid(capture, lease):
                    return function(capture, *args)
        return None

    def finish_if_ready(self, lease):
        capture = self.capture(lease)
        if capture is None:
            return
        with capture.lock:
            if (not self.valid(capture, lease) or not capture.http_done
                    or capture.worker_state in ('queued', 'running')):
                return
            capture.finished = True
        # No native lock, SQLite operation, network operation, or await is
        # inside this lock. A finalization fault still releases the slot.
        with self.lock:
            try:
                self._merge(capture)
            finally:
                self.active -= 1
                self.free.append(lease[0])

    def _add(self, values, index, amount):
        value = values[index] + amount
        self.saturated |= value > MAX_VALUE
        values[index] = min(MAX_VALUE, value)

    def _merge(self, capture):
        self.completed = min(MAX_VALUE, self.completed + 1)
        self.saturated |= capture.saturated or self.completed == MAX_VALUE
        counts = self.counts[capture.operation]
        for i, value in enumerate((1, int(capture.error), int(capture.aborted), *capture.counters)):
            self._add(counts, i, value)
        for phase, invocations in enumerate(capture.calls):
            if not invocations:
                continue
            cell = self.cells[capture.operation * len(PHASES) + phase]
            duration = capture.totals[phase]
            for i, value in enumerate((1, invocations, duration)):
                self._add(cell, i, value)
            cell[3] = max(cell[3], duration)
            cell[4] = max(cell[4], capture.maxima[phase])
            bucket = next(i for i, upper in enumerate(BUCKET_UPPER_US)
                          if upper is None or duration <= upper)
            self._add(cell, 5 + bucket, 1)

    def snapshot(self):
        with self.lock:
            summary = dict(active_captures=self.active, completed_operations=self.completed,
                           dropped_captures=self.dropped, saturated=self.saturated)
            cells = [tuple(cell) for cell in self.cells]
            counts = [tuple(row) for row in self.counts]
        operations = {}
        for operation, name in enumerate(OPERATIONS):
            count = counts[operation]
            if not count[0]:
                continue
            phases = {}
            for phase, label in enumerate(PHASES):
                values = cells[operation * len(PHASES) + phase]
                if values[0]:
                    phases[label] = dict(zip(('operations', 'invocations', 'total_us',
                        'max_operation_us', 'max_invocation_us'), values[:5]))
                    phases[label]['buckets'] = list(values[5:])
            operations[name] = {'completed': count[0], 'errors': count[1], 'aborted': count[2],
                                'counters': dict(zip(COUNTERS, count[3:])), 'phases': phases}
        return {'schema': PHASE_SCHEMA, 'available': True,
                'registry_id': self.registry_id, 'reset_count': 0,
                'capture_limit': CAPTURE_LIMIT,
                'telemetry_error': _TELEMETRY_FAILED, 'unit': 'microseconds',
                'histogram': 'per_operation_phase_sum', 'bucket_upper_us': BUCKET_UPPER_US,
                **summary, 'operations': operations}


_METRICS = _PhaseMetrics()


def phase_health():
    registry = _METRICS
    sample = _safe(registry.snapshot)
    return {'native_phases': sample if sample is not None else {
        'schema': PHASE_SCHEMA, 'available': False,
        'registry_id': registry.registry_id, 'reset_count': 0,
        'telemetry_error': True}}


def _update(function, *args, lease=_USE_CURRENT):
    if lease is _USE_CURRENT:
        lease = _safe(_CURRENT.get)
    return _safe(_METRICS.update, lease, function, *args)


def classify_operation(operation):
    index = _OP.get(operation)
    if index is not None:
        _update(lambda capture: setattr(capture, 'operation', index))


def classify_replay_state(state, completed=False):
    # Invoked only after the existing round read; no diagnostic SQL query.
    def classify(capture):
        if capture.operation == _OP['replay_pending']:
            if state == 'failed':
                capture.operation = _OP['replay_failed']
            elif completed:
                capture.operation = _OP['replay_completed']
    _update(classify)


class phase:
    """Bounded inclusive wall span; exceptions from the body remain unchanged."""
    __slots__ = ('label', 'lease', 'start', 'enabled')

    def __init__(self, label):
        self.label = _PHASE.get(label)
        self.lease = self.start = None
        self.enabled = False

    def __enter__(self):
        if self.label is None:
            return self
        self.lease = _safe(_CURRENT.get)
        def enter(capture):
            if capture.depth >= MAX_NESTING:
                capture.add(capture.counters, _COUNTER['dropped_spans'])
                return False
            capture.depth += 1
            return True
        self.enabled = bool(_update(enter, lease=self.lease))
        if self.enabled:
            self.start = _clock()
        return self

    def __exit__(self, *exception):
        if self.enabled:
            end = _clock()
            def leave(capture):
                capture.depth -= 1
                capture.record(self.label, self.start, end)
            _update(leave, lease=self.lease)
        return False


def phase_call(label, function, *args, **kwargs):
    with phase(label):
        return function(*args, **kwargs)


def measured(label):
    def decorate(function):
        @wraps(function)
        def wrapped(*args, **kwargs):
            return phase_call(label, function, *args, **kwargs)
        return wrapped
    return decorate


class measured_lock:
    def __init__(self, label, manager):
        self.label, self.manager = label, manager

    def __enter__(self):
        return phase_call(self.label, self.manager.__enter__)

    def __exit__(self, *exception):
        return self.manager.__exit__(*exception)


def _counter(label, amount=1):
    index = _COUNTER[label]
    _update(lambda capture: capture.add(capture.counters, index, amount))


def begin_immediate(db):
    result = phase_call('begin_immediate_wall', db.execute, 'BEGIN IMMEDIATE')
    ended = _clock()
    def started(capture):
        capture.tx_start, capture.tx_dml = ended, 0
        capture.add(capture.counters, _COUNTER['explicit_transactions_started'])
    _update(started)
    return result


def _end_transaction_body():
    ended = _clock()
    def end(capture):
        if capture.tx_start is not None:
            _safe(capture.record, _PHASE['explicit_tx_body'], capture.tx_start, ended)
            label = 'explicit_transactions_with_dml' if capture.tx_dml else 'explicit_transactions_zero_dml'
            capture.add(capture.counters, _COUNTER[label])
            capture.tx_start = None
    _update(end)


def commit_db(db):
    active = _safe(lambda: db.in_transaction)
    _end_transaction_body()
    _counter('explicit_commit_active' if active else 'explicit_commit_noop')
    try:
        return phase_call('explicit_commit_wall' if active else 'noop_commit_wall', db.commit)
    except BaseException:
        _counter('explicit_commit_failed')
        raise


def execute_write(label, db, sql, parameters=()):
    active = _safe(lambda: db.in_transaction)
    try:
        result = phase_call('explicit_dml_execute' if active else label, db.execute, sql, parameters)
    except BaseException:
        _counter('dml_failure')
        raise
    def success(capture):
        capture.add(capture.counters, _COUNTER['dml_success'])
        if active and capture.tx_start is not None:
            capture.tx_dml = min(MAX_VALUE, capture.tx_dml + 1)
    _update(success)
    return result


def close_db(db):
    if _safe(lambda: db.in_transaction):
        _counter('closed_transaction')
        _end_transaction_body()
    return phase_call('db_close', db.close)


class _ObservedThreadLimiter:
    """Observe one acquisition on the serving loop's unchanged default limiter.

    AnyIO's asyncio backend uses the context manager; its Trio backend uses
    acquire/release_on_behalf_of. Each entry point delegates exactly once, with
    no extra await/checkpoint, shield, capacity change, or financial retry.
    Borrower identities are forwarded only, never stored in telemetry.
    """
    __slots__ = ('_limiter', '_lease')

    def __init__(self, limiter, lease):
        self._limiter, self._lease = limiter, lease

    def __getattr__(self, name):
        return getattr(self._limiter, name)

    def _record_admission(self, started, admitted):
        def record(capture):
            capture.admitted = admitted
            _safe(capture.record, _PHASE['dispatch_to_admission'], capture.dispatch, started)
            _safe(capture.record, _PHASE['admission_wait'], started, admitted)
        _update(record, lease=self._lease)

    async def _acquire(self, acquire, *args):
        started = _clock()
        result = await acquire(*args)
        admitted = _clock()
        # No telemetry exception may escape after a real token was acquired.
        # A cancelled/failed acquisition is not a successful admission sample.
        _safe(self._record_admission, started, admitted)
        return result

    async def __aenter__(self):
        return await self._acquire(self._limiter.__aenter__)

    async def __aexit__(self, *exception):
        return await self._limiter.__aexit__(*exception)

    async def acquire(self):
        return await self._acquire(self._limiter.acquire)

    async def acquire_on_behalf_of(self, borrower):
        return await self._acquire(self._limiter.acquire_on_behalf_of, borrower)


def _run_worker(lease, function, args, kwargs):
    began, cpu_began = _clock(), _cpu_clock()
    def claim(capture):
        if capture.worker_state not in ('queued', 'none'):
            return False
        capture.worker_state = 'running'
        if capture.dispatch is not None:
            _safe(capture.record, _PHASE['dispatch_to_worker'], capture.dispatch, began)
        if capture.admitted is not None:
            _safe(capture.record, _PHASE['admission_to_worker'], capture.admitted, began)
        return True
    claimed = _update(claim, lease=lease)
    token = _safe(_CURRENT.set, lease if claimed else None)
    failed = False
    try:
        return function(*args, **kwargs)
    except BaseException:
        failed = True
        raise
    finally:
        ended, cpu_ended = _clock(), _cpu_clock()
        if claimed:
            def finished(capture):
                capture.worker_end, capture.worker_state = ended, 'finished'
                capture.error |= failed
                _safe(capture.record, _PHASE['worker_total'], began, ended)
                _safe(capture.record, _PHASE['worker_cpu'], cpu_began, cpu_ended)
            _update(finished, lease=lease)
        if token is not None:
            _safe(_CURRENT.reset, token)
        _safe(_METRICS.finish_if_ready, lease)


async def run_observed(request, function, *args, **kwargs):
    """One AnyIO offload, observing its existing default limiter acquisition.

    Admission wall time includes the limiter's own await/checkpoint and wake-up.
    Admission-to-worker includes worker dispatch/start/scheduling and telemetry
    overhead; it is not an isolated OS scheduler measurement.
    """
    lease = _safe(request.scope.get, _SCOPE_KEY)
    if lease is None:
        return await run_in_threadpool(function, *args, **kwargs)
    dispatched = _clock()
    def queued(capture):
        capture.dispatch, capture.worker_state = dispatched, 'queued'
        capture.admitted = None
        capture.record(_PHASE['arrival_to_dispatch'], capture.arrival, dispatched)
    _update(queued, lease=lease)
    try:
        limiter = _safe(lambda: _ObservedThreadLimiter(current_default_thread_limiter(), lease))
        if limiter is None:
            # Setup failure falls back before execution; never retry a worker.
            return await run_in_threadpool(_run_worker, lease, function, args, kwargs)
        # Match Starlette's partial binding and AnyIO's cancellation defaults.
        # The delegate wraps the SAME limiter; do not acquire it around run_sync.
        return await run_sync(partial(_run_worker, lease, function, args, kwargs), limiter=limiter)
    finally:
        # A cancellation before entry must not keep a slot forever. A late
        # queued wrapper executes the original callable without metrics; its
        # stale generation can never affect a newly reused capture slot.
        def abandon_pending(capture):
            if capture.worker_state == 'queued':
                capture.worker_state = 'abandoned'
        _update(abandon_pending, lease=lease)
        _safe(_METRICS.finish_if_ready, lease)


def recovery_operation(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        lease = _safe(_METRICS.start, 'recovery')
        try:
            return _run_worker(lease, function, args, kwargs)
        finally:
            _finish_http(lease, _clock(), False, False)
    return wrapped


def _finish_http(lease, ended, error, aborted):
    def finish(capture):
        if capture.http_done:
            return
        capture.http_done, capture.error, capture.aborted = True, capture.error or error, aborted
        _safe(capture.record, _PHASE['operation_total'], capture.arrival, ended)
        if capture.worker_end is not None and not aborted:
            _safe(capture.record, _PHASE['worker_to_response_complete'], capture.worker_end, ended)
        if capture.worker_state == 'none' and error:
            capture.operation = _OP['request_rejected']
    _update(finish, lease=lease)
    _safe(_METRICS.finish_if_ready, lease)


class NativePhaseMiddleware:
    """Pure ASGI: explicit scope lease survives BaseHTTP task boundaries."""
    def __init__(self, app, routes):
        self.app = app
        # Only caller-declared fixed routes; no dynamic metric cardinality.
        self.routes = dict(routes)

    async def __call__(self, scope, receive, send):
        operation = self.routes.get((scope.get('method'), scope.get('path')))
        if scope.get('type') != 'http' or operation is None:
            return await self.app(scope, receive, send)
        lease = _safe(_METRICS.start, operation)
        if lease is None:
            return await self.app(scope, receive, send)
        scoped = dict(scope)
        scoped[_SCOPE_KEY] = lease
        ended, error = None, False
        async def observed_send(message):
            nonlocal ended, error
            if message['type'] == 'http.response.start':
                error = message['status'] >= 400
            await send(message)
            if message['type'] == 'http.response.body' and not message.get('more_body', False):
                ended = _clock()
        try:
            return await self.app(scoped, receive, observed_send)
        except BaseException:
            error = True
            raise
        finally:
            _finish_http(lease, ended if ended is not None else _clock(), error, ended is None)
