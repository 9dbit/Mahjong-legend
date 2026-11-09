import io
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from cryptography.exceptions import InvalidTag
from tools.native_backup import backup_once, restore_verify


class FakeS3:
    """In-memory transport double; never contacts a remote bucket."""
    def __init__(self):
        self.objects = {}

    def put_object(self, Bucket, Key, Body, Metadata):
        self.objects[(Bucket, Key)] = Body

    def get_object(self, Bucket, Key):
        return {'Body': io.BytesIO(self.objects[(Bucket, Key)])}


class BackupTests(unittest.TestCase):
    def make_database(self, directory):
        db_path = Path(directory) / 'live.sqlite'
        with sqlite3.connect(db_path) as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('CREATE TABLE rounds(id INTEGER PRIMARY KEY, amount INTEGER)')
            db.execute('INSERT INTO rounds(amount) VALUES(42)')
            db.commit()
        return db_path

    def config(self, style='virtual-host'):
        config = {
            'ENGINE_BACKUP_KEY_HEX': os.urandom(32).hex(),
            'ENGINE_BACKUP_S3_ENDPOINT': 'https://example.invalid',
            'ENGINE_BACKUP_S3_ACCESS_KEY_ID': 'test',
            'ENGINE_BACKUP_S3_SECRET_ACCESS_KEY': 'test',
        }
        if style is not None:
            config['ENGINE_BACKUP_S3_URL_STYLE'] = style
        return config

    def test_encrypted_remote_snapshot_and_isolated_restore(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = self.make_database(directory)
            s3 = FakeS3()
            config = self.config()
            with patch.dict(os.environ, config, clear=True), patch('boto3.client', return_value=s3) as factory:
                result = backup_once(str(db_path), 'mahjong', 'backups', 'native')
            self.assertEqual(factory.call_args.kwargs['config'].s3['addressing_style'], 'virtual')
            payload = next(iter(s3.objects.values()))
            self.assertNotIn(b'CREATE TABLE rounds', payload)
            self.assertTrue(result['verified'])
            self.assertEqual(restore_verify(payload, config['ENGINE_BACKUP_KEY_HEX'])['sha256'],
                             result['manifest']['sha256'])
            corrupted = bytearray(payload)
            corrupted[-1] ^= 1
            with self.assertRaises(InvalidTag):
                restore_verify(bytes(corrupted), config['ENGINE_BACKUP_KEY_HEX'])

    def test_supported_addressing_styles_reach_real_botocore_config(self):
        cases = [(None, 'virtual'), ('auto', 'auto'), ('virtual', 'virtual'),
                 ('path', 'path'), ('virtual-host', 'virtual'),
                 (' VIRTUAL-HOST ', 'virtual')]
        with tempfile.TemporaryDirectory() as directory:
            db_path = self.make_database(directory)
            for configured, expected in cases:
                with self.subTest(style=configured):
                    s3 = FakeS3()
                    with patch.dict(os.environ, self.config(configured), clear=True), patch('boto3.client', return_value=s3) as factory:
                        result = backup_once(str(db_path), 'mahjong', 'backups', 'native')
                    self.assertEqual(factory.call_args.kwargs['config'].s3['addressing_style'], expected)
                    self.assertTrue(result['verified'])

    def test_invalid_style_fails_before_database_read_or_storage_call(self):
        for style in ('', 'virtual_host', 'path-style', 'invalid'):
            with self.subTest(style=style):
                with patch.dict(os.environ, self.config(style), clear=True), patch('boto3.client') as factory, patch('tools.native_backup.sqlite3.connect') as connect:
                    with self.assertRaisesRegex(ValueError, 'ENGINE_BACKUP_S3_URL_STYLE must be'):
                        backup_once('/nonexistent/live.sqlite', 'mahjong', 'backups', 'native')
                    factory.assert_not_called()
                    connect.assert_not_called()

    def test_remote_readback_mismatch_is_not_reported_as_verified(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = self.make_database(directory)
            s3 = FakeS3()
            with patch.dict(os.environ, self.config(), clear=True), patch('boto3.client', return_value=s3), patch.object(s3, 'get_object', return_value={'Body': io.BytesIO(b'corrupt remote readback')}):
                with self.assertRaisesRegex(RuntimeError, 'Remote backup readback mismatch'):
                    backup_once(str(db_path), 'mahjong', 'backups', 'native')
            self.assertEqual(len(s3.objects), 1)


if __name__ == '__main__':
    unittest.main()
