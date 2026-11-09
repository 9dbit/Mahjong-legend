"""Native Mahjong sandbox: original renderer/math, durable central wallet.

One instance/worker and persistent SQLite. Studio editing remains on the original
service; this runtime pins its bundled baseline config and engine hash per ticket.
"""
from __future__ import annotations
import hashlib, hmac, json, os, re, secrets, sqlite3, threading, time, uuid
from contextlib import asynccontextmanager
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING, localcontext
from datetime import datetime
from pathlib import Path
from fastapi import Depends, FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse, FileResponse, HTMLResponse
from starlette.concurrency import run_in_threadpool
from agency_wallet import AgencyWallet, AgencyWalletError, transport_metrics
from native_locks import operation_lock, active_lock_count
from native_observability import (thread_limiter_health, phase_health, NativePhaseMiddleware,
    phase, phase_call, measured, measured_lock, commit_db, execute_write, close_db,
    classify_operation, recovery_operation, run_observed, CALLBACK_PHASES)
from deployment_identity import initialize_bound_database, open_bound_database, public_identity, canonical_path, requested_identity, require_play, validate_redeemed, cookie_value, runtime_health
from game_studio.domain import baseline_config, digest, ENGINE_HASH
import agency_studio as studio
from mahjong_legend.engine import GameConfig, play_round, verify_round, sha256, display_decimal

ROOT=Path(__file__).resolve().parent
WEB=ROOT/'web'
COOKIE='mahjong_agency'
LOCK=threading.RLock()

def wallet():
    return AgencyWallet(os.environ['AGENCY_WALLET_ORIGIN'],os.environ['AGENCY_WALLET_KEY_ID'],os.environ['AGENCY_WALLET_SECRET'],allow_local=os.getenv('AGENCY_WALLET_LOCAL_QA')=='1')

@measured('db_open_total')
def connect(*, initialize=False):
    path=canonical_path(os.environ['MAHJONG_AGENCY_DB_PATH'])
    os.environ['MAHJONG_AGENCY_DB_PATH']=path
    if not Path(path).is_absolute(): raise RuntimeError('Persistent absolute database path required')
    opener=initialize_bound_database if initialize else open_bound_database
    db=phase_call('open_bound_total',opener,path,'mahjong-wild');db.row_factory=sqlite3.Row
    with phase('connection_pragmas'):
        db.execute('PRAGMA foreign_keys=ON');db.execute('PRAGMA busy_timeout=30000');db.execute('PRAGMA synchronous=FULL')
    return db

def init():
    if os.getenv('AGENCY_WALLET_MODE')!='sandbox': raise RuntimeError('Native Mahjong supports sandbox only')
    wallet()
    if os.getenv('ENGINE_RESTORE_OBJECT_KEY') or os.getenv('ENGINE_RESTORE_OBJECT'):
        from tools.native_backup import restore_from_remote
        path=canonical_path(os.environ['MAHJONG_AGENCY_DB_PATH'])
        restore_from_remote(path,'mahjong',requested_identity('mahjong-wild',path))
    with LOCK:
        db=connect(initialize=True);db.execute('PRAGMA journal_mode=WAL')
        db.executescript('''
        CREATE TABLE IF NOT EXISTS launches(token_hash TEXT PRIMARY KEY, request_id TEXT NOT NULL, cookie_hash TEXT NOT NULL UNIQUE, session_json TEXT, created_at REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS tickets(id TEXT PRIMARY KEY, actor TEXT NOT NULL, seed TEXT NOT NULL, config_json TEXT NOT NULL, engine_hash TEXT NOT NULL,
          state TEXT NOT NULL DEFAULT 'ready', session_json TEXT, request_id TEXT, bet TEXT, stake TEXT, payout TEXT, max_payout TEXT,
          outcome_json TEXT, central_id TEXT, created_at REAL NOT NULL, finished_at REAL, error_status INTEGER);
        CREATE UNIQUE INDEX IF NOT EXISTS one_open ON tickets(actor) WHERE state IN ('ready','pending','reserved');
        CREATE UNIQUE INDEX IF NOT EXISTS request_once ON tickets(actor,request_id) WHERE request_id IS NOT NULL;
        CREATE INDEX IF NOT EXISTS tickets_settled_history ON tickets(actor,state,finished_at DESC) WHERE state='settled';
        ''');db.close()

def remote(action,p):
    with phase(CALLBACK_PHASES.get(action)):
        try: return wallet().request(action,p)
        except AgencyWalletError: raise
        except Exception: raise HTTPException(503,'Koneksi wallet terputus. Hasil tersimpan; ulangi request yang sama.') from None

def hashtext(value): return hashlib.sha256(value.encode()).hexdigest()

def units(value,scale,rounding=None):
    # No binary floats enter stake/settlement accounting.
    with localcontext() as ctx:
        ctx.prec=80
        n=Decimal(str(value)) * (Decimal(10)**scale)
        if not n.is_finite() or n<0 or n>Decimal('10000000000000000000000000000000000000'): raise HTTPException(422,'Nominal tidak valid')
        rounded=n.to_integral_value(rounding=rounding or ROUND_HALF_UP)
        if rounding is None and n!=rounded: raise HTTPException(422,'Taruhan tidak sesuai presisi koin agen')
        return str(int(rounded))

def credits(value,scale):
    with localcontext() as ctx:
        ctx.prec=80
        return format(Decimal(value)/(Decimal(10)**scale),'f')

def session_context(s):
    expires=s.get('expires_at')
    try: expired=bool(expires and datetime.fromisoformat(expires.replace('Z','+00:00')).timestamp()<=time.time())
    except (ValueError,TypeError): expired=False
    return {'navigation':s.get('navigation'),'session_expires_at':expires,'session_expired':expired}

@measured('session_validation')
def actor_session(db,request):
    require_play()
    raw=request.cookies.get(COOKIE,'')
    if not re.fullmatch('[a-f0-9]{64}',raw): raise HTTPException(401,'Buka Mahjong dari website agen')
    row=db.execute('SELECT * FROM launches WHERE cookie_hash=? AND created_at>?',(hashtext(raw),time.time()-86400)).fetchone()
    if not row or not row['session_json']: raise HTTPException(401,'Sesi tidak tersedia. Buka kembali dari website agen.')
    s=json.loads(row['session_json']);validate_redeemed(s,'mahjong-wild',os.environ['MAHJONG_AGENCY_DB_PATH']);return s,s['tenant_id']+':'+s['player_id']

def guard(request):
    require_play()
    if request.headers.get('x-ml-request')!='local-demo' or request.headers.get('sec-fetch-site')=='cross-site': raise HTTPException(403,'Same-origin game request required')
    origin=request.headers.get('origin')
    if origin and origin.split('://',1)[-1]!=request.headers.get('host'): raise HTTPException(403,'Same-origin request required')

async def body(request):
    if not request.headers.get('content-type','').startswith('application/json'): raise HTTPException(415,'JSON required')
    raw=await request.body()
    if len(raw)>1024*1024: raise HTTPException(413,'Payload terlalu besar')
    try: data=json.loads(raw)
    except Exception: raise HTTPException(400,'JSON tidak valid') from None
    if not isinstance(data,dict): raise HTTPException(400,'Object required')
    return data

def get_ticket(db,actor):
    t=db.execute("SELECT * FROM tickets WHERE actor=? AND state IN ('ready','pending','reserved') ORDER BY created_at LIMIT 1",(actor,)).fetchone()
    if t and t['state']=='ready' and (t['created_at']<time.time()-86400 or t['engine_hash']!=ENGINE_HASH):
        execute_write('autocommit_ticket_execute',db,"UPDATE tickets SET state='expired' WHERE id=?",(t['id'],));t=None
    if not t:
        rid=str(uuid.uuid4())
        execute_write('autocommit_ticket_execute',db,'INSERT INTO tickets(id,actor,seed,config_json,engine_hash,created_at) VALUES(?,?,?,?,?,?)',(rid,actor,secrets.token_hex(32),json.dumps(studio.active_config()),ENGINE_HASH,time.time()))
        t=db.execute('SELECT * FROM tickets WHERE id=?',(rid,)).fetchone()
    return t

def manifest(t,scale):
    c=json.loads(t['config_json']);allowed=[]
    for bet in c['bet']['options']:
        try: units(bet,scale);allowed.append(bet)
        except HTTPException: pass
    if not allowed: raise HTTPException(409,'Tidak ada pilihan taruhan sesuai presisi agen')
    bet={**c['bet'],'options':allowed,'default':c['bet']['default'] if c['bet']['default'] in allowed else allowed[0]}
    return {'release_id':digest({'config':c,'engine':t['engine_hash']}),'release_sha256':digest(c),'engine_sha256':t['engine_hash'],
            'schema_version':1,'bet':bet,**{k:c[k] for k in ('presentation','tiles','scene','audio')}}

def advance(db,rid):
    if db.in_transaction: raise RuntimeError('Native wallet callbacks require a committed intent')
    row=db.execute('SELECT actor FROM tickets WHERE id=?',(rid,)).fetchone()
    if not row: raise HTTPException(404,'Tiket tidak tersedia')
    with measured_lock('player_lock_acquire',operation_lock('player:'+row['actor'])), measured_lock('round_lock_acquire',operation_lock('round:'+rid)): return _advance_unlocked(db,rid)

def _advance_unlocked(db,rid):
    t=db.execute('SELECT * FROM tickets WHERE id=?',(rid,)).fetchone()
    if t['state']=='failed': raise HTTPException(t['error_status'],'Reservasi ditolak. Muat ulang untuk mendapatkan tiket baru.')
    if t['state'] not in ('pending','reserved'): return t
    s=json.loads(t['session_json'])
    if t['state']=='pending':
        try: r=remote('reserve',{'tenant_id':s['tenant_id'],'session_id':s['session_id'],'round_ref':'mahjong-'+rid,'stake':t['stake'],'max_payout':t['max_payout']})
        except AgencyWalletError as e:
            if 400<=e.status<500 and e.status not in (408,429):
                execute_write('autocommit_failure_execute',db,"UPDATE tickets SET state='failed',error_status=? WHERE id=?",(e.status,rid));commit_db(db)
            raise HTTPException(e.status if e.status<500 else 503,'Reservasi wallet belum berhasil. Periksa saldo, sesi dan risk pool.') from None
        execute_write('autocommit_result_execute',db,"UPDATE tickets SET central_id=?,state='reserved' WHERE id=?",(r['id'],rid));commit_db(db)
        t=db.execute('SELECT * FROM tickets WHERE id=?',(rid,)).fetchone()
    try: remote('settle',{'tenant_id':s['tenant_id'],'round_id':t['central_id'],'payout':t['payout'],'evidence':'mahjong-native-v1:'+hashtext(t['outcome_json'])})
    except AgencyWalletError: raise HTTPException(503,'Settlement tertunda; hasil tersimpan dan akan direkonsiliasi.') from None
    execute_write('autocommit_result_execute',db,"UPDATE tickets SET state='settled',finished_at=? WHERE id=?",(time.time(),rid))
    return db.execute('SELECT * FROM tickets WHERE id=?',(rid,)).fetchone()

def balance(s):
    try: return remote('status',{'tenant_id':s['tenant_id'],'session_id':s['session_id']})
    except AgencyWalletError: raise HTTPException(503,'Saldo Soft Tech belum tersedia') from None

@measured('response_assembly_inclusive')
def state(db,s,actor):
    with measured_lock('player_lock_acquire',operation_lock('player:'+actor)): return _state_unlocked(db,s,actor)

def _state_unlocked(db,s,actor):
    t=get_ticket(db,actor)
    if t['state'] in ('pending','reserved'):
        advance(db,t['id']);t=get_ticket(db,actor)
    m=manifest(t,s['coin_scale']);cfg=GameConfig(json.loads(t['config_json'])['math']);b=balance(s)
    with phase('history_read'):
        last=db.execute("SELECT * FROM tickets WHERE actor=? AND state='settled' ORDER BY finished_at DESC LIMIT 1",(actor,)).fetchone()
        count=db.execute("SELECT count(*) FROM tickets WHERE actor=? AND state='settled'",(actor,)).fetchone()[0]
    return {**session_context({**s,**b}),'game':'Mahjong Wild','version':cfg.raw['version'],'ui_version':'agency-v1','balance':credits(b['balance'],s['coin_scale']),
      'reserved':credits(b['reserved'],s['coin_scale']),'spin_price':m['bet']['default'],'bet_options':m['bet']['options'],'max_payout_x':str(cfg.cap),'spin_count':count,
      'next_seed_commitment_sha256':sha256(bytes.fromhex(t['seed'])),'config_sha256':cfg.digest,
      'ticket':{'id':t['id'],'sequence':count+1,'status':'ready','release_id':m['release_id'],'expires_at':t['created_at']+86400,'commitment':sha256(bytes.fromhex(t['seed'])),'stake':None},
      'rules':{'grid':list(cfg.heights),'ways':2000,'base_multipliers':list(cfg.base_mult),'bonus_multipliers':list(cfg.bonus_mult),'scatter_per_reel':cfg.scatter_prob,
       'free_spins_for_3_scatters':cfg.raw['free_spins_for_3_scatters'],'extra_free_spins':cfg.raw['extra_free_spins_per_additional_scatter'],'paytable':cfg.raw['paytable'],'symbols':cfg.raw['symbols']},
      'manifest':m,'last_round_id':json.loads(last['outcome_json'])['round_id'] if last else None,
      'virtual_credits_only':True,'session_storage':'persistent','preview':False,'wallet':'soft-tech','simulation':True,
      'settlement_policy':{'coin_scale':s['coin_scale'],'rounding':'half_up','note':f"Sandbox Soft Tech. Payout dibulatkan half-up ke {s['coin_scale']} desimal per ronde; seluruh free spins dihitung sebelum pembulatan. Tidak ada reset saldo lokal."}}

def spin(db,s,actor,data):
    with measured_lock('player_lock_acquire',operation_lock('player:'+actor)): return _spin_unlocked(db,s,actor,data)

def _spin_unlocked(db,s,actor,data):
    if set(data)-{'ticket_id','idempotency_key','bet'}: raise HTTPException(422,'Payload spin tidak valid')
    try: tid=str(uuid.UUID(data.get('ticket_id','')));key=str(uuid.UUID(data.get('idempotency_key','')))
    except (ValueError,TypeError,AttributeError): raise HTTPException(422,'Tiket dan idempotency key wajib') from None
    bet=data.get('bet')
    if not isinstance(bet,str) or len(bet)>40: raise HTTPException(422,'Taruhan harus string decimal')
    other=db.execute('SELECT id FROM tickets WHERE actor=? AND request_id=?',(actor,key)).fetchone()
    if other and other['id']!=tid: raise HTTPException(409,'Idempotency key sudah dipakai untuk tiket lain')
    t=db.execute('SELECT * FROM tickets WHERE id=? AND actor=?',(tid,actor)).fetchone()
    if not t: raise HTTPException(404,'Tiket tidak dimiliki sesi ini')
    if t['request_id'] and (t['request_id']!=key or t['bet']!=bet): raise HTTPException(409,'Payload retry berbeda')
    classify_operation({'ready':'spin_new','pending':'spin_resume','reserved':'spin_resume',
                        'settled':'replay_completed','failed':'replay_failed'}.get(t['state'],'request_unclassified'))
    if t['state']=='ready':
        if t['created_at']<time.time()-86400 or t['engine_hash']!=ENGINE_HASH: raise HTTPException(409,'Tiket lama. Muat ulang.')
        if bet not in manifest(t,s['coin_scale'])['bet']['options']: raise HTTPException(422,'Taruhan tidak tersedia untuk presisi agen')
        with phase('local_prepare'):
            cfg=GameConfig(json.loads(t['config_json'])['math'])
            outcome=play_round(t['seed'],cfg)
            with localcontext() as ctx:
                ctx.prec=80
                payout=units(Decimal(bet)*Decimal(outcome['total_payout_x']),s['coin_scale'],ROUND_HALF_UP)
                maximum=units(Decimal(bet)*cfg.cap,s['coin_scale'],ROUND_CEILING)
            stake=units(bet,s['coin_scale'])
        execute_write('autocommit_intent_execute',db,"UPDATE tickets SET state='pending',request_id=?,bet=?,stake=?,payout=?,max_payout=?,session_json=?,outcome_json=? WHERE id=?",
            (key,bet,stake,payout,maximum,json.dumps(s),json.dumps(outcome,separators=(',',':')),tid))
        # Autocommit + synchronous FULL: no network before this outcome is durable.
    t=advance(db,tid)
    if t['state']!='settled': raise HTTPException(409,'Tiket tidak dapat dimainkan')
    return {'round':json.loads(t['outcome_json']),'stake_virtual_credits':bet,'win_virtual_credits':credits(t['payout'],s['coin_scale']),
       'round_release_id':manifest(t,s['coin_scale'])['release_id'],'round_manifest':manifest(t,s['coin_scale']),
       'state':state(db,s,actor),'idempotency_key':key,'ticket_id':tid,'settlement':{'payout_minor':t['payout'],'coin_scale':s['coin_scale'],'rounding':'half_up'}}

@recovery_operation
def recover():
    if os.getenv('AGENCY_ENVIRONMENT','sandbox')=='production': return
    db=connect()
    try:
        with phase('recovery_scan'):
            rows=db.execute("SELECT id FROM tickets WHERE state IN ('pending','reserved') LIMIT 20").fetchall()
        for row in rows:
            try: advance(db,row['id'])
            except Exception: pass # Durable intent is retained, never locally refunded.
    finally: close_db(db)

def worker(stop):
    while not stop.wait(30):
        try: recover()
        except sqlite3.Error: continue

@asynccontextmanager
async def lifespan(app):
    init();stop=threading.Event();threading.Thread(target=worker,args=(stop,),daemon=True).start()
    if os.getenv('ENGINE_BACKUP_ENABLED')=='true':
        def backup_worker():
            try:
                print('[ENGINE BACKUP] Mahjong worker thread entered',flush=True)
                print('[ENGINE BACKUP] Mahjong importing backup module',flush=True)
                from tools.native_backup_loop import run
                print('[ENGINE BACKUP] Mahjong module loaded',flush=True)
                run(['--database',os.environ['MAHJONG_AGENCY_DB_PATH'],'--game','mahjong'])
            except BaseException as exc:
                print(f'[ENGINE BACKUP] Mahjong worker terminated: {type(exc).__name__}: {str(exc)[:160]}',flush=True)
        threading.Thread(target=backup_worker,name='mahjong-native-backup',daemon=True).start()
    app.state.studio=studio.StudioSync(wallet()) if studio.enabled() else None
    if app.state.studio:threading.Thread(target=app.state.studio.run,args=(stop,),daemon=True).start()
    yield
    stop.set()

app=FastAPI(lifespan=lifespan,docs_url=None,redoc_url=None,openapi_url=None)

@app.get('/health/backup')
async def backup_health():
    from tools.native_backup_status import backup_health as read_backup_health
    proof=read_backup_health('/data/mahjong-backup-status.json',os.getenv('RAILWAY_GIT_COMMIT_SHA',''),enabled=os.getenv('ENGINE_BACKUP_ENABLED')=='true')
    return JSONResponse(proof,status_code=200 if proof['ok'] else 503)

@app.exception_handler(HTTPException)
async def errors(request,e): return JSONResponse({'error':e.detail},status_code=e.status_code)

@app.middleware('http')
async def headers(request,next):
    response=await next(request)
    response.headers.update({'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','Referrer-Policy':'same-origin','X-Frame-Options':'DENY',
      'Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; media-src 'self' blob:; connect-src 'self'; worker-src 'self' blob:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"})
    return response

app.add_middleware(NativePhaseMiddleware,routes={
    ('GET','/api/state'):'state',
    ('POST','/api/spin'):'request_unclassified'})

@app.post('/api/agency/launch')
async def launch(request:Request):
    guard(request);data=await body(request);token=data.get('token','')
    if not isinstance(token,str) or not re.fullmatch('[A-Za-z0-9_-]{30,120}',token): raise HTTPException(422,'Token invalid')
    return await run_in_threadpool(redeem,request,token)

def redeem(request,token):
    require_play()
    cookie=cookie_value(token,'mahjong-wild',os.environ['MAHJONG_AGENCY_DB_PATH'])
    with operation_lock('launch:'+hashtext(token)):
        db=connect()
        try:
            rid='mahjong-redeem-'+hashtext(token)
            try: s=remote('redeem',{'token':token,'request_id':rid})
            except AgencyWalletError as e: raise HTTPException(e.status if e.status<500 else 503,'Launch ditolak. Buka ulang dari website agen.') from None
            validate_redeemed(s,'mahjong-wild',os.environ['MAHJONG_AGENCY_DB_PATH'])
            if s.get('game')!='mahjong-wild' or type(s.get('coin_scale')) is not int or not 0<=s['coin_scale']<=12: raise HTTPException(409,'Game/presisi wallet tidak sesuai')
            db.execute('INSERT INTO launches VALUES(?,?,?,?,?) ON CONFLICT(token_hash) DO UPDATE SET session_json=excluded.session_json',(hashtext(token),rid,hashtext(cookie),json.dumps(s),time.time()))
        finally: db.close()
    response=JSONResponse({'ok':True,'mode':os.getenv('AGENCY_ENVIRONMENT','sandbox'),'coin_scale':s['coin_scale'],**session_context(s)})
    response.set_cookie(COOKIE,cookie,httponly=True,secure=request.url.scheme=='https' or request.headers.get('x-forwarded-proto')=='https',samesite='strict',max_age=86400)
    return response

@app.get('/health')
def health(limiter_health: dict = Depends(thread_limiter_health)):
    db=connect()
    try: db.execute('SELECT 1')
    finally: db.close()
    sync=getattr(app.state,'studio',None)
    return {**runtime_health(),**limiter_health,**phase_health(),'callback_transport':transport_metrics(),'pending_operation_locks':active_lock_count(),'ok':True,'provider':'soft-tech','version':'provider-v1','game':'Mahjong Wild','mode':os.getenv('AGENCY_ENVIRONMENT','sandbox'),'wallet':'soft-tech','environment':os.getenv('AGENCY_ENVIRONMENT','sandbox'),'deployment_identity':public_identity('mahjong-wild',os.environ['MAHJONG_AGENCY_DB_PATH']),'database':'connected','source_commit':os.getenv('RAILWAY_GIT_COMMIT_SHA',''),'engine_sha256':ENGINE_HASH,'studio':{'enabled':bool(sync),'last_sync':sync.last_sync if sync else None,'error':sync.error if sync else ''}}

@app.get('/api/agency/context')
def context(request:Request):
    db=connect()
    try: s,_=actor_session(db,request);return session_context(s)
    finally: db.close()

@app.get('/api/audio-live')
def audio():
    c=studio.active_config();return {'release_id':digest(c),'release_sha256':digest(c),'audio':c['audio']}

@app.api_route('/api/{operation}',methods=['GET','POST'])
async def api(request:Request,operation:str):
    if operation not in ('state','spin','reset','verify','last-round'): raise HTTPException(404,'Not found')
    if request.method=='POST': guard(request);data=await body(request)
    else: data={}
    if (operation in ('state','last-round'))!=(request.method=='GET'): raise HTTPException(405,'Method not allowed')
    return await run_observed(request,dispatch,request,operation,data)

def dispatch(request,operation,data):
    db=connect()
    try:
        s,actor=actor_session(db,request)
        if operation=='state': return state(db,s,actor)
        if operation=='spin': return spin(db,s,actor,data)
        if operation=='reset': raise HTTPException(403,'Saldo dikelola Soft Tech; reset lokal dinonaktifkan')
        rows=db.execute("SELECT * FROM tickets WHERE actor=? AND state='settled' ORDER BY finished_at DESC LIMIT 100",(actor,)).fetchall()
        if operation=='last-round':
            if not rows: raise HTTPException(404,'Belum ada ronde')
            return {'round':json.loads(rows[0]['outcome_json']),'release_id':manifest(rows[0],s['coin_scale'])['release_id'],'ticket_id':rows[0]['id']}
        transcript=data.get('round')
        if not isinstance(transcript,dict): raise HTTPException(400,'Round required')
        found=next((r for r in rows if json.loads(r['outcome_json'])['round_id']==transcript.get('round_id')),None)
        if not found: raise HTTPException(404,'Ronde tidak dimiliki player')
        return verify_round(transcript,GameConfig(json.loads(found['config_json'])['math']))
    finally: close_db(db)

@app.get('/agency-navigation.js')
def navigation_script(): return FileResponse(ROOT/'agency-navigation.js',media_type='application/javascript')

@app.get('/agency-media/{name}')
def studio_media(name:str):
    if not studio.enabled():raise HTTPException(404,'Media tidak ditemukan')
    try:target=studio.file_path(name)
    except ValueError:raise HTTPException(404,'Media tidak ditemukan') from None
    if not target.is_file():raise HTTPException(404,'Media tidak ditemukan')
    return FileResponse(target)

@app.get('/agency-client.js')
def client(): return FileResponse(ROOT/'agency-client.js',media_type='application/javascript')

@app.get('/{path:path}')
def static(path:str):
    if path in ('','index.html'):
        html=(WEB/'index.html').read_text().replace('<head>','<head><script src="/agency-navigation.js?v=2"></script><script src="/agency-client.js?v=2"></script>')
        return HTMLResponse(html)
    target=(WEB/path).resolve()
    if not target.is_relative_to(WEB.resolve()) or not target.is_file() or not(path.startswith('assets/') or path in ('style.css','sw.js','manifest.webmanifest','favicon.ico','apple-touch-icon.png')): raise HTTPException(404,'Not found')
    return FileResponse(target)
