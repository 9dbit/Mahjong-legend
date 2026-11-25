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
