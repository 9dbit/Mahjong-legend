from copy import deepcopy
from functools import wraps
import json
import mimetypes
import os
from pathlib import Path
import secrets
import uuid
from django.conf import settings
from django.contrib.auth import authenticate, login, logout, get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.password_validation import validate_password
from django.core import signing
from django.core.exceptions import ValidationError, RequestDataTooBig
from django.db import transaction
from django.http import JsonResponse, HttpResponse, FileResponse
from django.middleware.csrf import get_token
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from . import game
from .domain import digest, baseline_config, validate_config, ENGINE_HASH, decimal_value, integer, BASELINE_REFS, BASE_MUSIC, BASE_AUDIO
from .models import Draft, Release, ActiveRelease, Asset, Job, AuditEvent, Round, PlayerSession, WorkerHeartbeat
from .releases import active_release, validate_draft, publish, activate, make_release, audit
from .security import throttle
from .storage import ContentStore
from mahjong_legend.engine import sha256

WEB=settings.BASE_DIR/'web'
def content_store(): return ContentStore(root=None if os.environ.get('STUDIO_S3_BUCKET') else settings.STUDIO_MEDIA_ROOT)
def reply(value,status=200): return JsonResponse(value,status=status,json_dumps_params={'allow_nan':False})
def csrf_failure(request,reason=''): return reply({'error':'CSRF verification failed. Refresh this page and retry.'},403)

def body(request):
    if request.content_type!='application/json': raise game.GameError('JSON content type required',415)
    if int(request.META.get('CONTENT_LENGTH') or 0)>1024*1024: raise game.GameError('Request too large',413)
    def invalid(value): raise ValueError('Non-finite JSON values are not allowed')
    data=json.loads(request.body or b'{}',parse_constant=invalid)
    if not isinstance(data,dict): raise ValueError('Expected a JSON object')
    return data

def api(permission=None,methods=('GET',)):
    def decorate(fn):
        @wraps(fn)
        def wrapped(request,*args,**kwargs):
            if request.method not in methods: return reply({'error':'Method not allowed'},405)
            if permission:
                if not request.user.is_authenticated: return reply({'error':'Studio sign-in required'},401)
                codes={'edit':'edit_studio','publish':'publish_release','test':'test_studio','read':'test_studio'}
                if not request.user.has_perm('game_studio.'+codes[permission]): return reply({'error':'Permission denied'},403)
            try: return fn(request,*args,**kwargs)
            except game.GameError as exc: return reply({'error':str(exc)},exc.code)
            except (ValueError,TypeError,KeyError,ValidationError) as exc: return reply({'error':str(exc)[:800]},400)
            except RequestDataTooBig: return reply({'error':'Request too large'},413)
            except (Draft.DoesNotExist,Asset.DoesNotExist,Release.DoesNotExist,Job.DoesNotExist): return reply({'error':'Not found'},404)
        return wrapped
    return decorate

def session_data(request):
    auth=request.user.is_authenticated
    perms=[key for key,code in [('edit','edit_studio'),('publish','publish_release'),('test','test_studio')]
           if auth and request.user.has_perm('game_studio.'+code)]
    pointer=ActiveRelease.objects.filter(pk=1).first()
    return {'authenticated':auth,'user':{'username':request.user.username,'permissions':perms} if auth else None,
            'csrf_token':get_token(request),'environment':'production' if settings.PRODUCTION else 'development',
            'setup_required':bool(settings.STUDIO_SETUP_TOKEN and pointer and not pointer.setup_used and not get_user_model().objects.filter(is_superuser=True).exists()),
            'version':'0.9.2','virtual_credits_only':True}

@api()
def session(request): return reply(session_data(request))

@api(methods=('POST',))
def sign_in(request):
    data=body(request);username=str(data.get('username',''))[:150]
    if not throttle(['login-ip',request.META.get('REMOTE_ADDR')],60) or not throttle(['login-user',username.casefold()],12):
        return reply({'error':'Too many attempts. Retry in five minutes.'},429)
    user=authenticate(request,username=username,password=data.get('password',''))
    if user is None or not user.has_perm('game_studio.test_studio'): return reply({'error':'Invalid Studio credentials'},401)
    login(request,user);audit(user,'login',user.pk)
    return reply(session_data(request))

@api(methods=('POST',))
def sign_out(request):
    logout(request);return reply(session_data(request))

@api(methods=('POST',))
def setup(request):
    data=body(request)
    if not throttle(['setup',request.META.get('REMOTE_ADDR')],8): return reply({'error':'Too many attempts'},429)
    token=data.get('token')
    if not settings.STUDIO_SETUP_TOKEN or not isinstance(token,str) or not secrets.compare_digest(token,settings.STUDIO_SETUP_TOKEN):
        return reply({'error':'Invalid owner activation link'},403)
    with transaction.atomic():
        pointer=ActiveRelease.objects.select_for_update().get(pk=1)
        if pointer.setup_used or get_user_model().objects.filter(is_superuser=True).exists(): return reply({'error':'Owner activation has already been completed'},409)
        user=get_user_model()(username=data.get('username',''),is_superuser=True,is_staff=True)
        user.full_clean(exclude=['password','last_login','date_joined'])
        validate_password(data.get('password',''),user)
        user.set_password(data['password']);user.save()
        user.groups.add(Group.objects.get(name='Owner'))
        pointer.setup_used=True;pointer.save(update_fields=['setup_used'])
        audit(user,'owner_activated',user.pk)
    login(request,user);return reply(session_data(request),201)

def release_data(r,active=None):
    return {'id':str(r.id),'name':r.name,'sha256':r.digest,'created_at':r.created_at.isoformat(),
            'math_version':r.config['math']['version'],
            'engine_sha256':r.engine_hash,'versions':r.versions,'validation':r.validation,'active':str(r.id)==str(active)}
def draft_data(d):
    return {'id':str(d.id),'name':d.name,'revision':d.revision,'config':d.config,'validation':d.validation,
            'status':'validated' if d.validation.get('valid') else 'draft','base_release_id':str(d.base_release_id),'updated_at':d.updated_at.isoformat()}
def job_data(j):
    return {'id':str(j.id),'kind':j.kind,'status':j.status,'progress':j.progress,'result':j.result,'error':j.error,
            'source_asset_id':str(j.request.get('asset_id')) if j.kind in ('ingest','render') and j.request.get('asset_id') else None,
            'created_at':j.created_at.isoformat(),'cancel_requested':j.cancel_requested,'attempts':j.attempts}
def asset_data(a):
    return {'id':str(a.id),'name':a.name,'kind':a.kind,'status':a.status,'sha256':a.sha256,
            'url':f'/api/studio/assets/{a.id}/content','preview_url':f'/api/studio/assets/{a.id}/content',
            'mime':a.mime,'byte_size':a.byte_size,'metadata':a.metadata,'recipe':a.recipe,
            'original_id':str(a.original_id) if a.original_id else None,'is_derivative':a.is_derivative,'published':a.published}

@api('read')
def overview(request):
    active=active_release()
    return reply({'active_release':release_data(active,active.id),'drafts':[draft_data(d) for d in Draft.objects.order_by('-updated_at')[:8]],
        'jobs':[job_data(j) for j in Job.objects.order_by('-created_at')[:12]],
        'stats':{'drafts':Draft.objects.count(),'releases':Release.objects.filter(preview=False).count(),
                 'assets':Asset.objects.filter(is_derivative=True,status='ready').count(),'rounds':Round.objects.filter(session__preview_release=None).count()},
        'baseline_math_unchanged':True,'minimum_validation_rounds':settings.STUDIO_MATH_MIN_ROUNDS})

@api('read',methods=('GET','POST'))
def drafts(request):
    if request.method=='GET': return reply({'drafts':[draft_data(d) for d in Draft.objects.order_by('-updated_at')[:200]]})
    if not request.user.has_perm('game_studio.edit_studio'): return reply({'error':'Permission denied'},403)
    data=body(request);source=Release.objects.get(pk=data['release_id'],preview=False) if data.get('release_id') else active_release()
    name=data.get('name','Untitled draft')
    if not isinstance(name,str) or not 1<=len(name.strip())<=120: raise ValueError('Draft name must be 1–120 characters')
    d=Draft.objects.create(name=name.strip(),config=deepcopy(source.config),base_release=source,created_by=request.user)
    audit(request.user,'draft_created',d.id,base=str(source.id));return reply(draft_data(d),201)

def revision(request,d,data):
    value=request.headers.get('If-Match',str(data.get('revision',''))).strip('"')
    if value!=str(d.revision): raise game.GameError('Draft changed in another tab. Reload the latest revision before saving.',409)

@api('read',methods=('GET','PATCH'))
def draft_detail(request,draft_id):
    if request.method=='GET':
        d=Draft.objects.get(pk=draft_id);response=reply(draft_data(d));response['ETag']=f'"{d.revision}"';return response
    if not request.user.has_perm('game_studio.edit_studio'): return reply({'error':'Permission denied'},403)
    data=body(request)
    with transaction.atomic():
        d=Draft.objects.select_for_update().get(pk=draft_id);revision(request,d,data)
        config=data.get('config',d.config)
        # Draft may be temporarily invalid; reject unsafe shapes/size and preserve validation errors for the UI.
        if not isinstance(config,dict) or len(json.dumps(config,allow_nan=False))>150000: raise ValueError('Invalid draft configuration')
        name=data.get('name',d.name)
        if not isinstance(name,str) or not 1<=len(name.strip())<=120: raise ValueError('Invalid draft name')
        d.config=config;d.name=name.strip();d.revision+=1;d.validation={};d.save()
        audit(request.user,'draft_saved',d.id,revision=d.revision,config_hash=digest(config))
    return reply(draft_data(d))

@api('test',methods=('POST',))
def draft_validate(request,draft_id):
    data=body(request)
    with transaction.atomic():
        d=Draft.objects.select_for_update().get(pk=draft_id);revision(request,d,data)
        result=validate_draft(d)
    return reply(result)

@api('publish',methods=('POST',))
def draft_publish(request,draft_id):
    data=body(request)
    with transaction.atomic():
        d=Draft.objects.select_for_update().get(pk=draft_id);revision(request,d,data)
        r=publish(d,request.user,data.get('reason',''))
    return reply({'release':release_data(r,r.id)},201)

@api('test',methods=('POST',))
def draft_preview(request,draft_id):
    data=body(request)
    with transaction.atomic():
        d=Draft.objects.select_for_update().get(pk=draft_id);revision(request,d,data)
        checked=validate_draft(d)
        if not checked['valid']: raise ValueError('; '.join(checked['errors']))
        r=make_release(d.config,'Preview: '+d.name,request.user,checked,preview=True)
    token=signing.dumps({'release':str(r.id),'user':request.user.pk},salt='studio-preview')
    return reply({'url':'/studio/preview/'+token,'release_id':str(r.id)})

@api('test',methods=('POST',))
def simulate(request,draft_id):
    data=body(request)
    with transaction.atomic():
        d=Draft.objects.select_for_update().get(pk=draft_id);revision(request,d,data)
        valid=validate_config(d.config)
        if not valid['valid']: raise ValueError('; '.join(valid['errors']))
        rounds=integer(data.get('rounds',100000),100,settings.STUDIO_MATH_MAX_ROUNDS,'simulation rounds')
        if Job.objects.filter(status__in=['queued','running'],kind='simulate').count()>=3: return reply({'error':'Math Lab queue is full. Wait for a job or cancel one.'},429)
        target=data.get('target_rtp')
        if target is not None: target=float(decimal_value(target,0,1000,'target RTP percent'))
        j=Job.objects.create(kind='simulate',created_by=request.user,request={'config':d.config,
            'config_hash':digest(d.config),'engine_hash':ENGINE_HASH,'rounds':rounds,'draft_id':str(d.id),'revision':d.revision,
            'seed_domain':str(data.get('seed_domain','validation'))[:80],
            'validation_domains':[secrets.token_hex(24),secrets.token_hex(24)],'target_rtp':target})
        audit(request.user,'simulation_queued',j.id,draft=str(d.id),rounds=rounds)
    return reply({'job':job_data(j)},202)

@api('read',methods=('GET','POST'))
def assets(request):
    if request.method=='GET': return reply({'assets':[asset_data(a) for a in Asset.objects.order_by('-created_at')[:500]]})
    if not request.user.has_perm('game_studio.edit_studio'): return reply({'error':'Permission denied'},403)
    kind=request.POST.get('kind');file=request.FILES.get('file')
    if kind not in ('tile','scene','audio') or file is None: raise ValueError('Choose file and kind (tile/scene/audio)')
    limit=(32 if kind=='audio' else 16)*1024*1024
    if not 0<file.size<=limit: return reply({'error':f'Upload limit: {limit//1024//1024} MiB'},413)
    if not throttle(['upload',request.user.pk],30,3600): return reply({'error':'Hourly upload limit reached'},429)
    if Job.objects.filter(status__in=['queued','running'],kind__in=['ingest','render']).count()>=50: return reply({'error':'Media queue full'},429)
    data=file.read();stored=content_store().put(data,'bin')
    name=Path(file.name.replace('\\','/')).name[:180]
    with transaction.atomic():
        a=Asset.objects.create(name=name,kind=kind,object_key=stored['key'],sha256=stored['sha256'],byte_size=len(data),created_by=request.user)
        j=Job.objects.create(kind='ingest',request={'asset_id':str(a.id),'recipe':{}},created_by=request.user)
        audit(request.user,'asset_uploaded',a.id,kind=kind,sha256=a.sha256)
    return reply({'asset':asset_data(a),'job':job_data(j)},202)

@api('edit',methods=('POST',))
def asset_render(request,asset_id):
    data=body(request);a=Asset.objects.get(pk=asset_id)
    if a.status!='ready': raise ValueError('Asset must be Ready before rendering')
    original=a.original or a
    recipe=data.get('recipe',{})
    if not isinstance(recipe,dict) or len(json.dumps(recipe))>10000: raise ValueError('Invalid render recipe')
    if Job.objects.filter(status__in=['queued','running'],kind__in=['ingest','render']).count()>=50: return reply({'error':'Media queue full'},429)
    j=Job.objects.create(kind='render',request={'asset_id':str(original.id),'recipe':recipe},created_by=request.user)
    return reply({'job':job_data(j)},202)

@api('edit',methods=('POST',))
def import_baseline(request):
    data=body(request);path=data.get('path')
    if path not in BASELINE_REFS: raise ValueError('Not an allowlisted baseline source')
    if not throttle(['upload',request.user.pk],30,3600): return reply({'error':'Hourly upload limit reached'},429)
    source=(WEB/path.lstrip('/')).resolve()
    if not source.is_relative_to(WEB.resolve()) or not source.is_file(): raise ValueError('Build baseline artwork before importing')
    kind='audio' if path==BASE_MUSIC or path in BASE_AUDIO.values() else 'tile'
    raw=source.read_bytes();stored=content_store().put(raw,'bin')
    with transaction.atomic():
        a=Asset.objects.create(name=source.name,kind=kind,object_key=stored['key'],sha256=stored['sha256'],byte_size=len(raw),created_by=request.user)
        j=Job.objects.create(kind='ingest',request={'asset_id':str(a.id),'recipe':{}},created_by=request.user)
        audit(request.user,'baseline_imported',a.id,path=path)
    return reply({'asset':asset_data(a),'job':job_data(j)},202)

@api('read')
def asset_content(request,asset_id):
    a=Asset.objects.get(pk=asset_id,status='ready')
    if not a.is_derivative: raise game.GameError('Original uploads are kept private; use the verified derivative',403)
    response=HttpResponse(content_store().get(a.object_key),content_type=a.mime)
    response['Content-Disposition']='inline';return response

@api()
def published_media(request,asset_id,sha):
    a=Asset.objects.get(pk=asset_id,sha256=sha,status='ready',published=True,is_derivative=True)
    response=HttpResponse(content_store().get(a.object_key),content_type=a.mime)
    response['Cache-Control']='public, max-age=31536000, immutable';response['ETag']='"'+sha+'"'
    return response

@api('read')
def jobs(request): return reply({'jobs':[job_data(j) for j in Job.objects.order_by('-created_at')[:100]]})

@api('test',methods=('POST',))
def job_cancel(request,job_id):
    body(request)
    with transaction.atomic():
        j=Job.objects.select_for_update().get(pk=job_id)
        if j.status in ('queued','running'):
            j.cancel_requested=True
            if j.status=='queued': j.status='cancelled'
            j.save()
    return reply({'job':job_data(j)})

@api('read')
def releases(request):
    active=active_release()
    return reply({'releases':[release_data(r,active.id) for r in Release.objects.filter(preview=False).order_by('-created_at')[:200]],
        'audit':[{'action':a.action,'target':a.target,'detail':a.detail,'created_at':a.created_at.isoformat()} for a in AuditEvent.objects.order_by('-created_at')[:100]]})

@api('publish',methods=('POST',))
def release_activate(request,release_id):
    data=body(request);r=activate(Release.objects.get(pk=release_id),request.user,data.get('reason',''))
    return reply({'release':release_data(r,r.id)})

def preview_release(request,token):
    if not request.user.is_authenticated or not request.user.has_perm('game_studio.test_studio'): raise game.GameError('Studio preview sign-in required',403)
    try: data=signing.loads(token,salt='studio-preview',max_age=3600)
    except signing.BadSignature as exc: raise game.GameError('Preview expired; create a new preview',403) from exc
    if data.get('user')!=request.user.pk: raise game.GameError('Preview belongs to another editor',403)
    return Release.objects.get(pk=data['release'],preview=True)

@api()
def preview_page(request,token):
    preview_release(request,token)
    html=(WEB/'index.html').read_text()
    html=html.replace('<head>','<head><meta name="studio-api-base" content="/api/preview/'+token+'">',1)
    return HttpResponse(html,content_type='text/html; charset=utf-8')

@csrf_exempt
@api(methods=('GET','POST'))
def public_api(request,operation,preview_token=None):
    if operation not in ('state','spin','reset','verify','last-round','diagnostics/spin'): return reply({'error':'Not found'},404)
    if request.method=='POST':
        if operation in ('state','last-round'): return reply({'error':'Method not allowed'},405)
        if request.headers.get('X-ML-Request')!='local-demo': return reply({'error':'Required game request header missing'},403)
        origin=request.headers.get('Origin');expected=('https://' if request.is_secure() else 'http://')+request.get_host()
        if request.headers.get('Sec-Fetch-Site')=='cross-site' or (origin and origin!=expected) or (settings.PRODUCTION and not origin):
            return reply({'error':'Same-origin request required'},403)
        data=body(request)
    elif operation not in ('state','last-round'): return reply({'error':'Method not allowed'},405)
    if operation=='diagnostics/spin': return reply({'accepted':True},202)
    preview=preview_release(request,preview_token) if preview_token else None
    cookie='MLPREVIEW' if preview else 'MLGAME'
    candidate=request.COOKIES.get(cookie,'')
    known=bool(len(candidate)<=100 and PlayerSession.objects.filter(token_hash=sha256(candidate.encode()),preview_release=preview).exists())
    if not known and not preview:
        # Use a global rolling allocation budget as well as the durable cap.
        # It cannot be evaded by forging untrusted forwarding headers.
        if not throttle(['public-session-allocation'],500,3600): return reply({'error':'New demo sessions are temporarily rate limited. Please retry later.'},429)
    player,token,fresh=game.obtain(request.COOKIES.get(cookie),preview)
    if operation=='state':
        result=game.state(player)
        if fresh and request.COOKIES.get('MLSESSION') and not preview:
            result['migration_notice']='Engine diperbarui ke sesi permanen. Sesi demo sebelumnya disimpan di memori; saldo virtual dimulai kembali dari konfigurasi awal.'
    elif operation=='spin': result=game.spin(player,data.get('bet'),data.get('ticket_id'),data.get('idempotency_key'))
    elif operation=='reset': result=game.reset(player)
    elif operation=='verify': result=game.verify(player,data.get('round'))
    else: result=game.last_round(player)
    response=reply(result)
    if fresh: response.set_cookie(cookie,token,max_age=30*86400,httponly=True,secure=settings.PRODUCTION,samesite='Lax')
    return response

@api()
def health(request):
    from django.db import connection
    with connection.cursor() as cursor: cursor.execute('SELECT 1')
    active=active_release()
    worker=WorkerHeartbeat.objects.filter(pk='studio-worker').first()
    return reply({'ok':True,'game':'Mahjong Wild','version':'0.9.2','math_version':active.config['math']['version'],
        'engine_sha256':ENGINE_HASH,'storage':'postgresql' if connection.vendor=='postgresql' else 'sqlite-local',
        'worker_ready':bool(worker and (timezone.now()-worker.seen_at).total_seconds()<120)})

@api()
def static_page(request,path=''):
    if path.startswith('studio'):
        relative=path if path.startswith('studio/assets/') else 'studio/index.html'
    elif path.startswith('assets/') or path in ('app.js','style.css','manifest.webmanifest','sw.js'):
        relative=path
    elif path in ('','index.html'): relative='index.html'
    else: return reply({'error':'Not found'},404)
    target=(WEB/relative).resolve()
    if not target.is_relative_to(WEB.resolve()) or not target.is_file(): return reply({'error':'Not found'},404)
    mime=mimetypes.guess_type(target.name)[0] or 'application/octet-stream'
    if target.suffix=='.js': mime='application/javascript'
    if target.suffix=='.m4a': mime='audio/mp4'
    response=FileResponse(target.open('rb'),content_type=mime)
    if path=='sw.js': response['Service-Worker-Allowed']='/'
    return response
