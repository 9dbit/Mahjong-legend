"""Actual process counters and the real native health route under worker load."""
import json
import subprocess
import sys
import threading
import time
from pathlib import Path

import anyio
import httpx
import pytest

import agency_runtime as native
import native_observability as metrics
from agency_wallet import close_transport
from agency_runtime import app

DB_VARIABLE = 'MAHJONG_AGENCY_DB_PATH'
GAME_ID = 'mahjong-wild'
METRICS_MODULE = 'native_observability'
initialize = native.init


@pytest.fixture
def configured_app(tmp_path, monkeypatch):
    path = tmp_path / 'native.sqlite'
    values = {
        'AGENCY_WALLET_MODE': 'sandbox', 'AGENCY_ENVIRONMENT': 'preproduction',
        'AGENCY_DEPLOYMENT_ID': 'native-observability-test',
        'AGENCY_CORE_DEPLOYMENT_ID': 'core-observability-test',
        DB_VARIABLE: str(path), 'AGENCY_WALLET_ORIGIN': 'https://core.example',
        'AGENCY_WALLET_KEY_ID': 'synthetic-engine',
        'AGENCY_WALLET_SECRET': 'synthetic-observability-fixture-secret-only',
        'ENGINE_BACKUP_ENABLED': 'false', 'AGENCY_STUDIO_SYNC': '0',
        'RAILWAY_GIT_COMMIT_SHA': 'a' * 40,
    }
    for key in ('RAILWAY_PROJECT_ID', 'RAILWAY_SERVICE_ID', 'RAILWAY_DEPLOYMENT_ID',
                'RAILWAY_VOLUME_MOUNT_PATH', 'ENGINE_RESTORE_OBJECT_KEY',
                'ENGINE_RESTORE_OBJECT', 'ENGINE_RESTORE_CIPHERTEXT_SHA256'):
        monkeypatch.delenv(key, raising=False)
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    initialize()
    try:
        yield app, path
    finally:
        close_transport()


@pytest.mark.skipif(metrics.resource is None, reason='getrusage unavailable')
def test_actual_process_cpu_counters_advance_with_work():
    before = metrics.process_health()['cpu_usage_microseconds']
    deadline = time.process_time() + 0.04
    while time.process_time() < deadline:
        sum(value * value for value in range(100))
    after = metrics.process_health()['cpu_usage_microseconds']
    assert set(after) == {'user', 'system'}
    assert all(type(after[key]) is int and after[key] >= before[key] for key in after)
    assert sum(after.values()) - sum(before.values()) >= 30_000


@pytest.mark.skipif(not sys.platform.startswith('linux'), reason='Linux current RSS')
def test_rss_tracks_released_resident_pages_instead_of_historical_peak():
    # A separate process avoids allocator history and other test threads. Touch
    # every mmap page, then unmap it: current RSS must fall while ru_maxrss stays.
    script = f'''
import json, mmap, os, resource
from {METRICS_MODULE} import process_health
before = process_health()['memory_rss_bytes']
size = 32 * 1024 * 1024
region = mmap.mmap(-1, size)
for offset in range(0, size, os.sysconf('SC_PAGE_SIZE')):
    region[offset] = 1
during = process_health()['memory_rss_bytes']
peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
region.close()
after = process_health()['memory_rss_bytes']
peak_after = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
print(json.dumps([before, during, after, peak, peak_after]))
'''
    result = subprocess.run([sys.executable, '-c', script], check=True,
                            capture_output=True, text=True, timeout=10,
                            cwd=Path(__file__).resolve().parents[1])
    before, during, after, peak, peak_after = json.loads(result.stdout)
    assert during - before >= 24 * 1024 * 1024
    assert during - after >= 24 * 1024 * 1024
    assert peak_after >= peak


def test_unavailable_platform_metrics_are_explicit_null(monkeypatch):
    monkeypatch.setattr(metrics, 'resource', None)
    monkeypatch.setattr(metrics.sys, 'platform', 'unsupported')
    assert metrics.process_health() == {
        'cpu_usage_microseconds': None, 'memory_rss_bytes': None}


def test_unreadable_linux_rss_is_explicit_null(monkeypatch):
    def unavailable(*args, **kwargs):
        raise PermissionError('synthetic unavailable proc counter')
    monkeypatch.setattr(metrics.sys, 'platform', 'linux')
    monkeypatch.setattr(metrics, 'open', unavailable, raising=False)
    assert metrics.process_health()['memory_rss_bytes'] is None


def test_unavailable_async_limiter_is_explicit_null(monkeypatch):
    def unavailable():
        raise RuntimeError('synthetic unavailable async backend')
    monkeypatch.setattr(metrics, 'current_default_thread_limiter', unavailable)
    assert anyio.run(metrics.thread_limiter_health) == {'anyio_thread_limiter': None}


def test_health_preserves_identity_guards_and_reports_actual_metrics(configured_app, monkeypatch):
    native_app, path = configured_app

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=native_app),
                                     base_url='https://native.example') as client:
            response = await client.get('/health')
            assert response.status_code == 200
            health = response.json()
            assert health['ok'] and health['database'] == 'connected'
            assert health['source_commit'] == 'a' * 40
            assert health['deployment_identity']['game_id'] == GAME_ID
            assert health['deployment_identity']['deployment_id'] == 'native-observability-test'
            assert health['deployment_identity']['environment'] == 'preproduction'
            assert health['anyio_thread_limiter'] == {
                'total_tokens': 40, 'borrowed_tokens': 0, 'tasks_waiting': 0}
            assert health['cpu_usage_microseconds'] is not None
            assert health['memory_rss_bytes'] > 0
            assert health['process_boot_id'] and health['uptime_seconds'] >= 0
            assert 'synthetic-observability-fixture-secret-only' not in response.text
            before = path.read_bytes()
            monkeypatch.setenv('AGENCY_DEPLOYMENT_ID', 'wrong-observability-test')
            # Diagnostics must not convert a failed binding into a healthy reply.
            with pytest.raises(RuntimeError, match='IDENTITY_MISMATCH'):
                await client.get('/health')
            assert path.read_bytes() == before

    anyio.run(scenario)


def test_real_health_samples_saturated_default_limiter_before_worker_admission(configured_app):
    native_app, _ = configured_app

    async def scenario():
        limiter = anyio.to_thread.current_default_thread_limiter()
        assert limiter.total_tokens == 40
        release = threading.Event()
        captured = anyio.Event()
        health_done = anyio.Event()
        snapshots, responses = [], []

        def occupy_worker():
            assert release.wait(10), 'test worker was not released'

        async def blocked_call():
            await anyio.to_thread.run_sync(occupy_worker)

        async def capture_real_dependency():
            sample = await metrics.thread_limiter_health()
            snapshots.append(sample)
            captured.set()
            return sample

        async def wait_for_counts(borrowed, waiting):
            with anyio.fail_after(5):
                while True:
                    stats = limiter.statistics()
                    if (stats.borrowed_tokens, stats.tasks_waiting) == (borrowed, waiting):
                        return
                    await anyio.sleep(0.001)

        native_app.dependency_overrides[metrics.thread_limiter_health] = capture_real_dependency
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=native_app),
                                         base_url='https://native.example') as client:
                async def read_health():
                    responses.append(await client.get('/health'))
                    health_done.set()

                async with anyio.create_task_group() as tasks:
                    try:
                        for _ in range(40):
                            tasks.start_soon(blocked_call)
                        await wait_for_counts(40, 0)
                        for _ in range(5):
                            tasks.start_soon(blocked_call)
                        await wait_for_counts(40, 5)
                        tasks.start_soon(read_health)
                        with anyio.fail_after(5):
                            await captured.wait()
                        assert snapshots == [{'anyio_thread_limiter': {
                            'total_tokens': 40, 'borrowed_tokens': 40, 'tasks_waiting': 5}}]
                        release.set()
                        with anyio.fail_after(5):
                            await health_done.wait()
                    finally:
                        release.set()
            assert responses[0].status_code == 200
            sample = responses[0].json()['anyio_thread_limiter']
            assert sample == snapshots[0]['anyio_thread_limiter']
            assert set(sample) == {'total_tokens', 'borrowed_tokens', 'tasks_waiting'}
            assert await metrics.thread_limiter_health() == {'anyio_thread_limiter': {
                'total_tokens': 40, 'borrowed_tokens': 0, 'tasks_waiting': 0}}
        finally:
            release.set()
            native_app.dependency_overrides.pop(metrics.thread_limiter_health, None)

    anyio.run(scenario)
