import contextlib
import io
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from tools.native_backup_status import backup_health, write_backup_status
from tools import native_backup_loop as loop

COMMIT = 'a' * 40
NOW = datetime(2026, 11, 10, 0, 0, 0, tzinfo=timezone.utc)
FAILED = {'ok': False, 'backup_verified': False}


class StopWorker(BaseException):
    pass


class BackupStatusTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.status = Path(self.directory.name) / 'backup-status.json'

    def marker(self, **updates):
        result = {
            'backup_verified': True,
            'verified_at': (NOW - timedelta(seconds=60)).isoformat(),
            'source_commit': COMMIT,
            'object': 'native/mahjong/123-snapshot.aesgcm',
            'sha256': 'b' * 64,
        }
        result.update(updates)
        return result

    def test_current_verified_build_returns_only_public_fields(self):
        marker = self.marker()
        write_backup_status(self.status, marker)
        self.assertEqual(backup_health(self.status, COMMIT, now=NOW), {
            'ok': True, 'backup_verified': True, 'verified_at': marker['verified_at'], 'source_commit': COMMIT
        })

    def test_disabled_worker_never_reports_current_proof_as_ready(self):
        write_backup_status(self.status, self.marker())
        self.assertEqual(backup_health(self.status, COMMIT, now=NOW, enabled=False), FAILED)

    def test_missing_failed_and_malformed_markers_fail_closed(self):
        self.assertEqual(backup_health(self.status, COMMIT, now=NOW), FAILED)
        for marker in (None, [], True, 42, {}, self.marker(backup_verified=False),
                       self.marker(backup_verified=1), self.marker(object=None),
                       self.marker(sha256='invalid')):
            with self.subTest(marker=marker):
                self.status.write_text(json.dumps(marker), encoding='utf-8')
                self.assertEqual(backup_health(self.status, COMMIT, now=NOW), FAILED)
        self.status.write_text('{"backup_verified":', encoding='utf-8')
        self.assertEqual(backup_health(self.status, COMMIT, now=NOW), FAILED)

    def test_future_stale_naive_and_malformed_times_fail_closed(self):
        invalid = [(NOW + timedelta(microseconds=1)).isoformat(),
                   (NOW - timedelta(seconds=90001)).isoformat(),
                   NOW.replace(tzinfo=None).isoformat(), 'not-a-date', 1, None, []]
        for timestamp in invalid:
            with self.subTest(timestamp=timestamp):
                write_backup_status(self.status, self.marker(verified_at=timestamp))
                self.assertEqual(backup_health(self.status, COMMIT, now=NOW), FAILED)

    def test_freshness_boundaries_are_inclusive(self):
        for age in (0, 90000):
            with self.subTest(age=age):
                write_backup_status(self.status, self.marker(
                    verified_at=(NOW - timedelta(seconds=age)).isoformat()))
                self.assertTrue(backup_health(self.status, COMMIT, now=NOW)['ok'])

    def test_missing_or_wrong_build_binding_fails_closed(self):
        for marker_commit in (None, '', 'c' * 40):
            with self.subTest(marker_commit=marker_commit):
                write_backup_status(self.status, self.marker(source_commit=marker_commit))
                self.assertEqual(backup_health(self.status, COMMIT, now=NOW), FAILED)
        write_backup_status(self.status, self.marker())
        for current_commit in (None, '', 'short', 'c' * 40):
            with self.subTest(current_commit=current_commit):
                self.assertEqual(backup_health(self.status, current_commit, now=NOW), FAILED)

    def test_write_replaces_complete_document_atomically(self):
        old = self.marker(backup_verified=False)
        new = self.marker()
        write_backup_status(self.status, old)
        replace = os.replace
        observed = []
        def observe_replace(source, destination):
            self.assertEqual(Path(source).parent, self.status.parent)
            self.assertEqual(json.loads(self.status.read_text()), old)
            self.assertEqual(json.loads(Path(source).read_text()), new)
            observed.append(True)
            return replace(source, destination)
        with patch('tools.native_backup_status.os.replace', side_effect=observe_replace):
            write_backup_status(self.status, new)
        self.assertEqual(observed, [True])
        self.assertEqual(json.loads(self.status.read_text()), new)
        self.assertEqual(list(self.status.parent.iterdir()), [self.status])

    def test_failed_replace_never_leaves_partial_proof(self):
        old = self.marker()
        write_backup_status(self.status, old)
        with patch('tools.native_backup_status.os.replace', side_effect=OSError('replace failed')):
            with self.assertRaises(OSError):
                write_backup_status(self.status, self.marker(backup_verified=False))
        self.assertEqual(json.loads(self.status.read_text()), old)
        self.assertEqual(list(self.status.parent.iterdir()), [self.status])


class BackupWorkerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.db = Path(self.directory.name) / 'live.sqlite'
        self.db.write_bytes(b'test fixture; backup transport is replaced in worker tests')
        self.status = Path(self.directory.name) / 'backup-status.json'
        self.config = {'RAILWAY_GIT_COMMIT_SHA': COMMIT,
                       'ENGINE_BACKUP_S3_BUCKET': 'test-backups',
                       'RAILWAY_DEPLOYMENT_ID': '00000000-0000-4000-8000-000000000001'}
        self.receipt = {'verified': True, 'object': 'native/mahjong/test.aesgcm',
                        'manifest': {'sha256': 'b' * 64, 'size': 4096}, 'encrypted_size_bytes': 4608}

    def run_once(self, result=None, error=None, config=None):
        values = dict(self.config, **(config or {}))
        output = io.StringIO()
        with patch.dict(os.environ, values, clear=True), patch.object(
                loop, 'backup_once', return_value=result, side_effect=error) as backup, patch.object(
                loop.time, 'sleep', side_effect=StopWorker) as sleep, contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            with self.assertRaises(StopWorker):
                loop.run(['--database', str(self.db), '--game', 'mahjong'], status_file=self.status)
        return backup, sleep, output.getvalue()

    def test_verified_backup_writes_current_build_before_success_log(self):
        backup, sleep, output = self.run_once(result=self.receipt)
        backup.assert_called_once_with(str(self.db), 'mahjong', 'test-backups', 'native')
        sleep.assert_called_once_with(86400)
        marker = json.loads(self.status.read_text())
        self.assertEqual(marker['source_commit'], COMMIT)
        self.assertTrue(backup_health(self.status, COMMIT)['ok'])
        self.assertIn('engine.backup.remote_verified', output)
        event = next(json.loads(line) for line in output.splitlines() if 'engine.backup.remote_verified' in line)
        self.assertEqual(event['size_bytes'], 4096)
        self.assertEqual(event['encrypted_size_bytes'], 4608)
        self.assertEqual(event['platform_deployment_id'], self.config['RAILWAY_DEPLOYMENT_ID'])
        self.assertEqual(datetime.fromisoformat(event['event_at']).utcoffset(), timedelta(0))
        self.assertGreaterEqual(datetime.fromisoformat(event['event_at']) + timedelta(milliseconds=1), datetime.fromisoformat(marker['verified_at']))
        self.assertEqual(marker['size_bytes'], 4096)
        self.assertNotIn(str(self.db), json.dumps(event))

    def test_failed_or_unverified_backup_invalidates_previous_marker_and_retries(self):
        for error, result in ((RuntimeError('readback failed'), None), (None, {}),
                              (None, dict(self.receipt, verified=False))):
            with self.subTest(error=error, result=result):
                write_backup_status(self.status, {
                    'backup_verified': True, 'verified_at': datetime.now(timezone.utc).isoformat(),
                    'source_commit': COMMIT, 'object': self.receipt['object'], 'sha256': 'b' * 64})
                _, sleep, output = self.run_once(result=result, error=error)
                sleep.assert_called_once_with(300)
                self.assertEqual(backup_health(self.status, COMMIT), FAILED)
                self.assertNotIn('engine.backup.remote_verified', output)
                self.assertIn('engine.backup.failed', output)

    def test_success_interval_has_one_hour_minimum(self):
        _, sleep, _ = self.run_once(result=self.receipt, config={'ENGINE_BACKUP_INTERVAL_SECONDS': '1'})
        sleep.assert_called_once_with(3600)

    def test_database_not_ready_waits_without_claiming_backup(self):
        self.db.unlink()
        backup, sleep, output = self.run_once(result=self.receipt)
        backup.assert_not_called()
        sleep.assert_called_once_with(30)
        self.assertFalse(self.status.exists())
        self.assertIn('engine.backup.waiting_for_db', output)


if __name__ == '__main__':
    unittest.main()
