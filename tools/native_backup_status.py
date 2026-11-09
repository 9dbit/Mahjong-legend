"""Atomic, build-bound evidence for completed native database backups."""
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path

MAX_BACKUP_AGE_SECONDS = 90000


def write_backup_status(status_file, marker):
    """Replace a complete marker on the same filesystem; never expose partial JSON."""
    destination = Path(status_file)
    serialized = json.dumps(marker, separators=(',', ':'), sort_keys=True) + '\n'
    descriptor, temporary_name = tempfile.mkstemp(
        prefix='.' + destination.name + '.', suffix='.tmp', dir=destination.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            stream.write(serialized)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def backup_health(status_file, source_commit, *, now=None, enabled=True):
    """Return public-safe evidence only for a fresh backup of this deployed build."""
    failed = {'ok': False, 'backup_verified': False}
    if enabled is not True:
        return failed
    if not isinstance(source_commit, str) or re.fullmatch(r'[0-9a-f]{40}', source_commit) is None:
        return failed
    try:
        marker = json.loads(Path(status_file).read_text(encoding='utf-8'))
        if not isinstance(marker, dict) or marker.get('backup_verified') is not True:
            return failed
        if marker.get('source_commit') != source_commit:
            return failed
        if not isinstance(marker.get('object'), str) or not marker['object']:
            return failed
        if not isinstance(marker.get('sha256'), str) or re.fullmatch(r'[0-9a-f]{64}', marker['sha256']) is None:
            return failed
        timestamp = marker.get('verified_at')
        if not isinstance(timestamp, str):
            return failed
        verified_at = datetime.fromisoformat(timestamp)
        if verified_at.tzinfo is None or verified_at.utcoffset() is None:
            return failed
        current = now if now is not None else datetime.now(timezone.utc)
        age = (current - verified_at).total_seconds()
        if age < 0 or age > MAX_BACKUP_AGE_SECONDS:
            return failed
        result = {'ok': True, 'backup_verified': True, 'verified_at': timestamp, 'source_commit': source_commit}
        retention = marker.get('retention')
        if isinstance(retention, dict) and retention.get('enabled') is True:
            result['retention'] = {key: retention.get(key) for key in ('policy','enabled','mode','verified','verified_at','eligible_count','deleted_count','error_code')}
        return result
    except (OSError, ValueError, KeyError, TypeError, OverflowError):
        return failed
