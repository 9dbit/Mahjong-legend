import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from tools.native_backup import backup_once, restore_verify

class FakeS3:
    def __init__(self):
        self.objects = {}
    def put_object(self, Bucket, Key, Body, Metadata):
        self.objects[(Bucket, Key)] = Body
    def get_object(self, Bucket, Key):
        import io
        return {'Body': io.BytesIO(self.objects[(Bucket, Key)])}

class BackupTests(unittest.TestCase):
    def test_encrypted_remote_snapshot_and_isolated_restore(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / 'live.sqlite'
            with sqlite3.connect(db_path) as db:
                db.execute('PRAGMA journal_mode=WAL')
                db.execute('CREATE TABLE rounds(id INTEGER PRIMARY KEY, amount INTEGER)')
                db.execute('INSERT INTO rounds(amount) VALUES(42)')
                db.commit()
            s3 = FakeS3()
            key = os.urandom(32).hex()
            config = {'ENGINE_BACKUP_KEY_HEX':key,'ENGINE_BACKUP_S3_ENDPOINT':'https://example.invalid',
                      'ENGINE_BACKUP_S3_ACCESS_KEY_ID':'test','ENGINE_BACKUP_S3_SECRET_ACCESS_KEY':'test'}
            with patch.dict(os.environ,config),patch('boto3.client',return_value=s3):
                result=backup_once(str(db_path),'mahjong','backups','native')
            payload=next(iter(s3.objects.values()))
            self.assertNotIn(b'CREATE TABLE rounds',payload)
            self.assertTrue(result['verified'])
            self.assertEqual(restore_verify(payload,key)['sha256'],result['manifest']['sha256'])
            corrupted=bytearray(payload);corrupted[-1]^=1
            with self.assertRaises(Exception):
                restore_verify(bytes(corrupted),key)

if __name__ == '__main__':
    unittest.main()
