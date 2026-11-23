import json,uuid
from decimal import ROUND_HALF_UP
import pytest
from fastapi import HTTPException
import agency_runtime as m

@pytest.fixture
def native(tmp_path,monkeypatch):
 monkeypatch.setenv('AGENCY_WALLET_MODE','sandbox');monkeypatch.setenv('MAHJONG_AGENCY_DB_PATH',str(tmp_path/'wallet.sqlite'))
 monkeypatch.setattr(m,'wallet',lambda:object());m.init();db=m.connect()
 yield db
 db.close()

def test_precision():
 assert m.units('0.5',0,ROUND_HALF_UP)=='1'
 assert m.units('0.499999',0,ROUND_HALF_UP)=='0'
 assert m.units('9007199254740993',0)=='9007199254740993'
 with pytest.raises(HTTPException):m.units('0.5',0)

def test_durable_recovery(native,monkeypatch):
 db=native;s={'tenant_id':'t','player_id':'p','session_id':'s','coin_scale':0};actor='t:p';rounds={};balance=1000;fail=['reserve','settle'];generated=0
 original=m.play_round
 def outcome(*args):
  nonlocal generated
  generated+=1;return original(*args)
 monkeypatch.setattr(m,'play_round',outcome)
 def remote(action,p):
  nonlocal balance
  if action=='status':return {'balance':str(balance),'reserved':'0'}
  if action=='reserve':
   rid=p['round_ref']
   if rid not in rounds:rounds[rid]={'id':rid,**p};balance-=int(p['stake'])
   if action in fail:fail.remove(action);raise HTTPException(503,'lost reserve response')
   return rounds[rid]
  if action=='settle':
   r=rounds[p['round_id']]
   if not r.get('settled'):r['settled']=True;balance+=int(p['payout'])
   if action in fail:fail.remove(action);raise HTTPException(503,'lost settle response')
   return {'ok':True}
 monkeypatch.setattr(m,'remote',remote)
 st=m.state(db,s,actor);assert st['bet_options']==['1','2','5','10']
 p={'ticket_id':st['ticket']['id'],'idempotency_key':str(uuid.uuid4()),'bet':'1'}
 with pytest.raises(HTTPException):m.spin(db,s,actor,{**p,'payout':'9999'})
 assert generated==0
 with pytest.raises(HTTPException):m.spin(db,s,actor,p)
 assert generated==1 and balance==999
 # Close/reopen the connection to simulate process loss of all in-memory state.
 db.close();db=m.connect()
 with pytest.raises(HTTPException):m.spin(db,s,actor,p)
 db.close();db=m.connect();a=m.spin(db,s,actor,p);b=m.spin(db,s,actor,p)
 assert a==b and generated==1 and len(rounds)==1
 assert balance==999+int(a['settlement']['payout_minor'])
 with pytest.raises(HTTPException):m.spin(db,s,actor,{**p,'bet':'2'})
 assert m.verify_round(a['round'],m.GameConfig())['valid']
 db.close()

def test_production_native_wallet_refuses_missing_volume(tmp_path,monkeypatch):
    monkeypatch.setenv('STUDIO_PRODUCTION','1')
    monkeypatch.setenv('MAHJONG_AGENCY_DB_PATH',str(tmp_path/'agency.sqlite3'))
    monkeypatch.delenv('RAILWAY_VOLUME_MOUNT_PATH',raising=False)
    with pytest.raises(RuntimeError,match='persistent Railway volume'):
        m.checked_storage_path()
    assert not (tmp_path/'agency.sqlite3').exists()


def test_production_native_wallet_refuses_db_outside_volume(tmp_path,monkeypatch):
    volume=tmp_path/'volume'
    volume.mkdir()
    monkeypatch.setenv('STUDIO_PRODUCTION','1')
    monkeypatch.setenv('RAILWAY_VOLUME_MOUNT_PATH',str(volume))
    monkeypatch.setenv('MAHJONG_AGENCY_DB_PATH',str(tmp_path/'outside.sqlite3'))
    with pytest.raises(RuntimeError,match='inside its persistent volume'):
        m.checked_storage_path()


def test_production_native_wallet_refuses_unmounted_directory(tmp_path,monkeypatch):
    volume=tmp_path/'not-a-real-mount'
    volume.mkdir()
    monkeypatch.setenv('STUDIO_PRODUCTION','1')
    monkeypatch.setenv('RAILWAY_VOLUME_MOUNT_PATH',str(volume))
    monkeypatch.setenv('MAHJONG_AGENCY_DB_PATH',str(volume/'agency.sqlite3'))
    monkeypatch.setattr(m.os.path,'ismount',lambda p:False)
    with pytest.raises(RuntimeError,match='not mounted'):
        m.checked_storage_path()


def test_production_native_wallet_accepts_mounted_volume(tmp_path,monkeypatch):
    volume=tmp_path/'persistent'
    volume.mkdir()
    monkeypatch.setenv('STUDIO_PRODUCTION','1')
    monkeypatch.setenv('RAILWAY_VOLUME_MOUNT_PATH',str(volume))
    monkeypatch.setenv('MAHJONG_AGENCY_DB_PATH',str(volume/'agency.sqlite3'))
    monkeypatch.setattr(m.os.path,'ismount',lambda p:True)
    assert m.checked_storage_path()==volume/'agency.sqlite3'


def test_production_native_wallet_refuses_symlink_escape(tmp_path,monkeypatch):
    volume=tmp_path/'persistent'
    outside=tmp_path/'outside'
    volume.mkdir()
    outside.mkdir()
    (volume/'jump').symlink_to(outside,target_is_directory=True)
    monkeypatch.setenv('STUDIO_PRODUCTION','1')
    monkeypatch.setenv('RAILWAY_VOLUME_MOUNT_PATH',str(volume))
    monkeypatch.setenv('MAHJONG_AGENCY_DB_PATH',str(volume/'jump'/'agency.sqlite3'))
    monkeypatch.setattr(m.os.path,'ismount',lambda p:True)
    with pytest.raises(RuntimeError,match='inside its persistent volume'):
        m.checked_storage_path()
