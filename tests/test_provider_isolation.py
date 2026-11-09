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
    db=identity.open_bound_database(isolated,'mahjong-wild')
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
    good={'environment':'preproduction','deployment_id':'core-test-deployment'}
    identity.validate_redeemed(good,'mahjong-wild',isolated)
    for bad in ({},dict(good,environment='sandbox'),dict(good,deployment_id='different-core')):
        with pytest.raises(HTTPException):identity.validate_redeemed(bad,'mahjong-wild',isolated)
    monkeypatch.setenv('AGENCY_ENVIRONMENT','production')
    with pytest.raises(HTTPException) as exc:identity.require_play()
    assert exc.value.status_code==423
    wallet=AgencyWallet('https://core.example','engine-key','q'*40)
    with pytest.raises(AgencyWalletError) as exc:wallet.request('redeem',{'request_id':'r','token':'x'*48})
    assert exc.value.status==423

def test_v2_transport_binds_exact_body_environment_audience(isolated):
    wallet=AgencyWallet('https://core.example','engine-key','q'*40)
    class Response:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def read(self):return b'{"ok":true}'
    with patch.object(wallet.opener,'open',return_value=Response()) as opened:
        assert wallet.request('redeem',{'request_id':'r','token':'x'*48})=={'ok':True}
    request=opened.call_args.args[0];headers={k.lower():v for k,v in request.header_items()}
    assert headers['x-agency-version']=='2' and headers['x-agency-environment']=='preproduction'
    assert headers['x-agency-audience']=='core-test-deployment'
    message='\n'.join(('agency.v2','preproduction','core-test-deployment','POST','/api/v4/agency-game/redeem',headers['x-agency-timestamp'],headers['x-agency-nonce'],hashlib.sha256(request.data).hexdigest()))
    assert headers['x-agency-signature']==hmac.new(('q'*40).encode(),message.encode(),'sha256').hexdigest()
    assert headers['x-agency-signature']!=hmac.new(('q'*40).encode(),message.replace('preproduction','sandbox').encode(),'sha256').hexdigest()
