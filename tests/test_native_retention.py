import hashlib, json, os
from datetime import datetime, timezone
import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from tools.native_retention import retention_plan,enforce_retention,probe_conditional_deletion,POLICY
from tools.native_backup import decrypt_payload
NOW=int(datetime(2026,11,10,12,tzinfo=timezone.utc).timestamp());DAY=86400
IDENTITY={'environment':'preproduction','deployment_id':'native-fixture','core_deployment_id':'core-fixture','game_id':'mahjong-wild','identity_version':1}
GAME='mahjong'

def fixture():
    key=os.urandom(32);objects={};deleted=[];events=[];sequence=0
    def add(age,who=None):
        nonlocal sequence
        sequence+=1;plain=b'fixture sqlite bytes';manifest={'game':GAME,'created_at':NOW-age,'sha256':hashlib.sha256(plain).hexdigest(),'size':len(plain),'format':'sqlite-online-backup-v1','key_id':'test','deployment_identity':who or IDENTITY}
        header=json.dumps(manifest,sort_keys=True,separators=(',',':')).encode();nonce=os.urandom(12);payload=len(header).to_bytes(4,'big')+header+nonce+AESGCM(key).encrypt(nonce,plain,header)
        name=f"native/{GAME}/{manifest['created_at']}-{manifest['sha256'][:16]}-{sequence:016d}.aesgcm"
        objects[name]={'bytes':payload,'etag':'"'+hashlib.sha256(payload).hexdigest()+'"'};return name
    current=add(0);second=add(3600);old=[add((400+i)*DAY) for i in range(14)]
    legacy=f'native/{GAME}/1000000000-abcdefabcdefabcd.aesgcm';objects[legacy]={'bytes':b'never delete legacy'}
    def remove(name,etag):
        assert objects[name]['etag']==etag;del objects[name];deleted.append(name)
    options=dict(game=GAME,identity=IDENTITY,current_object=current,current_ciphertext_sha256=hashlib.sha256(objects[current]['bytes']).hexdigest(),now=NOW,mode='apply',list_page=lambda token:{'keys':list(objects),'next_token':None},download=lambda k:objects[k],remove=remove,verify=lambda b:decrypt_payload(b,key.hex())[0],logger=events.append,check_conditional_delete=lambda:{'verified':True})
    return objects,deleted,events,options,current,second,old,legacy,add,key

def test_calendar_retention_protects_young_two_latest_and_periodic_snapshots():
    keys=[f'native/{GAME}/{NOW-d*DAY-h*3600}-aaaaaaaaaaaaaaaa-{d*2+h:016d}.aesgcm' for d in range(400) for h in range(2)]
    plan=retention_plan(keys,game=GAME,now=NOW,restoring_object=keys[-1],max_deletes=10)
    assert all(k in plan['keep'] for k in keys[:14]+[keys[-1]])
    assert len(plan['candidates'])==10 and all(NOW-r['created_at']>=7*DAY for r in plan['candidates'])
    months={datetime.fromtimestamp(int(k.split('/')[2].split('-')[0]),timezone.utc).strftime('%Y-%m') for k in plan['keep'] if NOW-int(k.split('/')[2].split('-')[0])>=7*DAY}
    assert len(months)>=11

def test_dryrun_and_bounded_applied_deletion():
    objects,deleted,events,options,current,second,old,legacy,add,key=fixture()
    report=enforce_retention(**{**options,'mode':'dry-run'})
    assert report['verified'] and report['deleted_count']==0 and report['eligible_count']==5 and not deleted
    report=enforce_retention(**options)
    assert report['policy']==POLICY and report['verified'] and report['deleted_count']==5 and len(deleted)==5
    assert all(k in objects for k in (current,second,legacy))
    assert events[0]['event']=='engine.backup.retention_plan'

@pytest.mark.parametrize('kind',['tampered','unknown-key','foreign'])
def test_invalid_proof_blocks_every_deletion(kind):
    objects,deleted,events,options,current,second,old,legacy,add,key=fixture()
    target=old[-1]
    if kind=='tampered':
        b=bytearray(objects[target]['bytes']);b[-1]^=1;objects[target]['bytes']=bytes(b)
    elif kind=='unknown-key':options['verify']=lambda b:decrypt_payload(b,keys={})[0]
    else:
        original=options['verify'];options['verify']=lambda b:{**original(b),'deployment_identity':{**IDENTITY,'environment':'production'}}
    report=enforce_retention(**options)
    assert not report['verified'] and not deleted

def test_stale_proof_incomplete_inventory_and_changed_etag_fail_closed():
    objects,deleted,events,options,*_=fixture();report=enforce_retention(**{**options,'now':NOW+26*3600});assert not report['verified'] and not deleted
    objects,deleted,events,options,*_=fixture();report=enforce_retention(**{**options,'list_page':lambda token:{'keys':list(objects),'next_token':'loop'}});assert report['error_code']=='RETENTION_PAGINATION_LOOP' and not deleted
    objects,deleted,events,options,*_=fixture()
    def conditional_failure(*args):raise RuntimeError('HTTP 412')
    report=enforce_retention(**{**options,'remove':conditional_failure});assert not report['verified'] and report['deleted_count']==0 and not deleted
    report=enforce_retention(**{**options,'max_objects':1});assert report['error_code']=='RETENTION_INVENTORY_LIMIT' and not deleted

def test_backup_worker_enforces_policy_on_real_encrypted_sqlite_snapshot(tmp_path,monkeypatch):
    import io,sqlite3,time
    from unittest.mock import patch
    from tools.native_backup import backup_once
    path=tmp_path/'native.sqlite'
    db=sqlite3.connect(path);db.execute('CREATE TABLE native_deployment_identity(singleton INTEGER PRIMARY KEY,identity_json TEXT)');db.execute('INSERT INTO native_deployment_identity VALUES(1,?)',(json.dumps(IDENTITY),));db.execute('CREATE TABLE rounds(id TEXT PRIMARY KEY,payout TEXT)');db.execute("INSERT INTO rounds VALUES('settled','42')");db.commit();db.close()
    class Storage:
        def __init__(self):self.objects={};self.deleted=[]
        def put_object(self,Bucket,Key,Body,Metadata):
            self.objects[Key]=Body;return {'ETag':'"'+hashlib.sha256(Body).hexdigest()+'"'}
        def get_object(self,Bucket,Key):return {'Body':io.BytesIO(self.objects[Key]),'ETag':'"'+hashlib.sha256(self.objects[Key]).hexdigest()+'"'}
        def head_object(self,Bucket,Key):
            if Key not in self.objects:raise storage_error(404)
            return {'ETag':'"'+hashlib.sha256(self.objects[Key]).hexdigest()+'"'}
        def list_objects_v2(self,**kwargs):return {'Contents':[{'Key':key} for key in self.objects],'IsTruncated':False}
        def delete_object(self,Bucket,Key,IfMatch):
            if IfMatch!='"'+hashlib.sha256(self.objects[Key]).hexdigest()+'"':raise storage_error(412)
            del self.objects[Key];self.deleted.append(Key)
    storage=Storage()
    values={'ENGINE_BACKUP_KEY_HEX':os.urandom(32).hex(),'ENGINE_BACKUP_S3_ENDPOINT':'https://storage.example','ENGINE_BACKUP_S3_ACCESS_KEY_ID':'test','ENGINE_BACKUP_S3_SECRET_ACCESS_KEY':'test','ENGINE_BACKUP_S3_BUCKET':'backups','ENGINE_BACKUP_RETENTION_ENABLED':'false'}
    for k,v in values.items():monkeypatch.setenv(k,v)
    with patch('boto3.client',return_value=storage):
        for stamp in (NOW-401*DAY,NOW-400*DAY,NOW-3600):
            with patch('time.time',return_value=stamp):backup_once(str(path),GAME,'backups','native')
        legacy=f'native/{GAME}/1000000000-abcdefabcdefabcd.aesgcm';storage.objects[legacy]=b'legacy object remains untouched'
        monkeypatch.setenv('ENGINE_BACKUP_RETENTION_ENABLED','true');monkeypatch.setenv('ENGINE_BACKUP_RETENTION_MODE','apply')
        with patch('time.time',return_value=NOW):result=backup_once(str(path),GAME,'backups','native')
    assert result['verified'] and result['retention']['verified'] and result['retention']['mode']=='apply'
    assert result['retention']['deleted_count']==2 and len(storage.deleted)==3
    assert result['retention']['conditional_delete_verified'] and result['retention']['conditional_delete']['absence_verified']
    assert legacy in storage.objects and result['object'] in storage.objects
    assert len(storage.objects)==3


def storage_error(status):
    from botocore.exceptions import ClientError
    return ClientError({'Error':{'Code':str(status)},'ResponseMetadata':{'HTTPStatusCode':status}},'Fixture')


@pytest.mark.parametrize('behavior',['supported','ignored','wrong-status','content-changed','delete-noop','head-denied','weak-etag'])
def test_conditional_delete_probe_proves_backend_semantics_using_only_new_canary(behavior):
    objects={};deleted=[]
    def put(name,body):
        assert name.startswith(f"native/{GAME}/.retention-probe/preproduction/native-fixture/")
        objects[name]={'bytes':body,'etag':'"'+hashlib.sha256(body).hexdigest()+'"'}
        return {'etag':('W/' if behavior=='weak-etag' else '')+objects[name]['etag']}
    def download(name):return {**objects[name],'bytes':b'changed' if behavior=='content-changed' else objects[name]['bytes']}
    def head(name):
        if behavior=='head-denied':raise storage_error(403)
        if name not in objects:raise storage_error(404)
        return objects[name]
    def remove(name,etag):
        if etag!=objects[name]['etag'] and behavior!='ignored':raise storage_error(400 if behavior=='wrong-status' else 412)
        if behavior!='delete-noop':del objects[name];deleted.append(name)
    report=probe_conditional_deletion(game=GAME,identity=IDENTITY,put=put,download=download,head=head,remove=remove,now=NOW)
    assert report['verified']==(behavior=='supported')
    if behavior=='supported':
        assert report['wrong_etag_rejected'] and report['correct_etag_deleted'] and report['absence_verified'] and not objects
    else:assert report['error_code'].startswith('RETENTION_PROBE_')
    assert len(set(deleted))<=1


def test_missing_or_failed_live_capability_proof_blocks_backup_deletion_and_forces_dryrun():
    for check in (None,lambda:{'verified':False,'error_code':'RETENTION_PROBE_CONDITION_IGNORED'}):
        objects,deleted,events,options,*_=fixture()
        report=enforce_retention(**{**options,'check_conditional_delete':check})
        assert not report['verified'] and not report['conditional_delete_verified'] and not deleted
        assert report['mode']=='apply' and report['effective_mode']=='dry-run'


def test_explicit_probe_qualifies_empty_new_bucket_during_dryrun():
    objects,deleted,events,options,current,second,*_=fixture();probes=[]
    options['list_page']=lambda token:{'keys':[current,second],'next_token':None}
    options['check_conditional_delete']=lambda:(probes.append(True) or {'verified':True,'absence_verified':True})
    report=enforce_retention(**{**options,'mode':'dry-run','probe_requested':True})
    assert report['verified'] and report['conditional_delete_verified'] and report['eligible_count']==0
    assert probes==[True] and not deleted and report['effective_mode']=='dry-run'
