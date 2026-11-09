import hashlib, hmac, json, sqlite3
from pathlib import Path
from unittest.mock import patch
import pytest
from fastapi import HTTPException
import deployment_identity as identity
from agency_wallet import AgencyWallet, AgencyWalletError

@pytest.fixture
def isolated(tmp_path,monkeypatch):
    monkeypatch.setenv('AGENCY_ENVIRONMENT','preproduction')
    monkeypatch.setenv('AGENCY_DEPLOYMENT_ID','native-test-deployment')
    monkeypatch.setenv('AGENCY_CORE_DEPLOYMENT_ID','core-test-deployment')
    monkeypatch.setenv('AGENCY_WALLET_SECRET','q'*40)
    return tmp_path/'native.sqlite'

def test_identity_immutable_wrong_environment_does_not_write(isolated,monkeypatch):
    db=identity.initialize_bound_database(isolated,'mahjong-wild')
    for sql in ("DELETE FROM native_deployment_identity", "UPDATE native_deployment_identity SET identity_json='{}'", "INSERT OR REPLACE INTO native_deployment_identity VALUES(1,'{}')"):
        with pytest.raises(sqlite3.IntegrityError): db.execute(sql)
    db.close();before=isolated.read_bytes()
    monkeypatch.setenv('AGENCY_ENVIRONMENT','production')
    with pytest.raises(RuntimeError,match='IDENTITY_MISMATCH'): identity.open_bound_database(isolated,'mahjong-wild')
    assert isolated.read_bytes()==before

def test_legacy_db_cannot_be_adopted_as_preproduction(isolated):
    db=sqlite3.connect(isolated);db.execute('CREATE TABLE old_sessions(id TEXT)');db.close()
    before=isolated.read_bytes()
    with pytest.raises(RuntimeError,match='UNBOUND_DATABASE'):identity.open_bound_database(isolated,'mahjong-wild')
    assert isolated.read_bytes()==before

def test_volume_escape_and_cookie_scope(isolated,tmp_path,monkeypatch):
    mount=tmp_path/'mount';mount.mkdir();outside=tmp_path/'outside';outside.mkdir();(mount/'link').symlink_to(outside,target_is_directory=True)
    monkeypatch.setenv('RAILWAY_VOLUME_MOUNT_PATH',str(mount))
    with pytest.raises(RuntimeError,match='escapes'): identity.open_bound_database(mount/'link'/'bad.sqlite','mahjong-wild')
    a=identity.cookie_value('x'*48,'mahjong-wild',isolated)
    monkeypatch.setenv('AGENCY_ENVIRONMENT','production')
    b=identity.cookie_value('x'*48,'mahjong-wild',isolated)
    assert a!=b

def test_redeemed_scope_and_production_quarantine(isolated,monkeypatch):
    good={'provider':'soft-tech','game':'mahjong-wild','environment':'preproduction','deployment_id':'core-test-deployment'}
    identity.validate_redeemed(good,'mahjong-wild',isolated)
    for bad in ({},dict(good,environment='sandbox'),dict(good,deployment_id='different-core'),dict(good,provider='foreign'),dict(good,game='wrong-game')):
        with pytest.raises(HTTPException):identity.validate_redeemed(bad,'mahjong-wild',isolated)
    monkeypatch.setenv('AGENCY_ENVIRONMENT','production')
    with pytest.raises(HTTPException) as exc:identity.require_play()
    assert exc.value.status_code==423
    wallet=AgencyWallet('https://core.example','engine-key','q'*40)
    with pytest.raises(AgencyWalletError) as exc:wallet.request('redeem',{'request_id':'r','token':'x'*48})
    assert exc.value.status==423

def test_v2_transport_binds_exact_body_environment_audience(isolated):
    wallet=AgencyWallet('https://core.example','engine-key','q'*40)
    with patch.object(wallet.transport,'post',return_value={'ok':True}) as posted:
        assert wallet.request('redeem',{'request_id':'r','token':'x'*48})=={'ok':True}
    url,body,sent_headers=posted.call_args.args;headers={k.lower():v for k,v in sent_headers.items()}
    assert url=='https://core.example/api/v4/agency-game/redeem'
    assert headers['x-agency-version']=='2' and headers['x-agency-environment']=='preproduction'
    assert headers['x-agency-audience']=='core-test-deployment'
    message='\n'.join(('agency.v2','preproduction','core-test-deployment','POST','/api/v4/agency-game/redeem',headers['x-agency-timestamp'],headers['x-agency-nonce'],hashlib.sha256(body).hexdigest()))
    assert headers['x-agency-signature']==hmac.new(('q'*40).encode(),message.encode(),'sha256').hexdigest()
    assert headers['x-agency-signature']!=hmac.new(('q'*40).encode(),message.replace('preproduction','sandbox').encode(),'sha256').hexdigest()

@pytest.mark.parametrize('environment',['sandbox','preproduction','production'])
def test_cloud_native_requires_volume_before_creating_database(tmp_path,monkeypatch,environment):
    monkeypatch.setenv('RAILWAY_SERVICE_ID','cloud-native-service')
    monkeypatch.setenv('AGENCY_ENVIRONMENT',environment)
    monkeypatch.setenv('AGENCY_DEPLOYMENT_ID','native-cloud-test')
    monkeypatch.setenv('AGENCY_CORE_DEPLOYMENT_ID','core-cloud-test')
    monkeypatch.delenv('RAILWAY_VOLUME_MOUNT_PATH',raising=False)
    path=tmp_path/'missing-volume'/'native.sqlite'
    with pytest.raises(RuntimeError,match='PERSISTENT_NATIVE_VOLUME_REQUIRED'):
        identity.open_bound_database(path,'mahjong-wild')
    assert not path.parent.exists()


# The request path must preserve the no-write identity boundary while avoiding
# the writer queue. These tests exercise observable SQLite behavior.
from concurrent.futures import ThreadPoolExecutor


def test_request_open_does_not_create_a_missing_database(isolated):
    missing = isolated.parent / 'absent-directory' / 'native.sqlite'
    with pytest.raises(RuntimeError, match='NOT_INITIALIZED'):
        identity.open_bound_database(missing, 'mahjong-wild')
    assert not missing.parent.exists()
    db = identity.initialize_bound_database(isolated, 'mahjong-wild')
    db.close()
    isolated.unlink()
    with pytest.raises(RuntimeError, match='NOT_INITIALIZED'):
        identity.open_bound_database(isolated, 'mahjong-wild')
    assert not isolated.exists()


def test_bound_open_finishes_while_an_unrelated_writer_is_uncommitted(isolated, monkeypatch):
    db = identity.initialize_bound_database(isolated, 'mahjong-wild')
    db.execute('PRAGMA journal_mode=WAL')
    db.execute('CREATE TABLE activity(value INTEGER)')
    db.execute('INSERT INTO activity VALUES(1)')
    db.close()
    original_connect = sqlite3.connect
    blocker = original_connect(isolated, isolation_level=None)
    blocker.execute('BEGIN IMMEDIATE')
    blocker.execute('UPDATE activity SET value=2')
    traced = []; connections = []
    def observed_connect(*args, **kwargs):
        connections.append(str(args[0]))
        result = original_connect(*args, **kwargs)
        result.set_trace_callback(traced.append)
        return result
    monkeypatch.setattr(sqlite3, 'connect', observed_connect)
    def request():
        connection = identity.open_bound_database(isolated, 'mahjong-wild')
        try:
            assert not connection.in_transaction
            assert connection.execute('SELECT value FROM activity').fetchone()[0] == 1
        finally:
            connection.close()
    with ThreadPoolExecutor(max_workers=1) as worker:
        future = worker.submit(request)
        try:
            # A BEGIN IMMEDIATE here would wait for blocker rather than finish.
            future.result(timeout=2)
            assert blocker.in_transaction
        finally:
            blocker.rollback(); blocker.close()
    assert len(connections) == 2
    assert connections[0].endswith('?mode=ro') and connections[1].endswith('?mode=rw')
    assert not any(sql.lstrip().upper().startswith(('BEGIN', 'CREATE', 'INSERT', 'UPDATE', 'DELETE', 'COMMIT')) for sql in traced)


@pytest.mark.parametrize('method', ['open_bound_database', 'initialize_bound_database'])
@pytest.mark.parametrize('tamper', ['missing', 'changed'])
def test_missing_or_changed_guard_fails_before_writable_open(isolated, monkeypatch, method, tamper):
    db = identity.initialize_bound_database(isolated, 'mahjong-wild')
    db.close()
    db = sqlite3.connect(isolated)
    db.execute('DROP TRIGGER native_identity_update')
    if tamper == 'changed':
        db.execute('CREATE TRIGGER native_identity_update BEFORE UPDATE ON native_deployment_identity BEGIN SELECT 1; END')
    db.commit(); db.close()
    before = isolated.read_bytes(); calls = []
    original_connect = sqlite3.connect
    def observed_connect(*args, **kwargs):
        calls.append(str(args[0]))
        return original_connect(*args, **kwargs)
    monkeypatch.setattr(sqlite3, 'connect', observed_connect)
    with pytest.raises(RuntimeError, match='GUARDS_MISMATCH'):
        getattr(identity, method)(isolated, 'mahjong-wild')
    assert calls and all(call.endswith('?mode=ro') for call in calls)
    assert isolated.read_bytes() == before


@pytest.mark.parametrize('method', ['open_bound_database', 'initialize_bound_database'])
def test_wrong_core_identity_fails_before_writable_open(isolated, monkeypatch, method):
    db = identity.initialize_bound_database(isolated, 'mahjong-wild')
    db.close(); before = isolated.read_bytes(); calls = []
    monkeypatch.setenv('AGENCY_CORE_DEPLOYMENT_ID', 'different-core-deployment')
    original_connect = sqlite3.connect
    def observed_connect(*args, **kwargs):
        calls.append(str(args[0]))
        return original_connect(*args, **kwargs)
    monkeypatch.setattr(sqlite3, 'connect', observed_connect)
    with pytest.raises(RuntimeError, match='IDENTITY_MISMATCH'):
        getattr(identity, method)(isolated, 'mahjong-wild')
    assert calls and all(call.endswith('?mode=ro') for call in calls)
    assert isolated.read_bytes() == before


def test_new_identity_and_guards_are_one_atomic_transaction(isolated, monkeypatch):
    original_connect = sqlite3.connect
    class InterruptGuardCreation(sqlite3.Connection):
        def execute(self, sql, *args):
            if sql.startswith('CREATE TRIGGER native_identity_delete'):
                raise sqlite3.OperationalError('injected guard creation interruption')
            return super().execute(sql, *args)
    def interrupted_connect(*args, **kwargs):
        kwargs['factory'] = InterruptGuardCreation
        return original_connect(*args, **kwargs)
    monkeypatch.setattr(sqlite3, 'connect', interrupted_connect)
    with pytest.raises(sqlite3.OperationalError, match='injected'):
        identity.initialize_bound_database(isolated, 'mahjong-wild')
    with original_connect(isolated) as db:
        assert db.execute("SELECT name FROM sqlite_master WHERE name LIKE 'native_identity_%' OR name='native_deployment_identity'").fetchall() == []


def test_legacy_sandbox_adoption_requires_explicit_initializer(isolated, monkeypatch):
    monkeypatch.setenv('AGENCY_ENVIRONMENT', 'sandbox')
    with sqlite3.connect(isolated) as db:
        db.execute('CREATE TABLE old_sessions(id TEXT)')
        db.execute("INSERT INTO old_sessions VALUES('retained')")
    before = isolated.read_bytes()
    with pytest.raises(RuntimeError, match='UNBOUND_DATABASE'):
        identity.open_bound_database(isolated, 'mahjong-wild')
    assert isolated.read_bytes() == before
    db = identity.initialize_bound_database(isolated, 'mahjong-wild')
    assert db.execute('SELECT id FROM old_sessions').fetchone()[0] == 'retained'
    for sql in ('DELETE FROM native_deployment_identity', "UPDATE native_deployment_identity SET identity_json='{}'", "INSERT OR REPLACE INTO native_deployment_identity VALUES(1,'{}')"):
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(sql)
    db.close()


def test_preproduction_initializer_does_not_adopt_existing_application_data(isolated):
    with sqlite3.connect(isolated) as db:
        db.execute('CREATE TABLE old_sessions(id TEXT)')
        db.execute("INSERT INTO old_sessions VALUES('retained')")
    before = isolated.read_bytes()
    with pytest.raises(RuntimeError, match='UNBOUND_DATABASE'):
        identity.initialize_bound_database(isolated, 'mahjong-wild')
    assert isolated.read_bytes() == before


def test_valid_restored_binding_starts_without_recreating_guards(isolated, monkeypatch):
    source = identity.initialize_bound_database(isolated, 'mahjong-wild')
    source.execute('CREATE TABLE preserved_rounds(id TEXT)')
    source.execute("INSERT INTO preserved_rounds VALUES('accepted')")
    restored = isolated.with_name('restored.sqlite')
    target = sqlite3.connect(restored)
    source.backup(target); target.close(); source.close()
    traced = []; original_connect = sqlite3.connect
    def observed_connect(*args, **kwargs):
        connection = original_connect(*args, **kwargs)
        connection.set_trace_callback(traced.append)
        return connection
    monkeypatch.setattr(sqlite3, 'connect', observed_connect)
    db = identity.initialize_bound_database(restored, 'mahjong-wild')
    assert db.execute('SELECT id FROM preserved_rounds').fetchone()[0] == 'accepted'
    db.close()
    assert not any(sql.lstrip().upper().startswith(('BEGIN', 'CREATE', 'INSERT', 'UPDATE', 'DELETE')) for sql in traced)


def test_each_connection_rechecks_persisted_identity(isolated):
    db = identity.initialize_bound_database(isolated, 'mahjong-wild')
    trigger = db.execute("SELECT sql FROM sqlite_master WHERE name='native_identity_update'").fetchone()[0]
    stored = json.loads(db.execute('SELECT identity_json FROM native_deployment_identity').fetchone()[0])
    db.close()
    checked = identity.open_bound_database(isolated, 'mahjong-wild'); checked.close()
    # Simulate a differently bound restore with its immutable guards still valid.
    with sqlite3.connect(isolated) as db:
        db.execute('DROP TRIGGER native_identity_update')
        stored['core_deployment_id'] = 'different-restored-core'
        db.execute('UPDATE native_deployment_identity SET identity_json=?', (json.dumps(stored),))
        db.execute(trigger)
    before = isolated.read_bytes()
    with pytest.raises(RuntimeError, match='IDENTITY_MISMATCH'):
        identity.open_bound_database(isolated, 'mahjong-wild')
    assert isolated.read_bytes() == before
