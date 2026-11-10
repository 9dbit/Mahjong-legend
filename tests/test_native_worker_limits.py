"""Bounded startup configuration using the real serving loop and HTTP health."""
import threading

import anyio
import httpx
import pytest
from starlette.concurrency import run_in_threadpool

import agency_runtime as native
import native_observability as metrics
import native_worker_limits as config
from agency_wallet import close_transport

entrypoint = native
DB_VARIABLE = 'MAHJONG_AGENCY_DB_PATH'
GAME_ID = 'mahjong-wild'
INITIALIZER = 'init'

ENV_NAME = 'NATIVE_THREAD_TOKENS'


@pytest.fixture
def configured_native(tmp_path, monkeypatch):
    path = tmp_path / 'native.sqlite'
    for name in ('RAILWAY_PROJECT_ID', 'RAILWAY_SERVICE_ID', 'RAILWAY_DEPLOYMENT_ID',
                 'RAILWAY_VOLUME_MOUNT_PATH', 'ENGINE_RESTORE_OBJECT_KEY',
                 'ENGINE_RESTORE_OBJECT', 'ENGINE_RESTORE_CIPHERTEXT_SHA256', ENV_NAME):
        monkeypatch.delenv(name, raising=False)
    values = {
        'AGENCY_WALLET_MODE': 'sandbox', 'AGENCY_ENVIRONMENT': 'preproduction',
        'AGENCY_DEPLOYMENT_ID': 'native-worker-fixture',
        'AGENCY_CORE_DEPLOYMENT_ID': 'core-worker-fixture',
        DB_VARIABLE: str(path), 'AGENCY_WALLET_ORIGIN': 'https://core.example.invalid',
        'AGENCY_WALLET_KEY_ID': 'synthetic-worker-key',
        'AGENCY_WALLET_SECRET': 'synthetic-worker-secret-never-for-use',
        'ENGINE_BACKUP_ENABLED': 'false', 'AGENCY_STUDIO_SYNC': '0',
        'RAILWAY_GIT_COMMIT_SHA': 'a' * 40,
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    try:
        yield entrypoint.app, path
    finally:
        close_transport()


@pytest.mark.parametrize('value', [
    '', '0', '39', '41', '79', '81', '1000000', ' 80', '80 ', '80.0',
    '+80', '040', 'true', None, 80, True, 'synthetic-private-config-value',
])
def test_invalid_value_rejected_before_limiter_access(value, monkeypatch):
    def forbidden():
        raise AssertionError('invalid config must not access or modify a limiter')
    monkeypatch.setattr(config, 'current_default_thread_limiter', forbidden)
    with pytest.raises(RuntimeError) as caught:
        config.configure_native_worker_limit({ENV_NAME: value})
    assert str(caught.value) == 'NATIVE_THREAD_TOKENS_INVALID'


@pytest.mark.parametrize('value,expected', [(None, 40), ('40', 40), ('80', 80)])
def test_actual_startup_and_http_health_use_the_serving_loop_limiter(
        configured_native, monkeypatch, value, expected):
    app, path = configured_native
    if value is not None:
        monkeypatch.setenv(ENV_NAME, value)

    async def scenario():
        limiter = anyio.to_thread.current_default_thread_limiter()
        # A different initial value proves startup configures this same limiter,
        # instead of reporting a configuration value or using an unused pool.
        limiter.total_tokens = 7
        async with app.router.lifespan_context(app):
            assert anyio.to_thread.current_default_thread_limiter() is limiter
            assert limiter.total_tokens == expected
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                         base_url='https://native.example') as client:
                response = await client.get('/health')
                assert response.status_code == 200
                health = response.json()
                assert health['ok'] and health['database'] == 'connected'
                assert health['deployment_identity']['game_id'] == GAME_ID
                assert health['anyio_thread_limiter']['total_tokens'] == expected
                assert health['callback_transport']['pool_limit'] == 40
                assert set(health['anyio_thread_limiter']) == {
                    'total_tokens', 'borrowed_tokens', 'tasks_waiting'}
                assert health['native_phases']['active_captures'] == 0
                assert not health['native_phases']['telemetry_error']
                # This setting applies at startup; health reports the live
                # limiter even if a later environment value differs.
                monkeypatch.setenv(ENV_NAME, '40' if expected == 80 else '80')
                again = await client.get('/health')
                assert again.json()['anyio_thread_limiter']['total_tokens'] == expected
        assert path.is_file()

    anyio.run(scenario)


def test_invalid_startup_precedes_native_initialization_and_background_threads(
        configured_native, monkeypatch):
    app, path = configured_native
    events = []
    monkeypatch.setenv(ENV_NAME, '81')
    monkeypatch.setenv('ENGINE_BACKUP_ENABLED', 'true')
    monkeypatch.setattr(native, INITIALIZER, lambda: events.append('initialize'))
    monkeypatch.setattr(threading.Thread, 'start', lambda self: events.append('thread'))

    async def scenario():
        with pytest.raises(RuntimeError) as caught:
            async with app.router.lifespan_context(app):
                raise AssertionError('invalid startup must not reach serving state')
        assert str(caught.value) == 'NATIVE_THREAD_TOKENS_INVALID'

    anyio.run(scenario)
    assert events == []
    assert not path.exists()


def test_explicit_80_bounds_default_worker_admission_and_actual_health(
        configured_native, monkeypatch):
    app, _ = configured_native
    monkeypatch.setenv(ENV_NAME, '80')

    async def scenario():
        release = threading.Event()
        captured, health_done = anyio.Event(), anyio.Event()
        entered, snapshots, responses = [], [], []
        entered_lock = threading.Lock()

        def occupy_worker(index):
            with entered_lock:
                entered.append(index)
            assert release.wait(10), 'test worker was not released'

        async def blocked_call(index):
            # This is the unchanged Starlette primitive used by run_observed.
            await run_in_threadpool(occupy_worker, index)

        async def capture_real_dependency():
            sample = await metrics.thread_limiter_health()
            snapshots.append(sample)
            captured.set()
            return sample

        async with app.router.lifespan_context(app):
            limiter = anyio.to_thread.current_default_thread_limiter()
            assert limiter.total_tokens == 80

            async def wait_for_counts(borrowed, waiting, entered_count=None):
                with anyio.fail_after(5):
                    while True:
                        stats = limiter.statistics()
                        with entered_lock:
                            seen = len(entered)
                        if ((stats.borrowed_tokens, stats.tasks_waiting) == (borrowed, waiting)
                                and (entered_count is None or seen == entered_count)):
                            return
                        await anyio.sleep(0.001)

            app.dependency_overrides[metrics.thread_limiter_health] = capture_real_dependency
            try:
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                             base_url='https://native.example') as client:
                    async def read_health():
                        responses.append(await client.get('/health'))
                        health_done.set()

                    async with anyio.create_task_group() as tasks:
                        try:
                            for index in range(80):
                                tasks.start_soon(blocked_call, index)
                            await wait_for_counts(80, 0)
                            for index in range(80, 85):
                                tasks.start_soon(blocked_call, index)
                            await wait_for_counts(80, 5, entered_count=80)
                            assert len(entered) == 80
                            tasks.start_soon(read_health)
                            with anyio.fail_after(5):
                                await captured.wait()
                            # The async dependency observes the pool before the
                            # synchronous Mahjong health body takes its own token.
                            assert snapshots == [{'anyio_thread_limiter': {
                                'total_tokens': 80, 'borrowed_tokens': 80, 'tasks_waiting': 5}}]
                            release.set()
                            with anyio.fail_after(5):
                                await health_done.wait()
                        finally:
                            release.set()
                assert sorted(entered) == list(range(85))
                assert responses[0].status_code == 200
                assert responses[0].json()['anyio_thread_limiter'] == snapshots[0]['anyio_thread_limiter']
                assert responses[0].json()['callback_transport']['pool_limit'] == 40
                assert await metrics.thread_limiter_health() == {'anyio_thread_limiter': {
                    'total_tokens': 80, 'borrowed_tokens': 0, 'tasks_waiting': 0}}
            finally:
                release.set()
                app.dependency_overrides.pop(metrics.thread_limiter_health, None)

    anyio.run(scenario)

