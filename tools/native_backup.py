"""Encrypted online SQLite backup for Soft Tech native engines.

Run as a separate scheduled process. Does not run automatically at import.
"""
import argparse
import hashlib
import json
import os
import sqlite3
import tempfile
import time
from pathlib import Path

def backup_once(db_path, game, bucket, prefix):
    from boto3 import client
    from botocore.config import Config
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    key = bytes.fromhex(os.environ['ENGINE_BACKUP_KEY_HEX'])
    if len(key) != 32:
        raise ValueError('ENGINE_BACKUP_KEY_HEX must contain 32 bytes')
    source = Path(db_path)
    if not source.is_absolute() or not source.is_file():
        raise ValueError('Engine database must exist at an absolute path')
    with tempfile.TemporaryDirectory() as directory:
        snapshot = Path(directory) / 'snapshot.sqlite'
        with sqlite3.connect(f'file:{source}?mode=ro', uri=True, timeout=30) as live:
            with sqlite3.connect(snapshot) as destination:
                live.backup(destination, pages=128, sleep=0.1)
                if destination.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise RuntimeError('Snapshot integrity check failed')
        plaintext = snapshot.read_bytes()
        manifest = {'game': game, 'created_at': int(time.time()),
                    'sha256': hashlib.sha256(plaintext).hexdigest(),
                    'size': len(plaintext), 'format': 'sqlite-online-backup-v1'}
        nonce = os.urandom(12)
        header = json.dumps(manifest, sort_keys=True, separators=(',', ':')).encode()
        ciphertext = AESGCM(key).encrypt(nonce, plaintext, header)
        payload = len(header).to_bytes(4, 'big') + header + nonce + ciphertext
        key_name = f"{prefix.rstrip('/')}/{game}/{manifest['created_at']}-{manifest['sha256'][:16]}.aesgcm"
        storage = client('s3', endpoint_url=os.environ['ENGINE_BACKUP_S3_ENDPOINT'],
                         aws_access_key_id=os.environ['ENGINE_BACKUP_S3_ACCESS_KEY_ID'],
                         aws_secret_access_key=os.environ['ENGINE_BACKUP_S3_SECRET_ACCESS_KEY'],
                         region_name=os.environ.get('ENGINE_BACKUP_S3_REGION', 'auto'),
                         config=Config(s3={'addressing_style':os.environ.get('ENGINE_BACKUP_S3_URL_STYLE','virtual')}))
        storage.put_object(Bucket=bucket, Key=key_name, Body=payload,
                           Metadata={'sha256': manifest['sha256'], 'game': game})
        downloaded = storage.get_object(Bucket=bucket, Key=key_name)['Body'].read()
        if downloaded != payload:
            raise RuntimeError('Remote backup readback mismatch')
        return {'object': key_name, 'manifest': manifest, 'verified': True}

def restore_verify(payload, key_hex):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    size = int.from_bytes(payload[:4], 'big')
    if not 1 <= size <= 8192:
        raise ValueError('Invalid backup manifest length')
    header = payload[4:4 + size]
    manifest = json.loads(header)
    nonce = payload[4 + size:16 + size]
    plaintext = AESGCM(bytes.fromhex(key_hex)).decrypt(nonce, payload[16 + size:], header)
    if hashlib.sha256(plaintext).hexdigest() != manifest['sha256']:
        raise RuntimeError('Snapshot hash mismatch')
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / 'restored.sqlite'
        path.write_bytes(plaintext)
        with sqlite3.connect(path) as db:
            if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise RuntimeError('Restored database integrity check failed')
    return manifest

if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--database', required=True)
    p.add_argument('--game', required=True, choices=['uno', 'mahjong', 'skygate'])
    p.add_argument('--prefix', default='native')
    args = p.parse_args()
    result = backup_once(args.database, args.game,
                         os.environ['ENGINE_BACKUP_S3_BUCKET'], args.prefix)
    print(json.dumps(result))
