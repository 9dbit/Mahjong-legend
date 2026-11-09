"""Mount proof regressions. Real positive bind mounts run in the CI namespace fixture."""
import io
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
import pytest
from tools import native_volume as volume
from tools.native_backup import restore_from_remote, backup_once

ROOT = b'10 1 8:1 / / rw,relatime - ext4 /dev/fixture rw\n'
BIND = b'11 10 8:1 /owned/native /data rw,relatime shared:4 future:ignored - ext4 /dev/fixture rw\n'
UUID = '00000000-0000-4000-8000-000000000001'


def cloud(mount):
    return {'RAILWAY_SERVICE_ID': 'synthetic-service', 'RAILWAY_DEPLOYMENT_ID': UUID,
            'RAILWAY_VOLUME_MOUNT_PATH': str(mount)}


def test_same_device_bind_and_optional_fields_parse_without_ismount():
    records = volume.parse_mountinfo(ROOT + BIND)
    assert records[11]['root'] == '/owned/native'
    assert records[11]['mountpoint'] == '/data'
    assert records[11]['writable']
    assert records[11]['filesystem_type'] == 'ext4'


def test_escaped_paths_are_decoded_once_and_stacked_records_keep_distinct_ids():
    raw = ROOT + BIND.replace(b'/data', rb'/data\040space\011tab\012line\134040')
    record = volume.parse_mountinfo(raw)[11]
    assert record['mountpoint'] == '/data space\ttab\nline\\040'
    stacked = volume.parse_mountinfo(ROOT + BIND + b'12 11 0:9 / /data rw - tmpfs tmpfs rw\n')
    assert stacked[11]['filesystem_type'] == 'ext4'
    assert stacked[12]['filesystem_type'] == 'tmpfs'


@pytest.mark.parametrize('raw', [
    b'', b'invalid', ROOT + BIND + BIND, BIND.replace(b' - ', b' '),
    BIND.replace(b'11 10', b'x 10'), BIND.replace(b'8:1', b'not-device'),
    BIND.replace(b'/data', rb'/data\077'), BIND.replace(b'/data', b'data'),
    BIND.replace(b'/data', b'/data\0'), BIND.replace(b' ext4 ', b' ext/4 '),
    BIND.replace(b'11 10', b'9007199254740992 10'),
    b'x' * (volume.MAX_MOUNTINFO_BYTES + 1),
    ROOT + b'11 10 8:1 / /data rw ' + b'x' * volume.MAX_MOUNTINFO_LINE_BYTES + b' - ext4 disk rw\n',
])
def test_malformed_and_oversized_mount_tables_fail_closed(raw):
    with pytest.raises(RuntimeError, match='^PERSISTENT_NATIVE_VOLUME_REQUIRED$'):
        volume.parse_mountinfo(raw)


def test_line_count_is_bounded():
    raw = b''.join(str(i).encode() + b' 0 8:1 / /data rw - ext4 disk rw\n'
                   for i in range(1, volume.MAX_MOUNTINFO_LINES + 2))
    with pytest.raises(RuntimeError, match=volume.ERROR):
        volume.parse_mountinfo(raw)


def test_read_is_bounded_and_missing_file_is_not_a_positive_proof(tmp_path):
    path = tmp_path / 'bounded'
    path.write_bytes(b'a' * 4097)
    with pytest.raises(RuntimeError, match=volume.ERROR):
        volume._read_bounded(path, 4096)
    with pytest.raises(FileNotFoundError):
        volume._read_bounded(tmp_path / 'missing', 4096)


def test_real_proc_rejects_existing_ordinary_directory(tmp_path):
    mount = tmp_path / 'data'
    mount.mkdir()
    assert mount.is_dir()
    with pytest.raises(RuntimeError, match=volume.ERROR):
        volume.require_persistent_mount(cloud(mount))
    assert list(mount.iterdir()) == []


def test_symlink_and_nested_ordinary_path_fail_closed(tmp_path):
    mount = tmp_path / 'data'
    mount.mkdir()
    link = tmp_path / 'link'
    link.symlink_to(mount, target_is_directory=True)
    for path in (link, mount / 'missing', '/'):
        with pytest.raises(RuntimeError, match=volume.ERROR):
            volume.require_persistent_mount(cloud(path))


def test_real_tmpfs_is_not_accepted_as_persistent():
    if sys.platform != 'linux' or not Path('/dev/shm').is_dir():
        pytest.skip('Linux shared-memory mount unavailable')
    with pytest.raises(RuntimeError, match=volume.ERROR):
        volume.require_persistent_mount(cloud('/dev/shm'))


def test_cloud_missing_mount_and_non_linux_fail_closed(monkeypatch, tmp_path):
    for values in ({'RAILWAY_SERVICE_ID': 'synthetic'}, cloud('relative')):
        with pytest.raises(RuntimeError, match=volume.ERROR):
            volume.require_persistent_mount(values)
    monkeypatch.setattr(volume.sys, 'platform', 'darwin')
    with pytest.raises(RuntimeError, match=volume.ERROR):
        volume.require_persistent_mount(cloud(tmp_path))
    assert volume.require_persistent_mount({}) is None


def test_inaccessible_proc_cannot_fall_back_to_directory(monkeypatch, tmp_path):
    def unavailable(*args):
        raise PermissionError('synthetic inaccessible kernel metadata')
    monkeypatch.setattr(volume, '_read_bounded', unavailable)
    with pytest.raises(RuntimeError, match='^PERSISTENT_NATIVE_VOLUME_REQUIRED$'):
        volume.require_persistent_mount(cloud(tmp_path))


def test_startup_restore_checks_mount_before_any_download_or_marker(tmp_path, monkeypatch):
    mount = tmp_path / 'data'
    mount.mkdir()
    for name, value in cloud(mount).items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv('ENGINE_RESTORE_OBJECT_KEY', 'native/mahjong/synthetic.aesgcm')
    with patch('boto3.client', side_effect=AssertionError('must not download')):
        with pytest.raises(RuntimeError, match=volume.ERROR):
            restore_from_remote(mount / 'native.sqlite', 'mahjong', {})
        with pytest.raises(RuntimeError, match=volume.ERROR):
            backup_once(mount / 'native.sqlite', 'mahjong', 'synthetic-bucket', 'native')
    assert list(mount.iterdir()) == []


def test_health_and_event_provenance_do_not_publish_kernel_or_path_details(monkeypatch):
    proof = {'verified': True, 'verification': 'linux_mountinfo', 'mount_id': 999,
             'filesystem_type': 'ext4', 'source': '/private/host/device'}
    monkeypatch.setattr(volume, 'require_persistent_mount', lambda env: proof)
    health = volume.platform_health(cloud('/private/native/path'))
    assert health == {'platform_deployment_id': UUID, 'native_volume': {
        'required': True, 'verified': True, 'verification': 'linux_mountinfo', 'filesystem_type': 'ext4'}}
    before = datetime.now(timezone.utc)
    event = volume.event_provenance({'RAILWAY_DEPLOYMENT_ID': UUID, 'secret': 'do-not-copy'})
    assert before.timestamp() - 0.001 <= datetime.fromisoformat(event['event_at']).timestamp() <= datetime.now(timezone.utc).timestamp()
    assert event['platform_deployment_id'] == UUID and set(event) == {'event_at', 'platform_deployment_id'}
    assert volume.event_provenance({'RAILWAY_DEPLOYMENT_ID': 'not-a-uuid'})['platform_deployment_id'] is None
