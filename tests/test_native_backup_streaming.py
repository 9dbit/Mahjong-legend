"""Wire compatibility and fail-closed streaming restore, independent of game math."""
import base64
import hashlib
import io
import json
import os
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from tools import native_backup as backup

GAME = 'mahjong'
IDENTITY = {'environment':'preproduction','deployment_id':'native-stream-fixture','core_deployment_id':'core-stream-fixture','game_id':'mahjong-wild','identity_version':1}
KEY = bytes.fromhex('52' * 32)


def archive(tmp_path, *, manifest_override=None):
    source = tmp_path / 'source.sqlite'
    with sqlite3.connect(source) as db:
        db.execute('CREATE TABLE native_deployment_identity(singleton INTEGER PRIMARY KEY, identity_json TEXT)')
        db.execute('INSERT INTO native_deployment_identity VALUES(1,?)', (json.dumps(IDENTITY),))
        db.execute('CREATE TABLE rounds(id TEXT PRIMARY KEY,state TEXT,payout TEXT,payload BLOB)')
        db.execute("INSERT INTO rounds VALUES('settled','settled','42',zeroblob(2097153))")
        db.execute("INSERT INTO rounds VALUES('pending','intent','17',NULL)")
    manifest = {'game':GAME,'created_at':1794312000,'sha256':backup.file_sha256(source),'size':source.stat().st_size,'format':'sqlite-online-backup-v1','key_id':'old','deployment_identity':IDENTITY}
    manifest.update(manifest_override or {})
    payload = tmp_path / 'archive.aesgcm'
    # Valid authenticated fixtures with deliberately incorrect metadata are built
    # using the old one-shot producer, independently of the new stream writer.
    header = json.dumps(manifest, sort_keys=True, separators=(',', ':')).encode()
    nonce = bytes.fromhex('31' * 12)
    payload.write_bytes(len(header).to_bytes(4,'big') + header + nonce + AESGCM(KEY).encrypt(nonce, source.read_bytes(), header))
    return source, payload, manifest, nonce


def test_streamed_archive_is_byte_exact_with_existing_v1_producer_and_consumers(tmp_path):
    source, old_archive, manifest, nonce = archive(tmp_path)
    produced = tmp_path / 'streamed.aesgcm'
    checksum = backup.encrypt_snapshot(source, produced, manifest, KEY, nonce=nonce)
    assert produced.read_bytes() == old_archive.read_bytes()
    assert checksum == hashlib.sha256(old_archive.read_bytes()).hexdigest()
    old_manifest, plaintext = backup.decrypt_payload(produced.read_bytes(), KEY.hex())
    assert old_manifest == manifest and plaintext == source.read_bytes()
    restored = tmp_path / 'replacement' / 'native.sqlite'
    assert backup.restore_to_path(produced, restored, keys={'old':KEY}, expected_identity=IDENTITY) == manifest
    with sqlite3.connect(restored) as db:
        assert db.execute('SELECT id,state,payout FROM rounds ORDER BY id').fetchall() == [('pending','intent','17'),('settled','settled','42')]
    assert restored.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize('fault', ['tag','ciphertext','header','truncated','appended','manifest-hash','manifest-size'])
def test_untrusted_plaintext_is_removed_before_sqlite_or_publication(tmp_path, fault):
    overrides = {'sha256':'f'*64} if fault == 'manifest-hash' else {'size':1} if fault == 'manifest-size' else None
    _, payload, _, _ = archive(tmp_path, manifest_override=overrides)
    body = bytearray(payload.read_bytes())
    if fault == 'tag': body[-1] ^= 1
    elif fault == 'ciphertext': body[-100] ^= 1
    elif fault == 'header':
        i = body.index(b'preproduction'); body[i] = ord('x')
    elif fault == 'truncated': body = body[:-1]
    elif fault == 'appended': body += b'x'
    payload.write_bytes(body)
    destination = tmp_path / 'replacement' / 'native.sqlite'
    with patch.object(backup.sqlite3, 'connect', side_effect=AssertionError('SQLite must not see unauthenticated data')):
        with pytest.raises((InvalidTag, ValueError, RuntimeError)):
            backup.restore_to_path(payload, destination, keys={'old':KEY}, expected_identity=IDENTITY)
    assert not destination.exists()
    assert list(destination.parent.iterdir()) == []


@pytest.mark.parametrize('fault', ['foreign-manifest','foreign-database','unknown-key'])
def test_valid_archive_still_requires_key_and_exact_immutable_identity(tmp_path, fault):
    different = {**IDENTITY,'deployment_id':'foreign-stream-fixture'}
    override = {'deployment_identity':different} if fault == 'foreign-manifest' else None
    _, payload, manifest, _ = archive(tmp_path, manifest_override=override)
    destination = tmp_path / 'replacement' / 'native.sqlite'
    expected = different if fault == 'foreign-database' else IDENTITY
    if fault == 'foreign-database':
        # The caller expects a foreign identity and an authenticated manifest
        # agrees, but the actual SQLite identity stays original.
        source = tmp_path / 'source.sqlite'
        manifest['deployment_identity'] = different
        payload.unlink()
        backup.encrypt_snapshot(source, payload, manifest, KEY)
    with pytest.raises((ValueError, RuntimeError)):
        backup.restore_to_path(payload, destination, keys={} if fault=='unknown-key' else {'old':KEY}, expected_identity=expected)
    assert not destination.exists()
    assert list(destination.parent.iterdir()) == []


@pytest.mark.parametrize('suffix', ['', '-wal', '-shm'])
def test_streaming_restore_never_overwrites_existing_database_or_journal(tmp_path, suffix):
    _, payload, _, _ = archive(tmp_path)
    destination = tmp_path / 'replacement.sqlite'
    occupied = Path(str(destination) + suffix); occupied.write_bytes(b'preserve-existing-data')
    with pytest.raises(FileExistsError):
        backup.restore_to_path(payload, destination, keys={'old':KEY}, expected_identity=IDENTITY)
    assert occupied.read_bytes() == b'preserve-existing-data'


def test_cryptography47_legacy_file_restores_with_streaming_reader(tmp_path):
    fixture = json.loads((Path(__file__).parent / 'fixtures/native-backup-cryptography47.json').read_text())
    payload = tmp_path / 'legacy.aesgcm'; payload.write_bytes(base64.b64decode(fixture['ciphertext_base64']))
    destination = tmp_path / 'legacy.sqlite'
    manifest = backup.restore_to_path(payload, destination, key_hex=fixture['public_test_key_hex'])
    assert manifest['sha256'] == fixture['plaintext_sha256']


@pytest.mark.parametrize('fail', [False, True])
def test_download_is_chunk_bounded_and_closes_remote_stream_on_failure(tmp_path, fail):
    data = b'x' * (backup.CHUNK_SIZE * 3 + 29)
    class Body(io.BytesIO):
        calls = 0
        def read(self, amount=-1):
            assert 0 < amount <= backup.CHUNK_SIZE
            self.calls += 1
            if fail and self.calls == 2: raise OSError('injected transport failure')
            return super().read(amount)
    body = Body(data)
    class Storage:
        def get_object(self, **kwargs): return {'Body':body,'ETag':'"fixture-etag"'}
    target = tmp_path / 'download.aesgcm'
    if fail:
        with pytest.raises(OSError): backup.download_to_file(Storage(), 'fixture', 'archive', target)
    else:
        result = backup.download_to_file(Storage(), 'fixture', 'archive', target)
        assert result == {'sha256':hashlib.sha256(data).hexdigest(),'size':len(data),'etag':'"fixture-etag"'}
        assert target.read_bytes() == data
    assert body.closed


def test_failed_encryptor_does_not_publish_a_backup_when_snapshot_hash_disagrees(tmp_path):
    source, _, manifest, _ = archive(tmp_path)
    with pytest.raises(RuntimeError, match='Snapshot changed'):
        backup.encrypt_snapshot(source, tmp_path/'bad.aesgcm', {**manifest,'sha256':'0'*64}, KEY)



def test_full_backup_and_retention_memory_stays_bounded_as_snapshot_doubles():
    import subprocess, sys
    if sys.platform != 'linux': pytest.skip('RSS regression uses Linux resource metrics')
    script = Path(backup.__file__).with_name('benchmark_native_backup_memory.py')
    results = []
    for size in (64, 128):
        run = subprocess.run([sys.executable, str(script), '--mib', str(size), '--retention'], check=True, text=True, capture_output=True, timeout=60)
        result = json.loads(run.stdout)
        assert result['verified'] and result['retention_verified']
        assert result['incremental_peak_kib'] < 96 * 1024, result
        results.append(result)
    assert abs(results[1]['incremental_peak_kib'] - results[0]['incremental_peak_kib']) < 32 * 1024, results


def test_seekable_upload_and_streamed_readback_use_real_boto3_http_transport(tmp_path, monkeypatch):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread
    from urllib.parse import urlsplit, unquote
    source, _, _, _ = archive(tmp_path)
    objects = {}; uploads = []; downloads = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def key(self): return unquote(urlsplit(self.path).path)
        def do_PUT(self):
            length = int(self.headers['Content-Length'])
            target = tmp_path / ('remote-' + str(len(objects)))
            remaining = length
            with target.open('wb') as output:
                while remaining:
                    chunk = self.rfile.read(min(65536, remaining))
                    if not chunk: raise RuntimeError('Incomplete fixture upload')
                    output.write(chunk); remaining -= len(chunk)
            objects[self.key()] = target; uploads.append(length)
            self.send_response(200); self.send_header('Content-Length','0'); self.end_headers()
        def do_GET(self):
            path = objects.get(self.key())
            if path is None:
                self.send_error(404); return
            self.send_response(200); self.send_header('Content-Length',str(path.stat().st_size)); self.end_headers()
            with path.open('rb') as source:
                while chunk := source.read(65536): self.wfile.write(chunk)
            downloads.append(path.stat().st_size)
    server = ThreadingHTTPServer(('127.0.0.1',0), Handler)
    worker = Thread(target=server.serve_forever, daemon=True); worker.start()
    settings = {'ENGINE_BACKUP_KEY_HEX':KEY.hex(),'ENGINE_BACKUP_KEYS_JSON':'{}','ENGINE_BACKUP_ACTIVE_KEY_ID':'legacy','ENGINE_BACKUP_RETENTION_ENABLED':'false','ENGINE_BACKUP_S3_ENDPOINT':f'http://127.0.0.1:{server.server_port}','ENGINE_BACKUP_S3_URL_STYLE':'path','ENGINE_BACKUP_S3_ACCESS_KEY_ID':'fixture','ENGINE_BACKUP_S3_SECRET_ACCESS_KEY':'fixture','ENGINE_BACKUP_S3_REGION':'us-east-1'}
    for key, value in settings.items(): monkeypatch.setenv(key, value)
    try:
        result = backup.backup_once(str(source), GAME, 'fixture', 'native')
        assert result['verified']
        assert len(uploads) == len(downloads) == 1 and uploads == downloads
        remote = next(iter(objects.values()))
        assert backup.file_sha256(remote) == result['ciphertext_sha256']
    finally:
        server.shutdown(); server.server_close(); worker.join(timeout=5)
