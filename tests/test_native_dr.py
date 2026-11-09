"""Disposable complete Mahjong volume loss with actual HTTP/native math/journal."""
import io,json,os,shutil,time,uuid
from pathlib import Path
from unittest.mock import patch
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
import agency_runtime as native
from deployment_identity import requested_identity
from tools.native_backup import backup_once,restore_from_remote,restore_verify
class Storage:
    def __init__(self):self.objects={}
    def put_object(self,Bucket,Key,Body,Metadata):self.objects[Key]=Body
    def get_object(self,Bucket,Key):return {'Body':io.BytesIO(self.objects[Key])}

def test_full_native_volume_loss_key_rotation_and_recovery(tmp_path,monkeypatch):
    volume=tmp_path/'disposable-volume';volume.mkdir();path=volume/'native.sqlite';old,new=os.urandom(32).hex(),os.urandom(32).hex()
    values={'AGENCY_WALLET_MODE':'sandbox','AGENCY_ENVIRONMENT':'preproduction','AGENCY_DEPLOYMENT_ID':'mahjong-dr-deployment','AGENCY_CORE_DEPLOYMENT_ID':'core-dr-deployment','MAHJONG_AGENCY_DB_PATH':str(path),'AGENCY_WALLET_ORIGIN':'https://core.example','AGENCY_WALLET_KEY_ID':'test-engine','AGENCY_WALLET_SECRET':'q'*40,'AGENCY_STUDIO_SYNC':'0','ENGINE_BACKUP_KEYS_JSON':json.dumps({'old':old}),'ENGINE_BACKUP_ACTIVE_KEY_ID':'old','ENGINE_BACKUP_S3_ENDPOINT':'https://storage.example','ENGINE_BACKUP_S3_ACCESS_KEY_ID':'test','ENGINE_BACKUP_S3_SECRET_ACCESS_KEY':'test','ENGINE_BACKUP_S3_BUCKET':'backups'}
    for k,v in values.items():monkeypatch.setenv(k,v)
    storage=Storage();rounds={};balance=100000;lost=False;generated=0;original=native.play_round
    def play(*args,**kwargs):
        nonlocal generated
        generated+=1;return original(*args,**kwargs)
    monkeypatch.setattr(native,'play_round',play)
    class Wallet:
        def request(self,action,p):
            nonlocal balance,lost
            if action=='redeem':return {'provider':'soft-tech','tenant_id':'tenant','player_id':'player','session_id':'session','game':'mahjong-wild','coin_scale':2,'currency':'VCOIN','environment':'preproduction','deployment_id':'core-dr-deployment'}
            if action=='status':return {'balance':str(balance),'reserved':'0'}
            if action=='reserve':
                rid=p['round_ref']
                if rid not in rounds:rounds[rid]={'id':rid,**p};balance-=int(p['stake'])
                return rounds[rid]
            if action=='settle':
                r=rounds[p['round_id']]
                if not r.get('settled'):r['settled']=True;balance+=int(p['payout'])
                if lost:lost=False;raise HTTPException(503,'simulated lost settlement response')
                return {'ok':True}
            raise AssertionError(action)
    monkeypatch.setattr(native,'wallet',lambda:Wallet());headers={'X-ML-Request':'local-demo'}
    with patch('boto3.client',return_value=storage):
        with TestClient(native.app) as c:
            assert c.post('/api/agency/launch',headers=headers,json={'token':'t'*48}).status_code==200
            cookie=c.cookies.get(native.COOKIE);state=c.get('/api/state').json()
            request={'ticket_id':state['ticket']['id'],'idempotency_key':str(uuid.uuid4()),'bet':'1'}
            r=c.post('/api/spin',headers=headers,json=request);assert r.status_code==200,r.text
            first=r.json();lost=True
            pending={'ticket_id':first['state']['ticket']['id'],'idempotency_key':str(uuid.uuid4()),'bet':'1'}
            assert c.post('/api/spin',headers=headers,json=pending).status_code==503
            db=native.connect();before=dict(db.execute('SELECT * FROM tickets WHERE id=?',(pending['ticket_id'],)).fetchone());db.close();assert before['state']=='reserved'
            backup=backup_once(str(path),'mahjong','backups','native')
        lost_at=time.monotonic();shutil.rmtree(volume);assert not volume.exists();volume.mkdir()
        monkeypatch.setenv('ENGINE_BACKUP_KEYS_JSON',json.dumps({'old':old,'rotated':new}));monkeypatch.setenv('ENGINE_BACKUP_ACTIVE_KEY_ID','rotated')
        monkeypatch.setenv('ENGINE_RESTORE_OBJECT_KEY',backup['object']);monkeypatch.setenv('ENGINE_RESTORE_CIPHERTEXT_SHA256',backup['ciphertext_sha256']);monkeypatch.setenv('ENGINE_RESTORE_CONFIRM_DEPLOYMENT_ID','mahjong-dr-deployment')
        with TestClient(native.app) as c:
            c.cookies.set(native.COOKIE,cookie)
            assert c.get('/health').json()['deployment_identity']['environment']=='preproduction'
            r=c.post('/api/spin',headers=headers,json=pending);assert r.status_code==200,r.text
            again=c.post('/api/spin',headers=headers,json=pending);assert again.status_code==200 and again.json()==r.json()
            assert generated==2 and len(rounds)==2 and all(x['settled'] for x in rounds.values())
            db=native.connect();after=dict(db.execute('SELECT * FROM tickets WHERE id=?',(pending['ticket_id'],)).fetchone());settled=dict(db.execute('SELECT * FROM tickets WHERE id=?',(first['ticket_id'],)).fetchone());db.close()
            assert after['seed']==before['seed'] and after['outcome_json']==before['outcome_json'] and after['payout']==before['payout']
            assert settled['state']=='settled' and settled['outcome_json']==json.dumps(first['round'],separators=(',',':'))
            assert balance==100000-200+int(settled['payout'])+int(after['payout'])
            rotated=backup_once(str(path),'mahjong','backups','native')
            assert restore_verify(storage.objects[backup['object']])['key_id']=='old'
            assert restore_verify(storage.objects[rotated['object']])['key_id']=='rotated'
        rto=time.monotonic()-lost_at
        assert restore_from_remote(str(path),'mahjong',requested_identity('mahjong-wild',str(path))) is None
        monkeypatch.setenv('ENGINE_BACKUP_KEYS_JSON',json.dumps({'rotated':new}))
        with pytest.raises(ValueError,match='unavailable'):restore_verify(storage.objects[backup['object']])
        report={'game':'mahjong','scenario':'disposable-native-volume-deleted-and-replaced','transport':'in-memory S3 double; real native HTTP + SQLite + AES-GCM','settled_rounds_preserved':1,'pending_rounds_recovered':1,'rounds_generated':generated,'duplicate_debits':0,'duplicate_credits':0,'rpo_lost_committed_rounds':0,'snapshot_age_seconds':max(0,time.time()-backup['manifest']['created_at']),'rto_seconds':rto,'old_and_new_keys_restore':True,'production_certified':False}
        if os.getenv('NATIVE_DR_EVIDENCE_PATH'):Path(os.environ['NATIVE_DR_EVIDENCE_PATH']).write_text(json.dumps(report,indent=2)+'\n')
