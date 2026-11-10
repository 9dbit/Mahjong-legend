"""Feed to the final image on stdin; modules and entrypoint come only from /app."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request
from tools import native_volume
import native_worker_limits
import tools.native_backup, tools.native_backup_loop, tools.native_backup_status, tools.native_retention

assert Path(native_volume.__file__).resolve() == Path('/app/tools/native_volume.py')
assert Path(native_worker_limits.__file__).resolve() == Path('/app/native_worker_limits.py')
mode = sys.argv[1]
assert mode in ('mounted', 'unmounted')
mount = Path('/data')
mount.mkdir(exist_ok=True)
env = dict(os.environ, RAILWAY_SERVICE_ID='synthetic-service',
           RAILWAY_DEPLOYMENT_ID='00000000-0000-4000-8000-000000000001', RAILWAY_VOLUME_MOUNT_PATH='/data',
           AGENCY_WALLET_MODE='sandbox', AGENCY_ENVIRONMENT='preproduction',
           AGENCY_DEPLOYMENT_ID='native-image-smoke', AGENCY_CORE_DEPLOYMENT_ID='core-image-smoke',
           AGENCY_WALLET_ORIGIN='https://core.example.invalid', AGENCY_WALLET_KEY_ID='synthetic-image-smoke',
           AGENCY_WALLET_SECRET='synthetic-image-secret-never-for-use-' * 2,
           MAHJONG_AGENCY_DB_PATH='/data/native.sqlite', AGENCY_STUDIO_SYNC='0', ENGINE_BACKUP_ENABLED='false', PORT='18080',
           NATIVE_THREAD_TOKENS='80')
for key in tuple(env):
    if key.startswith('ENGINE_RESTORE_'):
        del env[key]
command = [sys.executable, 'tools/start_studio.py']
if mode == 'unmounted':
    before = mount.stat()
    try:
        native_volume.require_persistent_mount(env)
    except RuntimeError as error:
        assert str(error) == 'PERSISTENT_NATIVE_VOLUME_REQUIRED'
    else:
        raise AssertionError('A directory in the image was accepted as a mounted volume')
    result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=12)
    assert result.returncode != 0 and 'PERSISTENT_NATIVE_VOLUME_REQUIRED' in result.stderr
    after = mount.stat()
    assert (before.st_uid, before.st_gid, before.st_mode) == (after.st_uid, after.st_gid, after.st_mode)
    assert not (mount / 'native.sqlite').exists() and not (mount / '.native-restore.json').exists()
else:
    assert native_volume.require_persistent_mount(env)['verified']
    child = subprocess.Popen(command, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        deadline = time.monotonic() + 12
        health = None
        while time.monotonic() < deadline:
            if child.poll() is not None:
                raise AssertionError('Native image entrypoint terminated before health')
            try:
                with urllib.request.build_opener(urllib.request.ProxyHandler({})).open('http://127.0.0.1:18080/health', timeout=1) as response:
                    health = json.loads(response.read(65536))
                break
            except (OSError, ValueError):
                time.sleep(0.05)
        assert health and health['ok'] and health['database'] == 'connected'
        assert health['platform_deployment_id'] == env['RAILWAY_DEPLOYMENT_ID']
        assert health['native_volume']['required'] and health['native_volume']['verified']
        assert health['native_volume']['verification'] == 'linux_mountinfo'
        assert set(health['native_volume']) == {'required', 'verified', 'verification', 'filesystem_type'}
        assert health['cpu_usage_microseconds'] is not None and health['memory_rss_bytes'] > 0
        assert health['anyio_thread_limiter']['total_tokens'] == 80
        assert health['callback_transport']['pool_limit'] == 40
        phases = health['native_phases']
        assert phases['schema'] == 1 and phases['available'] and phases['capture_limit'] == 1024
        assert phases['active_captures'] == 0 and not phases['telemetry_error']
        assert (mount / 'native.sqlite').is_file()
        print('PASS: mounted image effective AnyIO worker limit 80 and callback pool 40')
    finally:
        child.terminate()
        try:
            child.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            child.kill(); child.communicate(timeout=5)
print('PASS: final image actual entrypoint and mount guard: ' + mode)
