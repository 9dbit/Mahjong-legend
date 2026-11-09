"""Fail closed unless a cloud native database has a real writable Linux mount.

mountinfo identifies bind mounts even when st_dev matches the parent. fdinfo's
mnt_id selects the mount actually visible through the opened directory, including
stacked mounts. Neither check certifies a provider volume ID or single writer.
Kernel format: https://www.kernel.org/doc/html/latest/filesystems/proc.html
"""
import os
import re
import stat
import sys
from datetime import datetime, timezone

MAX_MOUNTINFO_BYTES = 1024 * 1024
MAX_MOUNTINFO_LINES = 4096
MAX_MOUNTINFO_LINE_BYTES = 65536
MAX_FDINFO_BYTES = 4096
ERROR = 'PERSISTENT_NATIVE_VOLUME_REQUIRED'
_CLOUD_KEYS = ('RAILWAY_PROJECT_ID', 'RAILWAY_SERVICE_ID', 'RAILWAY_DEPLOYMENT_ID')
_VOLATILE_FS = frozenset((
    'overlay', 'overlayfs', 'aufs', 'fuse.overlayfs', 'fuse.fuse-overlayfs',
    'tmpfs', 'ramfs', 'rootfs', 'devtmpfs', 'proc', 'sysfs', 'devpts',
    'cgroup', 'cgroup2', 'securityfs', 'configfs', 'debugfs', 'tracefs',
    'pstore', 'mqueue', 'hugetlbfs', 'autofs', 'fusectl', 'rpc_pipefs', 'bpf',
    'squashfs', 'iso9660'))
_ESCAPES = {b'040': b' ', b'011': b'\t', b'012': b'\n', b'134': b'\\'}
_cached = None


def _fail():
    raise RuntimeError(ERROR)


def _path_field(value):
    # One pass: an escaped backslash followed by digits is not decoded twice.
    if re.search(rb'\\(?!040|011|012|134)', value):
        _fail()
    decoded = re.sub(rb'\\(040|011|012|134)', lambda m: _ESCAPES[m[1]], value)
    if not decoded.startswith(b'/') or b'\0' in decoded:
        _fail()
    return os.fsdecode(decoded)


def parse_mountinfo(raw):
    """Pure bounded parser; unrecognized optional fields are deliberately ignored."""
    if not isinstance(raw, bytes) or not raw or len(raw) > MAX_MOUNTINFO_BYTES:
        _fail()
    lines = raw.split(b'\n')
    if lines[-1] == b'':
        lines.pop()
    if len(lines) > MAX_MOUNTINFO_LINES:
        _fail()
    records = {}
    for line in lines:
        if not line or len(line) > MAX_MOUNTINFO_LINE_BYTES or line.count(b' - ') != 1:
            _fail()
        before, after = line.split(b' - ')
        fields, tail = before.split(b' '), after.split(b' ')
        if len(fields) < 6 or len(tail) != 3 or any(not x for x in fields + tail):
            _fail()
        if not re.fullmatch(rb'[1-9][0-9]{0,15}', fields[0]) or not re.fullmatch(rb'[0-9]{1,16}', fields[1]):
            _fail()
        if not re.fullmatch(rb'[0-9]+:[0-9]+', fields[2]) or not re.fullmatch(rb'[A-Za-z0-9_.-]{1,64}', tail[0]):
            _fail()
        mount_id = int(fields[0])
        if mount_id in records or mount_id > 9007199254740991:
            _fail()
        records[mount_id] = {
            'mount_id': mount_id, 'root': _path_field(fields[3]),
            'mountpoint': _path_field(fields[4]),
            'filesystem_type': tail[0].decode('ascii'),
            'writable': b'rw' in fields[5].split(b',') and b'ro' not in fields[5].split(b',')
                        and b'rw' in tail[2].split(b',') and b'ro' not in tail[2].split(b',')}
    return records


def _read_bounded(path, limit):
    with open(path, 'rb') as stream:
        parts, size = [], 0
        while True:
            chunk = stream.read(min(8192, limit + 1 - size))
            if not chunk:
                return b''.join(parts)
            size += len(chunk)
            if size > limit:
                _fail()
            parts.append(chunk)


def _mount_id(fd):
    raw = _read_bounded('/proc/self/fdinfo/' + str(fd), MAX_FDINFO_BYTES)
    matches = re.findall(rb'^mnt_id:\s*([0-9]+)\s*$', raw, re.MULTILINE)
    if len(matches) != 1:
        _fail()
    return int(matches[0])


def _mounts():
    global _cached
    raw = _read_bounded('/proc/self/mountinfo', MAX_MOUNTINFO_BYTES)
    # Read fresh kernel bytes every time. Only parsing unchanged bytes is cached.
    if _cached is None or _cached[0] != os.getpid() or _cached[1] != raw:
        _cached = (os.getpid(), raw, parse_mountinfo(raw))
    return _cached[2]


def require_persistent_mount(env=None):
    env = os.environ if env is None else env
    if not any(env.get(name) for name in _CLOUD_KEYS):
        return None
    try:
        mount = env.get('RAILWAY_VOLUME_MOUNT_PATH', '')
        if sys.platform != 'linux' or not isinstance(mount, str) or not os.path.isabs(mount):
            _fail()
        canonical = os.path.realpath(mount, strict=True)
        if canonical == '/' or canonical != os.path.normpath(mount):
            _fail()
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        fd = os.open(canonical, flags)
        try:
            if not stat.S_ISDIR(os.fstat(fd).st_mode):
                _fail()
            mount_id = _mount_id(fd)
            selected = _mounts().get(mount_id)
            if not selected or selected['mountpoint'] != canonical:
                _fail()
            if not selected['writable'] or selected['filesystem_type'].lower() in _VOLATILE_FS:
                _fail()
            # The path must still resolve to this descriptor after reading proc.
            current, opened = os.stat(canonical, follow_symlinks=False), os.fstat(fd)
            if (current.st_dev, current.st_ino) != (opened.st_dev, opened.st_ino):
                _fail()
            return {'verified': True, 'verification': 'linux_mountinfo',
                    'mount_id': mount_id, 'filesystem_type': selected['filesystem_type']}
        finally:
            os.close(fd)
    except (OSError, ValueError, TypeError, RuntimeError):
        raise RuntimeError(ERROR) from None


def _identifier(value):
    return value if isinstance(value, str) and re.fullmatch(r'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}', value) else None


def platform_health(env=None):
    env = os.environ if env is None else env
    proof = require_persistent_mount(env)
    return {
        'platform_deployment_id': _identifier(env.get('RAILWAY_DEPLOYMENT_ID')),
        'native_volume': {'required': proof is not None, 'verified': bool(proof),
            'verification': proof['verification'] if proof else 'not_required_local',
            'filesystem_type': proof['filesystem_type'] if proof else None}}


def event_provenance(env=None):
    """Emission time and platform UUID; never infer provider ingestion ordering."""
    env = os.environ if env is None else env
    return {'event_at': datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z'),
            'platform_deployment_id': _identifier(env.get('RAILWAY_DEPLOYMENT_ID'))}
