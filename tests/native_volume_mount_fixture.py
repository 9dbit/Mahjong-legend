"""Required CI: run in a private mount namespace, never on a live app volume."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.native_volume import require_persistent_mount, platform_health
from deployment_identity import initialize_bound_database, open_bound_database


def denied(env):
    try:
        require_persistent_mount(env)
    except RuntimeError as error:
        assert str(error) == 'PERSISTENT_NATIVE_VOLUME_REQUIRED'
    else:
        raise AssertionError('An unmounted or volatile path was accepted')


with tempfile.TemporaryDirectory(prefix='native-mount-fixture-') as temporary:
    base = Path(temporary)
    source, target = base / 'source', base / 'mount space\ttab\nline\\slash'
    source.mkdir(); target.mkdir()
    env = dict(os.environ, RAILWAY_SERVICE_ID='synthetic-service',
               RAILWAY_DEPLOYMENT_ID='00000000-0000-4000-8000-000000000001',
               RAILWAY_VOLUME_MOUNT_PATH=str(target), AGENCY_ENVIRONMENT='preproduction',
               AGENCY_DEPLOYMENT_ID='native-mount-fixture', AGENCY_CORE_DEPLOYMENT_ID='core-mount-fixture')
    denied(env)
    mounted = 0
    try:
        subprocess.run(['mount', '--bind', str(source), str(target)], check=True)
        mounted = 1
        assert source.stat().st_dev == target.stat().st_dev == base.stat().st_dev
        assert not os.path.ismount(target), 'This fixture must cover a same-filesystem bind'
        proof = require_persistent_mount(env)
        assert proof['verified'] and proof['verification'] == 'linux_mountinfo'
        health = platform_health(env)
        assert health['platform_deployment_id'] == env['RAILWAY_DEPLOYMENT_ID']
        assert set(health['native_volume']) == {'required', 'verified', 'verification', 'filesystem_type'}
        os.environ.update(env)
        path = target / 'native.sqlite'
        db = initialize_bound_database(str(path), 'mahjong-wild'); db.close()
        db = open_bound_database(str(path), 'mahjong-wild'); db.close()
        (target / 'ordinary').mkdir()
        denied(dict(env, RAILWAY_VOLUME_MOUNT_PATH=str(target / 'ordinary')))
        alias = base / 'alias'; alias.symlink_to(target, target_is_directory=True)
        denied(dict(env, RAILWAY_VOLUME_MOUNT_PATH=str(alias)))
        subprocess.run(['mount', '-t', 'tmpfs', '-o', 'size=1m,nodev,nosuid', 'tmpfs', str(target)], check=True)
        mounted = 2
        denied(env)  # The hidden persistent bind must not satisfy the visible tmpfs.
        subprocess.run(['umount', str(target)], check=True)
        mounted = 1
        assert require_persistent_mount(env)['verified']
        subprocess.run(['mount', '-o', 'remount,bind,ro', str(target)], check=True)
        denied(env)
    finally:
        while mounted:
            subprocess.run(['umount', str(target)], check=True)
            mounted -= 1
    denied(env)  # No stale positive cache after unmount.
    assert (source / 'native.sqlite').is_file() and not (target / 'native.sqlite').exists()
    subprocess.run(['mount', '-t', 'tmpfs', '-o', 'size=1m,nodev,nosuid', 'tmpfs', str(target)], check=True)
    try:
        denied(env)
    finally:
        subprocess.run(['umount', str(target)], check=True)
print('PASS: actual escaped same-filesystem bind, native identity open, readonly/ordinary/symlink/tmpfs rejection, no stale proof')
