"""Immutable Studio packages on the native volume; master activation via HMAC.

Never fetch asset URLs supplied in a package. Media bytes are bundled and validated
before the package is acknowledged. Existing tickets keep their pinned config.
"""
import base64,hashlib,io,json,os,re,sqlite3,threading,time,uuid
from copy import deepcopy
from pathlib import Path
from contextlib import contextmanager
from PIL import Image
from game_studio.domain import baseline_config,validate_config,BASELINE_REFS,ENGINE_HASH

def enabled(): return os.getenv('AGENCY_STUDIO_SYNC')=='1'
@contextmanager
def connect():
    db=sqlite3.connect(os.environ['MAHJONG_AGENCY_DB_PATH']+'.studio',timeout=30)
    db.row_factory=sqlite3.Row
    db.execute('PRAGMA journal_mode=WAL');db.execute('PRAGMA synchronous=FULL')
    db.executescript('''CREATE TABLE IF NOT EXISTS packages(id TEXT PRIMARY KEY,sha TEXT NOT NULL,config TEXT NOT NULL,engine TEXT NOT NULL,published INTEGER NOT NULL DEFAULT 0);
      CREATE TABLE IF NOT EXISTS state(id INTEGER PRIMARY KEY CHECK(id=1),active TEXT,sha TEXT,generation INTEGER NOT NULL);
      INSERT OR IGNORE INTO state VALUES(1,NULL,NULL,0);''')
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback();raise
    finally:db.close()
def media_root(): return Path(os.environ['MAHJONG_AGENCY_DB_PATH']).parent/'studio-media'
def active_config():
    if not enabled(): return baseline_config()
    with connect() as db:
        row=db.execute('SELECT p.config,p.engine FROM state s JOIN packages p ON p.id=s.active WHERE s.id=1').fetchone()
        if row and row['engine']!=ENGINE_HASH:raise ValueError('Active Studio release requires validation for this engine')
        return json.loads(row['config']) if row else baseline_config()
def coherent_state():
    with connect() as db:
        s=dict(db.execute('SELECT * FROM state WHERE id=1').fetchone())
        row=db.execute('SELECT engine FROM packages WHERE id=?',(s['active'],)).fetchone() if s['active'] else None
        coherent=s['active'] is None or row is not None and row['engine']==ENGINE_HASH
    return s,coherent
def file_path(name):
    if not re.fullmatch(r'[a-f0-9]{64}\.(png|webp|wav|mp3|ogg|m4a)',name): raise ValueError('Media tidak ditemukan')
    with connect() as db:
        if not db.execute('SELECT 1 FROM packages WHERE published=1 AND instr(config,?)>0',('/agency-media/'+name,)).fetchone():raise ValueError('Media belum dipublikasikan')
    return media_root()/name
def _media(item,kind):
    if not isinstance(item,dict) or set(item)!={'mime','data'}: raise ValueError('Aset tidak valid')
    try: raw=base64.b64decode(item['data'],validate=True)
    except Exception: raise ValueError('Encoding aset tidak valid') from None
    if not raw or len(raw)>12*1024*1024: raise ValueError('Aset maksimal 12 MB')
    mime=item['mime'];ext={'image/png':'png','image/webp':'webp','audio/wav':'wav','audio/mpeg':'mp3','audio/ogg':'ogg','audio/mp4':'m4a'}.get(mime)
    if not ext: raise ValueError('Format aset tidak didukung')
    if kind in ('tile','scene'):
        if ext not in ('png','webp'): raise ValueError('Aset gambar wajib PNG/WebP')
        with Image.open(io.BytesIO(raw)) as im:
            if im.format not in ('PNG','WEBP') or im.width>4096 or im.height>4096 or getattr(im,'n_frames',1)!=1: raise ValueError('Gambar tidak valid')
            if kind=='tile' and im.size!=(218,327): raise ValueError('Tile wajib 218×327')
            im.verify()
    else:
        valid=(ext=='wav' and raw[:4]==b'RIFF' and raw[8:12]==b'WAVE') or (ext=='ogg' and raw[:4]==b'OggS') or (ext=='mp3' and (raw[:3]==b'ID3' or raw[:1]==b'\xff' and len(raw)>1 and raw[1]&224==224)) or (ext=='m4a' and raw[4:8]==b'ftyp')
        if not valid: raise ValueError('Audio tidak valid')
    name=hashlib.sha256(raw).hexdigest()+'.'+ext
    return name,raw
def prepare(pkg):
    rid=str(uuid.UUID(pkg['id']));body=pkg['body']
    if len(body.encode())>34*1024*1024 or hashlib.sha256(body.encode()).hexdigest()!=pkg['sha256']: raise ValueError('Checksum paket tidak cocok')
    bundle=json.loads(body)
    if bundle.get('format')!='playground.studio.v1' or bundle.get('game')!='mahjong-wild': raise ValueError('Paket Mahjong tidak valid')
    p=bundle['payload']
    if set(p)-{'config','assets','engine_sha256'} or p.get('engine_sha256',ENGINE_HASH)!=ENGINE_HASH: raise ValueError('Versi engine tidak kompatibel')
    config=deepcopy(p['config']);checked=validate_config(config)
    if not checked['valid']: raise ValueError('; '.join(checked['errors'])[:500])
    assets=p.get('assets',{})
    if not isinstance(assets,dict) or len(assets)>100: raise ValueError('Daftar aset tidak valid')
    total=0;files={};seen=set()
    def resolve(ref,kind):
        nonlocal total
        if ref is None:return None
        if ref in BASELINE_REFS:return ref
        key=str(uuid.UUID(ref))
        if key not in assets:raise ValueError('Aset paket tidak ditemukan')
        name,raw=_media(assets[key],kind)
        if name not in files:total+=len(raw);files[name]=raw
        if total>24*1024*1024:raise ValueError('Total aset maksimal 24 MB')
        seen.add(key);return '/agency-media/'+name
    for variants in config['tiles'].values():
        for key,ref in variants.items():variants[key]=resolve(ref,'tile')
    for key,ref in config['scene'].items():config['scene'][key]=resolve(ref,'scene')
    for event in config['audio']['events'].values():event['asset']=resolve(event.get('asset'),'audio')
    for track in config['audio']['music'].values():
        if track:track['asset']=resolve(track.get('asset'),'audio')
    if set(assets)!=seen:raise ValueError('Paket berisi aset yang tidak dipakai')
    root=media_root();root.mkdir(parents=True,exist_ok=True)
    for name,raw in files.items():
        target=root/name
        if target.exists():
            if target.read_bytes()!=raw:raise ValueError('Checksum aset tersimpan berubah')
        else:
            tmp=root/(name+'.tmp')
            with tmp.open('wb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
            os.replace(tmp,target)
    if files:
        fd=os.open(root,os.O_DIRECTORY)
        try:os.fsync(fd)
        finally:os.close(fd)
    with connect() as db:
        old=db.execute('SELECT sha FROM packages WHERE id=?',(rid,)).fetchone()
        if old and old['sha']!=pkg['sha256']:raise ValueError('Identitas paket berubah')
        db.execute('INSERT OR IGNORE INTO packages(id,sha,config,engine) VALUES(?,?,?,?)',(rid,pkg['sha256'],json.dumps(config),ENGINE_HASH))
    return rid
class StudioSync:
    def __init__(self,client):self.client=client;self.error='';self.last_sync=None;self.lock=threading.Lock()
    def tick(self):
        if not self.lock.acquire(blocking=False):return
        try:self._tick()
        except Exception:self.error='Sinkronisasi Playground belum tersedia'
        finally:self.lock.release()
    def _tick(self):
        runtime=os.getenv('RAILWAY_GIT_COMMIT_SHA') or 'local-studio-v1'
        s,coherent=coherent_state()
        base={'format':'playground.studio.v1','game':'mahjong-wild','name':'Baseline Mahjong','payload':{'config':baseline_config(),'assets':{},'engine_sha256':ENGINE_HASH}}
        r=self.client.request('studio-sync',{'runtime':runtime,'active':s['active'] if coherent else None,'sha256':s['sha'] if coherent else None,'generation':s['generation'] if coherent else 0,'baseline':base,'error':self.error})
        receipt=None
        if r.get('candidate'):
            p=r['candidate'];receipt={'id':p['id'],'sha256':p['sha256']}
            try:prepare(p);receipt['state']='validated'
            except Exception as e:receipt.update(state='rejected',error=str(e)[:500])
        try:
            if r['generation']>s['generation'] or not coherent:
                if r['desired']:
                    if not r.get('apply'):raise ValueError('Paket aktif belum tersedia')
                    prepare(r['apply'])
                with connect() as db:
                    db.execute('UPDATE state SET active=?,sha=?,generation=? WHERE id=1',(r['desired'],r.get('apply',{}).get('sha256') if r.get('apply') else None,r['generation']))
                    if r['desired']:db.execute('UPDATE packages SET published=1 WHERE id=?',(r['desired'],))
            self.error=''
        except Exception as e:self.error=str(e)[:500]
        s,coherent=coherent_state()
        self.client.request('studio-sync',{'runtime':runtime,'active':s['active'] if coherent else None,'sha256':s['sha'] if coherent else None,'generation':s['generation'] if coherent else 0,'receipt':receipt,'error':self.error});self.last_sync=time.time()
    def run(self,stop):
        while not stop.is_set():self.tick();stop.wait(.3 if os.getenv('AGENCY_WALLET_LOCAL_QA')=='1' else 10)
