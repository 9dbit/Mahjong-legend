"""Encrypted online SQLite backup for Soft Tech native engines.

Run as a separate scheduled process. Does not run automatically at import.
"""
import argparse
import hashlib
import io
import json
import os
import re
import sqlite3
import tempfile
import time
from pathlib import Path
from contextlib import closing

CHUNK_SIZE = 1024 * 1024


def file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as source:
        while chunk := source.read(CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def encrypt_snapshot(snapshot, destination, manifest, key, *, nonce=None):
    """Write the unchanged v1 envelope without holding a database-sized buffer."""
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    nonce = os.urandom(12) if nonce is None else nonce
    header = json.dumps(manifest, sort_keys=True, separators=(',', ':')).encode()
    if not 1 <= len(header) <= 8192 or len(nonce) != 12:
        raise ValueError('Invalid backup header or nonce')
    encryptor = Cipher(algorithms.AES(key), modes.GCM(nonce)).encryptor()
    encryptor.authenticate_additional_data(header)
    plaintext_hash, ciphertext_hash, size = hashlib.sha256(), hashlib.sha256(), 0
    with Path(destination).open('xb') as output, Path(snapshot).open('rb') as source:
        def write(data):
            output.write(data); ciphertext_hash.update(data)
        write(len(header).to_bytes(4, 'big') + header + nonce)
        while chunk := source.read(CHUNK_SIZE):
            plaintext_hash.update(chunk); size += len(chunk)
            write(encryptor.update(chunk))
        write(encryptor.finalize()); write(encryptor.tag)
    if plaintext_hash.hexdigest() != manifest['sha256'] or size != manifest['size']:
        raise RuntimeError('Snapshot changed during encryption')
    return ciphertext_hash.hexdigest()


def download_to_file(storage, bucket, object_name, destination):
    """Close the remote body on every outcome; the caller owns the temporary file."""
    response = storage.get_object(Bucket=bucket, Key=object_name)
    body = response['Body']; digest = hashlib.sha256(); size = 0
    try:
        with Path(destination).open('xb') as output:
            while chunk := body.read(CHUNK_SIZE):
                output.write(chunk); digest.update(chunk); size += len(chunk)
    finally:
        body.close()
    return {'sha256': digest.hexdigest(), 'size': size, 'etag': response.get('ETag')}


def decrypt_to_file(payload, destination, key_hex=None, *, keys=None):
    """Authenticate in a private temporary file before any SQLite read/publication.

    bytes input remains supported for old callers and fixtures. Runtime callers
    pass an archive path, so encryption, restore and retention are bounded by
    CHUNK_SIZE rather than the database size.
    """
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    if isinstance(payload, bytes):
        source = io.BytesIO(payload)
    elif isinstance(payload, (str, os.PathLike)):
        source = Path(payload).open('rb')
    else:
        raise TypeError('Backup payload must be bytes or an archive path')
    owned = False; target = Path(destination)
    try:
        with source:
            source.seek(0, os.SEEK_END); total_size = source.tell(); source.seek(0)
            raw_size = source.read(4)
            size = int.from_bytes(raw_size, 'big')
            if len(raw_size) != 4 or not 1 <= size <= 8192 or total_size < size + 32:
                raise ValueError('Invalid backup manifest length')
            header = source.read(size); manifest = json.loads(header)
            if not isinstance(manifest, dict): raise ValueError('Invalid backup manifest')
            if key_hex is not None:
                key = bytes.fromhex(key_hex)
            else:
                ring = keys if keys is not None else key_ring()
                name = manifest.get('key_id', 'legacy')
                if name not in ring: raise ValueError('Backup decrypt key unavailable')
                key = ring[name]
                if isinstance(key, str): key = bytes.fromhex(key)
            nonce = source.read(12)
            source.seek(-16, os.SEEK_END); tag = source.read(16)
            source.seek(size + 16)
            remaining = total_size - size - 32
            decryptor = Cipher(algorithms.AES(key), modes.GCM(nonce, tag)).decryptor()
            decryptor.authenticate_additional_data(header)
            digest, plaintext_size = hashlib.sha256(), 0
            with target.open('xb') as output:
                owned = True; os.chmod(target, 0o600)
                while remaining:
                    chunk = source.read(min(CHUNK_SIZE, remaining))
                    if not chunk: raise ValueError('Truncated backup ciphertext')
                    remaining -= len(chunk)
                    plaintext = decryptor.update(chunk)
                    output.write(plaintext); digest.update(plaintext); plaintext_size += len(plaintext)
                # GCM plaintext is untrusted until this call succeeds.
                final = decryptor.finalize()
                output.write(final); digest.update(final); plaintext_size += len(final)
            if digest.hexdigest() != manifest['sha256'] or plaintext_size != manifest['size']:
                raise RuntimeError('Snapshot hash or size mismatch')
            return manifest
    except BaseException:
        if owned: target.unlink(missing_ok=True)
        raise

def s3_addressing_style(value):
    """Translate Railway's URL-style alias to botocore's accepted values."""
    style = value.strip().lower()
    if style == 'virtual-host':
        style = 'virtual'
    if style not in ('auto', 'virtual', 'path'):
        raise ValueError(
            'ENGINE_BACKUP_S3_URL_STYLE must be auto, virtual, path, or virtual-host'
        )
    return style

def backup_once(db_path, game, bucket, prefix):
    from boto3 import client
    from botocore.config import Config
    addressing_style = s3_addressing_style(
        os.environ.get('ENGINE_BACKUP_S3_URL_STYLE', 'virtual')
    )
    key_id, key = active_key()
    source = Path(db_path)
    if not source.is_absolute() or not source.is_file():
        raise ValueError('Engine database must exist at an absolute path')
    with tempfile.TemporaryDirectory() as directory:
        snapshot = Path(directory) / 'snapshot.sqlite'
        with closing(sqlite3.connect(f'file:{source}?mode=ro', uri=True, timeout=30)) as live:
            with closing(sqlite3.connect(snapshot)) as destination:
                live.backup(destination, pages=128, sleep=0.1)
                if destination.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise RuntimeError('Snapshot integrity check failed')
        identity = snapshot_identity(snapshot)
        manifest = {'game': game, 'created_at': int(time.time()),
                    'sha256': file_sha256(snapshot),
                    'size': snapshot.stat().st_size, 'format': 'sqlite-online-backup-v1',
                    'key_id': key_id, 'deployment_identity': identity}
        payload = Path(directory) / 'archive.aesgcm'
        ciphertext_sha256 = encrypt_snapshot(snapshot, payload, manifest, key)
        snapshot.unlink()
        key_name = f"{prefix.rstrip('/')}/{game}/{manifest['created_at']}-{manifest['sha256'][:16]}-{os.urandom(8).hex()}.aesgcm"
        storage = client('s3', endpoint_url=os.environ['ENGINE_BACKUP_S3_ENDPOINT'],
                         aws_access_key_id=os.environ['ENGINE_BACKUP_S3_ACCESS_KEY_ID'],
                         aws_secret_access_key=os.environ['ENGINE_BACKUP_S3_SECRET_ACCESS_KEY'],
                         region_name=os.environ.get('ENGINE_BACKUP_S3_REGION', 'auto'),
                         config=Config(s3={'addressing_style': addressing_style}))
        with payload.open('rb') as body:
            storage.put_object(Bucket=bucket, Key=key_name, Body=body,
                               Metadata={'sha256': manifest['sha256'], 'game': game})
        payload.unlink()
        downloaded = Path(directory) / 'remote.aesgcm'
        readback = download_to_file(storage, bucket, key_name, downloaded)
        if readback['sha256'] != ciphertext_sha256:
            raise RuntimeError('Remote backup readback mismatch')
        restore_verify(downloaded, key.hex())
        downloaded.unlink()
        result = {'object': key_name, 'manifest': manifest, 'ciphertext_sha256': ciphertext_sha256, 'encrypted_size_bytes': readback['size'], 'key_id': key_id, 'verified': True}
        if os.getenv('ENGINE_BACKUP_RETENTION_ENABLED') == 'true':
            result['retention'] = run_retention(storage, bucket, game, result)
        return result

def run_retention(storage, bucket, game, current):
    try: from .native_retention import enforce_retention, probe_conditional_deletion
    except ImportError: from native_retention import enforce_retention, probe_conditional_deletion
    identity=current['manifest'].get('deployment_identity')
    def list_page(token):
        response=storage.list_objects_v2(Bucket=bucket,Prefix='native/'+game+'/',MaxKeys=1000,**({'ContinuationToken':token} if token else {}))
        if response.get('IsTruncated') and not response.get('NextContinuationToken'):raise RuntimeError('RETENTION_INVENTORY_INVALID')
        return {'keys':[r['Key'] for r in response.get('Contents',[])],'next_token':response.get('NextContinuationToken') if response.get('IsTruncated') else None}
    def download(key):
        directory = tempfile.TemporaryDirectory(prefix='native-retention-download-')
        try:
            path = Path(directory.name) / 'archive.aesgcm'
            response = download_to_file(storage, bucket, key, path)
            return {'path': path, 'etag': response['etag'], 'cleanup': directory.cleanup}
        except BaseException:
            directory.cleanup(); raise
    def download_probe(key):
        response = storage.get_object(Bucket=bucket, Key=key)
        try:
            payload = response['Body'].read(8193)
            if len(payload) > 8192: raise RuntimeError('RETENTION_PROBE_CONTENT_CHANGED')
            return {'bytes': payload, 'etag': response.get('ETag')}
        finally:
            response['Body'].close()
    def verify(payload):
        with tempfile.TemporaryDirectory() as directory:
            return restore_to_path(payload,Path(directory)/'verify.sqlite',expected_identity=identity)
    return enforce_retention(game=game,identity=identity,current_object=current['object'],current_ciphertext_sha256=current['ciphertext_sha256'],
        list_page=list_page,download=download,remove=lambda key,etag:storage.delete_object(Bucket=bucket,Key=key,IfMatch=etag),verify=verify,
        restoring_object=os.getenv('ENGINE_RESTORE_OBJECT_KEY') or os.getenv('ENGINE_RESTORE_OBJECT'),
        mode=os.getenv('ENGINE_BACKUP_RETENTION_MODE','dry-run'),max_deletes=int(os.getenv('ENGINE_BACKUP_RETENTION_MAX_DELETES','5')),
        probe_requested=os.getenv('ENGINE_BACKUP_RETENTION_PROBE')=='true',
        check_conditional_delete=lambda:probe_conditional_deletion(game=game,identity=identity,
            put=lambda key,payload:{'etag':storage.put_object(Bucket=bucket,Key=key,Body=payload,Metadata={'purpose':'retention-capability-probe'}).get('ETag')},
            download=download_probe,head=lambda key:storage.head_object(Bucket=bucket,Key=key),
            remove=lambda key,etag:storage.delete_object(Bucket=bucket,Key=key,IfMatch=etag)),
        logger=lambda event:print(json.dumps(event),flush=True))


def key_ring(env=None):
    env = os.environ if env is None else env
    try: keys = json.loads(env.get('ENGINE_BACKUP_KEYS_JSON', '{}'))
    except (ValueError, TypeError): raise ValueError('Invalid backup key ring') from None
    if not isinstance(keys, dict): raise ValueError('Backup key ring must be an object')
    if env.get('ENGINE_BACKUP_KEY_HEX'): keys.setdefault('legacy', env['ENGINE_BACKUP_KEY_HEX'])
    if not keys or any(not re.fullmatch(r'[A-Za-z0-9._-]{1,64}', name) or not isinstance(value, str) or not re.fullmatch(r'[0-9a-fA-F]{64}', value) for name, value in keys.items()):
        raise ValueError('Backup key ring must contain named 32-byte keys')
    return {name: bytes.fromhex(value) for name, value in keys.items()}


def active_key(env=None):
    env = os.environ if env is None else env
    keys = key_ring(env); name = env.get('ENGINE_BACKUP_ACTIVE_KEY_ID', 'legacy')
    if name not in keys: raise ValueError('Active backup key ID missing from key ring')
    return name, keys[name]


def snapshot_identity(path):
    with closing(sqlite3.connect(Path(path).as_uri() + '?mode=ro', uri=True)) as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='native_deployment_identity'").fetchone(): return None
        row = db.execute('SELECT identity_json FROM native_deployment_identity WHERE singleton=1').fetchone()
        return json.loads(row[0]) if row else None


def decrypt_payload(payload, key_hex=None, *, keys=None):
    """Byte compatibility helper; production restore uses decrypt_to_file."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    size = int.from_bytes(payload[:4], 'big')
    if not 1 <= size <= 8192 or len(payload) < size + 32:
        raise ValueError('Invalid backup manifest length')
    header = payload[4:4 + size]; manifest = json.loads(header)
    if not isinstance(manifest, dict): raise ValueError('Invalid backup manifest')
    if key_hex is not None: key = bytes.fromhex(key_hex)
    else:
        ring = keys if keys is not None else key_ring()
        name = manifest.get('key_id', 'legacy')
        if name not in ring: raise ValueError('Backup decrypt key unavailable')
        key = ring[name]
        if isinstance(key, str): key = bytes.fromhex(key)
    nonce = payload[4 + size:16 + size]
    plaintext = AESGCM(key).decrypt(nonce, payload[16 + size:], header)
    if hashlib.sha256(plaintext).hexdigest() != manifest['sha256'] or len(plaintext) != manifest['size']:
        raise RuntimeError('Snapshot hash or size mismatch')
    return manifest, plaintext


def restore_to_path(payload, destination, key_hex=None, *, keys=None, expected_identity=None):
    """Restore only into an absent database. Existing files/WAL are never replaced."""
    target = Path(destination)
    if not target.is_absolute(): raise ValueError('Absolute restore destination required')
    if any(Path(str(target) + suffix).exists() for suffix in ('', '-wal', '-shm')):
        raise FileExistsError('Restore destination must be empty')
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=target.parent, prefix='.native-restore-') as directory:
        verified = Path(directory) / 'verified.sqlite'
        manifest = decrypt_to_file(payload, verified, key_hex, keys=keys)
        if expected_identity is not None and manifest.get('deployment_identity') != expected_identity:
            raise RuntimeError('BACKUP_DEPLOYMENT_IDENTITY_MISMATCH')
        with closing(sqlite3.connect(verified.as_uri() + '?mode=ro', uri=True)) as db:
            if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok': raise RuntimeError('Restored database integrity check failed')
        if expected_identity is not None and snapshot_identity(verified) != expected_identity:
            raise RuntimeError('RESTORED_DEPLOYMENT_IDENTITY_MISMATCH')
        with verified.open('rb') as stream: os.fsync(stream.fileno())
        # link is atomic and fails if another process created the target.
        os.link(verified, target)
        descriptor = os.open(target.parent, os.O_RDONLY)
        try: os.fsync(descriptor)
        finally: os.close(descriptor)
    return manifest


def restore_verify(payload, key_hex=None, *, keys=None):
    with tempfile.TemporaryDirectory() as directory:
        return restore_to_path(payload, Path(directory) / 'restored.sqlite', key_hex, keys=keys)


def restore_from_remote(destination, game, expected_identity):
    """Explicit startup recovery on a fresh replacement volume only."""
    if any(os.getenv(name) for name in ('RAILWAY_PROJECT_ID','RAILWAY_SERVICE_ID','RAILWAY_DEPLOYMENT_ID')):
        mount = os.getenv('RAILWAY_VOLUME_MOUNT_PATH','')
        if not mount or not Path(mount).is_absolute() or not Path(mount).is_dir():
            raise RuntimeError('PERSISTENT_NATIVE_VOLUME_REQUIRED')
    object_name = os.getenv('ENGINE_RESTORE_OBJECT_KEY') or os.getenv('ENGINE_RESTORE_OBJECT')
    if not object_name: return None
    expected_hash = os.getenv('ENGINE_RESTORE_CIPHERTEXT_SHA256', '')
    if not re.fullmatch(r'[a-f0-9]{64}', expected_hash):
        raise RuntimeError('Expected restore ciphertext SHA-256 required')
    if os.getenv('ENGINE_RESTORE_CONFIRM_DEPLOYMENT_ID') != expected_identity['deployment_id']:
        raise RuntimeError('Explicit restore deployment confirmation required')
    if not object_name.startswith('native/' + game + '/') or not re.fullmatch(r'native/[a-z]+/[A-Za-z0-9._-]+', object_name):
        raise ValueError('Invalid restore object scope')
    target = Path(destination)
    marker = target.parent / '.native-restore.json'
    expected_marker = {'object':object_name,'ciphertext_sha256':expected_hash,'deployment_identity':expected_identity}
    if target.exists():
        try: recorded = json.loads(marker.read_text())
        except (OSError, ValueError): raise RuntimeError('Restore requested on unmarked existing database') from None
        if recorded != expected_marker or snapshot_identity(target) != expected_identity:
            raise RuntimeError('Existing restored database identity or marker mismatch')
        return None
    target.parent.mkdir(parents=True, exist_ok=True)
    if any(p.name != 'lost+found' for p in target.parent.iterdir()):
        raise RuntimeError('Restore requires an empty replacement volume')
    from boto3 import client
    from botocore.config import Config
    storage = client('s3', endpoint_url=os.environ['ENGINE_BACKUP_S3_ENDPOINT'],
                     aws_access_key_id=os.environ['ENGINE_BACKUP_S3_ACCESS_KEY_ID'],
                     aws_secret_access_key=os.environ['ENGINE_BACKUP_S3_SECRET_ACCESS_KEY'],
                     region_name=os.environ.get('ENGINE_BACKUP_S3_REGION', 'auto'),
                     config=Config(s3={'addressing_style': s3_addressing_style(os.getenv('ENGINE_BACKUP_S3_URL_STYLE', 'virtual'))}))
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix='native-startup-download-') as directory:
        payload = Path(directory) / 'archive.aesgcm'
        response = download_to_file(storage, os.environ['ENGINE_BACKUP_S3_BUCKET'], object_name, payload)
        if response['sha256'] != expected_hash:
            raise RuntimeError('Remote restore ciphertext hash mismatch')
        manifest = restore_to_path(payload, destination, expected_identity=expected_identity)
    with marker.open('x') as stream:
        os.chmod(marker, 0o600)
        stream.write(json.dumps(expected_marker, sort_keys=True)); stream.flush(); os.fsync(stream.fileno())
    descriptor = os.open(target.parent, os.O_RDONLY)
    try: os.fsync(descriptor)
    finally: os.close(descriptor)
    print(json.dumps({'event':'engine.restore.completed','game':game,'object':object_name,
                      'snapshot_created_at':manifest['created_at'],'ciphertext_sha256':expected_hash,
                      'rto_restore_seconds':round(time.monotonic()-started,6)}), flush=True)
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
