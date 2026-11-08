import base64,hashlib,io,json,uuid
import pytest
from PIL import Image
import agency_studio as s

@pytest.fixture
def studio(tmp_path,monkeypatch):
    monkeypatch.setenv('MAHJONG_AGENCY_DB_PATH',str(tmp_path/'wallet.sqlite'))
    monkeypatch.setenv('AGENCY_STUDIO_SYNC','1')

def package(config=None,assets=None):
    body=json.dumps({'format':'playground.studio.v1','game':'mahjong-wild','payload':{'config':config or s.baseline_config(),'assets':assets or {},'engine_sha256':s.ENGINE_HASH}})
    return {'id':str(uuid.uuid4()),'sha256':hashlib.sha256(body.encode()).hexdigest(),'body':body}

def test_package_integrity_draft_media_and_durable_apply(studio):
    config=s.baseline_config();key=str(uuid.uuid4());symbol=next(iter(config['tiles']));variant=next(iter(config['tiles'][symbol]))
    config['tiles'][symbol][variant]=key
    buf=io.BytesIO();Image.new('RGBA',(218,327),'purple').save(buf,format='PNG')
    p=package(config,{key:{'mime':'image/png','data':base64.b64encode(buf.getvalue()).decode()}})
    s.prepare(p);s.prepare(p)
    name=hashlib.sha256(buf.getvalue()).hexdigest()+'.png'
    with pytest.raises(ValueError,match='dipublikasikan'):s.file_path(name)
    with pytest.raises(ValueError,match='Checksum'):s.prepare({**p,'sha256':'0'*64})
    q=package();q['id']=p['id']
    with pytest.raises(ValueError,match='Identitas'):s.prepare(q)
    reports=[];desired={'generation':1,'desired':p['id'],'apply':p,'candidate':p}
    class Client:
        def request(self,action,body):
            assert action=='studio-sync';reports.append(body);return desired
    sync=s.StudioSync(Client());sync.tick()
    assert reports[-1]['active']==p['id'] and reports[-1]['generation']==1
    assert s.file_path(name).read_bytes()==buf.getvalue()
    assert s.active_config()['tiles'][symbol][variant]=='/agency-media/'+name
    # A new controller has no in-memory state and must recover from disk.
    s.StudioSync(Client()).tick();assert reports[-1]['active']==p['id']
    desired.update(generation=2,desired=None,apply=None,candidate=None)
    sync.tick();assert reports[-1]['active'] is None and s.active_config()==s.baseline_config()
    assert s.file_path(name).exists() # Previously published rounds may still reference it.

def test_rejected_release_preserves_baseline_and_reports_failure(studio):
    config=s.baseline_config();config['presentation']['animation_speed']=-1
    p=package(config);reports=[]
    class Client:
        def request(self,action,body):
            reports.append(body);return {'generation':1,'desired':p['id'],'apply':p,'candidate':p}
    s.StudioSync(Client()).tick()
    assert reports[-1]['receipt']['state']=='rejected'
    assert reports[-1]['active'] is None and reports[-1]['generation']==0
    assert reports[-1]['error'] and s.active_config()==s.baseline_config()
