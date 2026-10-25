"""Durable, leased jobs. Media and simulation never run in a Spin request."""
from datetime import timedelta
from decimal import Decimal
import math
import os
import secrets
import time
from django.conf import settings
from django.db import transaction, connection
from django.db.models import Q
from django.utils import timezone
from mahjong_legend.engine import GameConfig, play_round, sha256
from .domain import digest, ENGINE_HASH
from .models import Job, Asset, WorkerHeartbeat
from .media import inspect_upload, render_tile, render_scene, process_audio
from .storage import ContentStore

class Cancelled(Exception): pass

@transaction.atomic
def claim():
    now=timezone.now()
    query=Job.objects.filter(Q(status='queued')|Q(status='running',lease_until__lt=now)).order_by('created_at')
    query=query.select_for_update(skip_locked=True) if connection.features.has_select_for_update_skip_locked else query.select_for_update()
    job=query.first()
    if not job: return None
    if job.cancel_requested or job.attempts>=3:
        job.status='cancelled' if job.cancel_requested else 'failed';job.error='Cancelled' if job.cancel_requested else 'Recovery attempt limit reached'
        job.save(update_fields=['status','error','updated_at']);return None
    job.status='running';job.fence+=1;job.attempts+=1;job.lease_until=now+timedelta(seconds=settings.STUDIO_JOB_LEASE_SECONDS)
    job.save(update_fields=['status','fence','attempts','lease_until','updated_at']);return job

def heartbeat(job,progress):
    WorkerHeartbeat.objects.update_or_create(name='studio-worker',defaults={'seen_at':timezone.now()})
    current=Job.objects.get(pk=job.pk)
    if current.fence!=job.fence or current.status!='running' or current.cancel_requested: raise Cancelled()
    count=Job.objects.filter(pk=job.pk,fence=job.fence,status='running',cancel_requested=False).update(
        progress=min(99.9,progress),lease_until=timezone.now()+timedelta(seconds=settings.STUDIO_JOB_LEASE_SECONDS),updated_at=timezone.now())
    if not count: raise Cancelled()

@transaction.atomic
def finish(job,result,asset_fields=None,original_fields=None):
    locked=Job.objects.select_for_update().get(pk=job.pk)
    if locked.fence!=job.fence or locked.status!='running': return
    if locked.cancel_requested:
        locked.status='cancelled'
    else:
        if original_fields:
            asset_id,fields=original_fields
            Asset.objects.filter(pk=asset_id,is_derivative=False).update(**fields)
        if asset_fields:
            asset=Asset.objects.create(**asset_fields)
            result['asset_id']=str(asset.id)
        locked.status='succeeded';locked.progress=100;locked.result=result
    locked.lease_until=None;locked.save(update_fields=['status','progress','result','lease_until','updated_at'])

def _media(job):
    asset=Asset.objects.get(pk=job.request['asset_id'])
    store=ContentStore(root=None if os.environ.get('STUDIO_S3_BUCKET') else settings.STUDIO_MEDIA_ROOT);data=store.get(asset.object_key)
    metadata=inspect_upload(data,asset.name,asset.kind)
    heartbeat(job,15)
    recipe=job.request.get('recipe',{})
    if asset.kind=='tile':
        output=render_tile(data,recipe);extension='png';mime='image/png'
        derived=inspect_upload(output,'tile.png','tile')
    elif asset.kind=='scene':
        if recipe: raise ValueError('Scene images use full-image import; no unsupported recipe operations')
        output=render_scene(data);extension='webp';mime='image/webp'
        derived=inspect_upload(output,'scene.webp','scene')
    else:
        result=process_audio(data,asset.name,recipe)
        output=result['data'];extension=result['extension'];mime=result['mime'];derived=result['metadata'];recipe=result['recipe']
    heartbeat(job,90)
    stored=store.put(output,extension)
    original=asset.original or asset
    # Original metadata is useful in Studio, but originals never become publishable.
    finish(job,{'sha256':stored['sha256'],'metadata':derived},asset_fields={
        'name':asset.name.rsplit('.',1)[0]+'.'+extension,'kind':asset.kind,'status':'ready',
        'object_key':stored['key'],'sha256':stored['sha256'],'mime':mime,'byte_size':len(output),
        'metadata':derived,'recipe':recipe,'original':original,'is_derivative':True,'created_by':job.created_by},
        original_fields=(asset.pk,{'status':'ready','metadata':metadata,'mime':metadata.get('mime',asset.mime)}))

def _simulate(job):
    cfg=GameConfig(job.request['config']['math']);n=job.request['rounds']
    domains=job.request['validation_domains'];start=time.monotonic();total=total2=0.0
    positive=returned=bonus=caps=0;cohorts=[];seen=0;last_heartbeat=start
    for ci,count in enumerate((n//2,n-n//2)):
        subtotal=0.0
        for index in range(count):
            seed=sha256(f'math-lab-v1:{domains[ci]}:{index}'.encode())
            outcome=play_round(seed,cfg);p=float(outcome['total_payout_x'])
            total+=p;total2+=p*p;subtotal+=p;seen+=1
            positive+=int(p>0);returned+=int(p>=1);bonus+=int(outcome['free_spins_played']>0);caps+=int(outcome['capped'])
            if time.monotonic()-last_heartbeat>=1 or seen==n:
                heartbeat(job,100*seen/n);last_heartbeat=time.monotonic()
        cohorts.append({'rounds':count,'rtp_percent':100*subtotal/count,'seed_domain':domains[ci]})
    mean=total/n;variance=max(0,(total2-n*mean*mean)/(n-1));margin=1.96*math.sqrt(variance/n)
    ci=[100*(mean-margin),100*(mean+margin)]
    result={'rounds':n,'rtp_percent':100*mean,'rtp_ci95_percent':ci,
        'positive_payout_percent':100*positive/n,'return_at_least_stake_percent':100*returned/n,
        'bonus_entry_percent':100*bonus/n,'cap_count':caps,'failures':0,'independent_validation':True,
        'cohorts':cohorts,'config_sha256':cfg.digest,'engine_sha256':ENGINE_HASH,'elapsed_seconds':round(time.monotonic()-start,3),
        'publish_sample_gate':n>=settings.STUDIO_MATH_MIN_ROUNDS,
        'confidence_method':'Normal approximation; rare capped tails can require substantially more samples. Estimate, not a guaranteed RTP.',
        'denominator':'One stake per paid round; award includes all free spins and retriggers.'}
    target=job.request.get('target_rtp')
    if target is not None: result.update(target_rtp_percent=target,target_in_ci=ci[0]<=target<=ci[1])
    finish(job,result)

def run_one():
    job=claim()
    if not job: return False
    try:
        if job.kind in ('ingest','render'): _media(job)
        elif job.kind=='simulate': _simulate(job)
        else: raise ValueError('Unknown job type')
    except Cancelled:
        Job.objects.filter(pk=job.pk,fence=job.fence,status='running').update(status='cancelled',lease_until=None,updated_at=timezone.now())
    except Exception as exc:
        # Known data validation messages are actionable; infrastructure paths/secrets stay in server logs only.
        message=str(exc)[:450] if isinstance(exc,ValueError) else f'Processing failed ({type(exc).__name__}); retry or inspect worker logs'
        with transaction.atomic():
            locked=Job.objects.select_for_update().get(pk=job.pk)
            if locked.fence==job.fence and locked.status=='running':
                locked.status='failed';locked.error=message;locked.lease_until=None;locked.save(update_fields=['status','error','lease_until','updated_at'])
                if job.kind=='ingest': Asset.objects.filter(pk=job.request.get('asset_id'),is_derivative=False).update(status='failed')
    return True
