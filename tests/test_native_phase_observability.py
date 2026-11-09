"""Real AnyIO queue and SQLite boundaries; diagnostics never change finance."""
import json
import sqlite3
import threading
import time
import tracemalloc
import uuid
from pathlib import Path

import anyio
import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

import agency_runtime as native
import native_observability as metrics
from agency_runtime import app as native_app
from test_native_concurrency import wallet_server

GAME = 'mahjong-wild'
IS_UNO = False


@pytest.fixture(autouse=True)
def fresh_metrics(monkeypatch):
    monkeypatch.setattr(metrics, '_METRICS', metrics._PhaseMetrics())
    monkeypatch.setattr(metrics, '_TELEMETRY_FAILED', False)
    assert metrics._CURRENT.get() is None
    yield
    assert metrics._CURRENT.get() is None


def capture_call(operation, function):
    lease = metrics._METRICS.start(operation)
    try:
        return metrics._run_worker(lease, function, (), {})
    finally:
        metrics._finish_http(lease, metrics._clock(), False, False)


def sample():
    return metrics.phase_health()['native_phases']


async def wait_counts(limiter, borrowed, waiting):
    with anyio.fail_after(5):
        while True:
            observed = limiter.statistics()
            if (observed.borrowed_tokens, observed.tasks_waiting) == (borrowed, waiting):
                return
            await anyio.sleep(0.001)


def probe_app(function, *, base_http=True):
    app = FastAPI()
    if base_http:
        @app.middleware('http')
        async def headers(request, call_next):
            response = await call_next(request)
            response.headers['X-Phase-Test'] = 'preserved'
            return response

    @app.get('/one')
    @app.get('/two')
    async def endpoint(request: Request):
        return await metrics.run_observed(request, function, request.url.path)

    app.add_middleware(metrics.NativePhaseMiddleware, routes={
        ('GET', '/one'): 'state', ('GET', '/two'): 'pick1'})
    return app


def test_real_default_40_workers_five_queued_requests_and_context_isolation():
    release = threading.Event()
    calls = []
    def occupy():
        assert release.wait(10)
    def work(path):
        calls.append(path)
        label = 'callback_status' if path == '/one' else 'callback_settle'
        return metrics.phase_call(label, lambda: {'ok': True})

    async def scenario():
        limiter = anyio.to_thread.current_default_thread_limiter()
        assert limiter.total_tokens == 40
        responses = []
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=probe_app(work)),
                                     base_url='https://native.example') as client:
            async def get(path):
                responses.append(await client.get(path, headers={'Authorization': 'test-secret-not-for-metrics'}))
            async with anyio.create_task_group() as group:
                try:
                    for _ in range(40):
                        group.start_soon(anyio.to_thread.run_sync, occupy)
                    await wait_counts(limiter, 40, 0)
                    for path in ('/one', '/two', '/one', '/two', '/one'):
                        group.start_soon(get, path)
                    await wait_counts(limiter, 40, 5)
                    queued_at = time.perf_counter_ns()
                    assert not calls and sample()['active_captures'] == 5
                    # Controlled queue interval, not a fragile speed ratio.
                    await anyio.sleep(0.025)
                    released_at = time.perf_counter_ns()
                finally:
                    release.set()
            assert all(r.status_code == 200 and r.headers['X-Phase-Test'] == 'preserved' for r in responses)
            assert len(responses) == len(calls) == 5
            assert await anyio.to_thread.run_sync(metrics._CURRENT.get) is None
            assert (await metrics.thread_limiter_health())['anyio_thread_limiter']['total_tokens'] == 40
        result = sample()
        assert result['active_captures'] == 0 and result['completed_operations'] == 5
        operations = result['operations']
        assert operations['state']['phases']['callback_status']['invocations'] == 3
        assert 'callback_settle' not in operations['state']['phases']
        assert operations['pick1']['phases']['callback_settle']['invocations'] == 2
        assert 'callback_status' not in operations['pick1']['phases']
        dispatch_total = sum(row['phases']['dispatch_to_worker']['total_us'] for row in operations.values())
        assert dispatch_total >= 5 * ((released_at - queued_at) // 1000)
        assert 'test-secret-not-for-metrics' not in json.dumps(result)
    anyio.run(scenario)


@pytest.mark.parametrize('cancel_when', ['queued', 'running'])
def test_cancellation_preserves_default_worker_lifetime_and_releases_capture(cancel_when):
    release, entered = threading.Event(), threading.Event()
    calls = []
    def occupy():
        assert release.wait(10)
    def work(path):
        calls.append(path)
        entered.set()
        assert release.wait(10)
        return {'ok': True}
    async def scenario():
        limiter = anyio.to_thread.current_default_thread_limiter()
        scopes, ended = [], anyio.Event()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=probe_app(work, base_http=False)),
                                     base_url='https://native.example') as client:
            async def get():
                with anyio.CancelScope() as scope:
                    scopes.append(scope)
                    try:
                        await client.get('/one')
                    finally:
                        ended.set()
            async with anyio.create_task_group() as group:
                try:
                    if cancel_when == 'queued':
                        for _ in range(40):
                            group.start_soon(anyio.to_thread.run_sync, occupy)
                        await wait_counts(limiter, 40, 0)
                    group.start_soon(get)
                    if cancel_when == 'queued':
                        await wait_counts(limiter, 40, 1)
                    else:
                        with anyio.fail_after(5):
                            while not entered.is_set():
                                await anyio.sleep(0.001)
                    scopes[0].cancel()
                    if cancel_when == 'queued':
                        with anyio.fail_after(5):
                            await ended.wait()
                        assert not calls and sample()['active_captures'] == 0
                    else:
                        await anyio.sleep(0.01)
                        assert not ended.is_set(), 'default AnyIO worker must not be abandoned'
                        assert sample()['active_captures'] == 1
                finally:
                    release.set()
            assert len(calls) == (0 if cancel_when == 'queued' else 1)
            assert sample()['active_captures'] == 0
            assert sample()['completed_operations'] == 1
    anyio.run(scenario)


def test_stale_cancelled_lease_cannot_contaminate_reused_slot():
    old = metrics._METRICS.start('state')
    metrics._update(lambda c: setattr(c, 'worker_state', 'abandoned'), lease=old)
    metrics._finish_http(old, metrics._clock(), True, True)
    current = metrics._METRICS.start('pick1')
    assert current[0] == old[0] and current[1] != old[1]
    calls = []
    metrics._run_worker(old, lambda: calls.append('late-original-call'), (), {})
    assert calls == ['late-original-call']
    metrics._run_worker(current, lambda: metrics.phase_call('callback_status', lambda: None), (), {})
    metrics._finish_http(current, metrics._clock(), False, False)
    result = sample()
    assert result['completed_operations'] == 2 and result['active_captures'] == 0
    assert result['operations']['pick1']['phases']['callback_status']['invocations'] == 1
    assert 'callback_status' not in result['operations']['state']['phases']


def test_real_sqlite_explicit_empty_and_autocommit_boundaries(tmp_path):
    path = tmp_path / 'phase.sqlite'
    def work():
        db = sqlite3.connect(path, isolation_level=None)
        assert db.execute('PRAGMA journal_mode=WAL').fetchone()[0] == 'wal'
        db.execute('PRAGMA synchronous=FULL')
        db.execute('CREATE TABLE entries(id INTEGER PRIMARY KEY,value INTEGER)')
        metrics.begin_immediate(db)
        metrics.execute_write('autocommit_intent_execute', db, 'INSERT INTO entries VALUES(1,5)')
        metrics.commit_db(db)
        metrics.execute_write('autocommit_result_execute', db, 'UPDATE entries SET value=7 WHERE id=1')
        assert not db.in_transaction
        metrics.commit_db(db)
        metrics.begin_immediate(db)
        assert db.execute('SELECT value FROM entries').fetchone()[0] == 7
        metrics.commit_db(db)
        metrics.close_db(db)
    capture_call('replay_completed', work)
    result = sample()['operations']['replay_completed']
    counters = result['counters']
    assert counters['explicit_transactions_started'] == 2
    assert counters['explicit_transactions_with_dml'] == counters['explicit_transactions_zero_dml'] == 1
    assert counters['explicit_commit_active'] == 2 and counters['explicit_commit_noop'] == 1
    assert counters['dml_success'] == 2
    assert result['phases']['autocommit_result_execute']['invocations'] == 1
    assert result['phases']['explicit_dml_execute']['invocations'] == 1
    assert result['phases']['db_close']['invocations'] == 1
    db = sqlite3.connect(path)
    assert db.execute('SELECT value FROM entries').fetchone()[0] == 7
    db.close()


def test_clock_errors_saturation_unknown_labels_and_fixed_memory(monkeypatch):
    tracemalloc.start()
    before = tracemalloc.get_traced_memory()[0]
    registry = metrics._PhaseMetrics()
    allocated = tracemalloc.get_traced_memory()[0] - before
    tracemalloc.stop()
    assert allocated < 8 * 1024 * 1024
    monkeypatch.setattr(metrics, '_METRICS', registry)
    leases = [registry.start('state') for _ in range(metrics.CAPTURE_LIMIT)]
    assert all(leases) and registry.start('state') is None
    assert registry.start('secret-player-key') is None
    for lease in leases:
        metrics._finish_http(lease, metrics._clock(), False, False)
    assert sample()['active_captures'] == 0 and sample()['dropped_captures'] == 1
    def work():
        metrics.phase_call('secret-session-key', lambda: None)
        lease = metrics._CURRENT.get()
        def controlled(c):
            c.record(metrics._PHASE['history_read'], 5, 4)
            c.record(metrics._PHASE['history_read'], None, 6)
            c.record(metrics._PHASE['history_read'], 0, 61_000_000_000)
            c.add(c.counters, metrics._COUNTER['dml_success'], metrics.MAX_VALUE + 1)
        metrics._METRICS.update(lease, controlled)
    capture_call('pick1', work)
    result = sample()
    assert result['operations']['pick1']['counters']['invalid_clock'] == 2
    assert result['operations']['pick1']['phases']['history_read']['buckets'][-1] == 1
    assert result['saturated']
    assert 'secret-' not in json.dumps(result)
    for cell in registry.cells + registry.counts:
        for i in range(len(cell)):
            cell[i] = metrics.MAX_VALUE
    assert len(json.dumps(sample()).encode()) < 512 * 1024


def test_telemetry_faults_preserve_return_exception_cleanup_and_recovery_context(monkeypatch):
    def fail(*args):
        raise RuntimeError('synthetic telemetry fault')
    sentinel = object()
    with monkeypatch.context() as patch:
        patch.setattr(metrics._Capture, 'record', fail)
        assert capture_call('state', lambda: sentinel) is sentinel
        original = ValueError('original caller exception')
        def error():
            raise original
        with pytest.raises(ValueError) as caught:
            capture_call('state', error)
        assert caught.value is original
        assert sample()['active_captures'] == 0
        assert sample()['telemetry_error']
    with monkeypatch.context() as patch:
        patch.setattr(metrics._METRICS, '_merge', fail)
        assert capture_call('state', lambda: sentinel) is sentinel
        assert sample()['active_captures'] == 0
    with monkeypatch.context() as patch:
        patch.setattr(metrics._METRICS, 'snapshot', fail)
        assert metrics.phase_health()['native_phases']['available'] is False
    @metrics.recovery_operation
    def recovery():
        metrics.phase_call('callback_reserve', lambda: None)
    thread = threading.Thread(target=recovery)
    thread.start()
    thread.join(timeout=5)
    assert not thread.is_alive()
    result = sample()
    assert result['operations']['recovery']['phases']['callback_reserve']['invocations'] == 1
    assert metrics._CURRENT.get() is None


@pytest.fixture
def provider(tmp_path, monkeypatch):
    with wallet_server(GAME) as (origin, entered, release, rounds):
        database = 'UNO_AGENCY_DB_PATH' if IS_UNO else 'MAHJONG_AGENCY_DB_PATH'
        values = {'AGENCY_WALLET_MODE':'sandbox','AGENCY_ENVIRONMENT':'preproduction',
            'AGENCY_DEPLOYMENT_ID':'native-phase-test','AGENCY_CORE_DEPLOYMENT_ID':'core-concurrency-test',
            database:str(tmp_path/'native.sqlite'),'AGENCY_WALLET_ORIGIN':origin,
            'AGENCY_WALLET_KEY_ID':'test-engine','AGENCY_WALLET_SECRET':'q'*40,
            'AGENCY_WALLET_LOCAL_QA':'1','AGENCY_STUDIO_SYNC':'0','ENGINE_BACKUP_ENABLED':'false'}
        for name, value in values.items():
            monkeypatch.setenv(name, value)
        for name in ('ENGINE_RESTORE_OBJECT_KEY','ENGINE_RESTORE_OBJECT','ENGINE_RESTORE_CIPHERTEXT_SHA256'):
            monkeypatch.delenv(name, raising=False)
        headers = {'X-UNO-Client':'spin-ui'} if IS_UNO else {'X-ML-Request':'local-demo'}
        with TestClient(native_app) as client:
            launched = client.post('/api/agency/launch', headers=headers, json={'token':'f'*48})
            assert launched.status_code == 200, launched.text
            assert 'HttpOnly' in launched.headers['set-cookie'] and 'SameSite=strict' in launched.headers['set-cookie']
            yield client, headers, rounds, Path(values[database])


def play(client, headers):
    state_path = '/api/agency/state' if IS_UNO else '/api/state'
    state = client.get(state_path, headers=headers)
    assert state.status_code == 200
    if IS_UNO:
        result = None
        for phase in (1, 2, 3):
            payload = {'request_id':str(uuid.uuid4()),'stake':25,'expected_phase':phase,
                       'round_id':result['round']['id'] if result else None}
            response = client.post('/api/agency/pick', headers=headers, json=payload)
            assert response.status_code == 200, response.text
            result = response.json()
        return '/api/agency/pick', payload, result
    payload = {'ticket_id':state.json()['ticket']['id'],'idempotency_key':str(uuid.uuid4()),'bet':'1'}
    response = client.post('/api/spin', headers=headers, json=payload)
    assert response.status_code == 200, response.text
    return '/api/spin', payload, response.json()


def test_actual_native_round_completed_replay_and_sql_phase_counts(provider):
    client, headers, rounds, database = provider
    path, payload, result = play(client, headers)
    replay = client.post(path, headers=headers, json=payload)
    assert replay.status_code == 200, replay.text
    if IS_UNO:
        assert replay.json()['round'] == result['round'] and replay.json()['replayed']
    else:
        assert replay.json() == result
    assert len(rounds) == 1 and all(r['debits'] == r['credits'] == 1 for r in rounds.values())
    health = client.get('/health').json()
    observed = health['native_phases']
    assert observed['available'] and not observed['telemetry_error'] and not observed['saturated']
    assert observed['active_captures'] == 0 and observed['dropped_captures'] == 0
    replay_metrics = observed['operations']['replay_completed']
    assert replay_metrics['phases']['callback_status']['invocations'] == 1
    assert 'callback_reserve' not in replay_metrics['phases'] and 'callback_settle' not in replay_metrics['phases']
    assert replay_metrics['phases']['db_close']['invocations'] == 1
    assert replay_metrics['counters']['dml_success'] == 0
    if IS_UNO:
        assert replay_metrics['counters']['explicit_transactions_zero_dml'] == 1
        assert replay_metrics['counters']['explicit_commit_active'] == 1
        for operation, result_writes in (('pick1',1),('pick2',0),('pick3',1)):
            row = observed['operations'][operation]
            assert row['counters']['explicit_transactions_with_dml'] == 1
            assert row['counters']['explicit_commit_active'] == 1
            assert row['phases']['explicit_dml_execute']['invocations'] == 2
            assert row['phases'].get('autocommit_result_execute',{}).get('invocations',0) == result_writes
    else:
        row = observed['operations']['spin_new']
        assert row['counters']['explicit_transactions_started'] == 0
        assert row['counters']['explicit_commit_noop'] == 1
        assert row['phases']['autocommit_intent_execute']['invocations'] == 1
        assert row['phases']['autocommit_result_execute']['invocations'] == 2
        assert row['phases']['autocommit_ticket_execute']['invocations'] == 1
    db = native.db_open() if IS_UNO else native.connect()
    assert db.execute('PRAGMA journal_mode').fetchone()[0] == 'wal'
    assert db.execute('PRAGMA synchronous').fetchone()[0] == 2
    db.close()
    forbidden = [str(database), 'f'*48, 'q'*40, *client.cookies.values(), *rounds.keys()]
    exported = json.dumps(observed)
    assert all(value not in exported for value in forbidden)


def test_lost_reserve_and_settle_replay_survive_telemetry_exceptions(provider, monkeypatch):
    client, headers, rounds, database = provider
    original_wallet = native.wallet
    pending_failures = {'reserve', 'settle'}
    actions = []
    class LosingResponse:
        def request(self, action, payload):
            result = original_wallet().request(action, payload)
            actions.append(action)
            if action in pending_failures:
                pending_failures.remove(action)
                raise native.AgencyWalletError(503, 'synthetic-lost-committed-response')
            return result
    monkeypatch.setattr(native, 'wallet', LosingResponse)
    def telemetry_failure(*args):
        raise RuntimeError('synthetic-telemetry-failure')
    monkeypatch.setattr(metrics._Capture, 'record', telemetry_failure)
    state_path = '/api/agency/state' if IS_UNO else '/api/state'
    state = client.get(state_path, headers=headers)
    assert state.status_code == 200, state.text
    if IS_UNO:
        path = '/api/agency/pick'
        payload = {'request_id':str(uuid.uuid4()),'stake':25,'expected_phase':1,'round_id':None}
        assert client.post(path,headers=headers,json=payload).status_code == 503
        first = client.post(path,headers=headers,json=payload)
        assert first.status_code == 200 and first.json()['replayed']
        rid = first.json()['round']['id']
        for phase in (2,3):
            payload = {'request_id':str(uuid.uuid4()),'stake':25,'expected_phase':phase,'round_id':rid}
            response = client.post(path,headers=headers,json=payload)
            assert response.status_code == (200 if phase == 2 else 503), response.text
        final = client.post(path,headers=headers,json=payload)
    else:
        path = '/api/spin'
        payload = {'ticket_id':state.json()['ticket']['id'],'idempotency_key':str(uuid.uuid4()),'bet':'1'}
        assert client.post(path,headers=headers,json=payload).status_code == 503
        assert client.post(path,headers=headers,json=payload).status_code == 503
        final = client.post(path,headers=headers,json=payload)
    assert final.status_code == 200, final.text
    replay = client.post(path,headers=headers,json=payload)
    assert replay.status_code == 200
    assert replay.json()['round'] == final.json()['round']
    assert not pending_failures and actions.count('reserve') == actions.count('settle') == 2
    assert len(rounds) == 1 and all(r['debits'] == r['credits'] == 1 for r in rounds.values())
    assert sample()['active_captures'] == 0 and sample()['telemetry_error']
    assert client.get('/health').json()['pending_operation_locks'] == 0


def test_invalid_retry_releases_writer_and_keeps_completed_outcome(provider):
    client, headers, rounds, database = provider
    path, payload, original = play(client, headers)
    changed = dict(payload, expected_phase=2) if IS_UNO else dict(payload, bet='2')
    conflict = client.post(path, headers=headers, json=changed)
    assert conflict.status_code == 409, conflict.text
    replay = client.post(path, headers=headers, json=payload)
    assert replay.status_code == 200 and replay.json()['round'] == original['round']
    assert len(rounds) == 1 and all(r['debits'] == r['credits'] == 1 for r in rounds.values())
    observed = sample()
    assert observed['active_captures'] == 0
    if IS_UNO:
        rejected = observed['operations']['pick2']
        assert rejected['counters']['closed_transaction'] == 1
        assert rejected['counters']['explicit_transactions_zero_dml'] == 1
    else:
        rejected = observed['operations']['request_unclassified']
        assert rejected['counters']['dml_success'] == 0
    assert rejected['errors'] == 1
    assert client.get('/health').json()['pending_operation_locks'] == 0


def test_clock_failure_and_nesting_limit_never_skip_caller(monkeypatch):
    from contextlib import ExitStack
    from types import SimpleNamespace
    def fault():
        raise RuntimeError('synthetic clock fault')
    with monkeypatch.context() as patch:
        patch.setattr(metrics, 'time', SimpleNamespace(
            perf_counter_ns=fault, thread_time_ns=time.thread_time_ns))
        sentinel = object()
        assert capture_call('state', lambda: sentinel) is sentinel
        result = sample()
        assert result['active_captures'] == 0 and result['telemetry_error']
        assert result['operations']['state']['counters']['invalid_clock'] >= 2
        assert 'operation_total' not in result['operations']['state']['phases']
    def nested():
        with ExitStack() as stack:
            for _ in range(metrics.MAX_NESTING + 1):
                stack.enter_context(metrics.phase('history_read'))
    capture_call('pick1', nested)
    row = sample()['operations']['pick1']
    assert row['counters']['dropped_spans'] == 1
    assert row['phases']['history_read']['invocations'] == metrics.MAX_NESTING



