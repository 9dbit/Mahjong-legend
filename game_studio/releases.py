from copy import deepcopy
import uuid
import json
import wave
from pathlib import Path
from django.db import transaction
from django.conf import settings
from .domain import baseline_config, digest, validate_config, asset_refs, BASELINE_REFS, BASE_MUSIC, ENGINE_HASH
from .models import ConfigurationVersion, Release, ActiveRelease, Asset, AuditEvent, Job

def audit(actor, action, target, **detail):
    return AuditEvent.objects.create(actor=actor,action=action,target=str(target),detail=detail)

def make_release(config, name, actor=None, validation=None, preview=False):
    key=digest({'config':config,'engine':ENGINE_HASH,'preview':preview})
    existing=Release.objects.filter(digest=key).first()
    if existing: return existing
    versions={}
    for kind in ('math','bet','presentation','tiles','scene','audio'):
        v,_=ConfigurationVersion.objects.get_or_create(kind=kind,digest=digest(config[kind]),defaults={'data':config[kind]})
        versions[kind]={'id':str(v.id),'sha256':v.digest}
    release,_=Release.objects.get_or_create(digest=key,defaults={'name':name[:120],'config':deepcopy(config),'versions':versions,
        'engine_hash':ENGINE_HASH,'created_by':actor,'validation':validation or {},'preview':preview})
    return release

@transaction.atomic
def bootstrap():
    existing=ActiveRelease.objects.filter(pk=1).first()
    if existing: return existing.release
    release=make_release(baseline_config(),'Baseline UI 0.9.0 / math 0.8.0',validation={
        'valid':True,'baseline':True,'math_changed':False,
        'note':'Exact legacy math snapshot; prior 5M audit retained. No recalibration.'})
    ActiveRelease.objects.get_or_create(pk=1,defaults={'release':release})
    return release

def active_release():
    return ActiveRelease.objects.select_related('release').get(pk=1).release

def resolve_asset(ref, private=False):
    if ref in BASELINE_REFS: return ref
    asset=Asset.objects.get(pk=uuid.UUID(str(ref)),status='ready',is_derivative=True)
    return f'/api/studio/assets/{asset.id}/content' if private else f'/media/{asset.id}/{asset.sha256}'

def manifest(release, private=False):
    config=deepcopy(release.config)
    for s, variants in config['tiles'].items():
        for v,ref in variants.items(): config['tiles'][s][v]=resolve_asset(ref,private)
    for slot,ref in config['scene'].items():
        if ref: config['scene'][slot]=resolve_asset(ref,private)
    for e in config['audio']['events'].values():
        if e.get('enabled') and e.get('asset'): e['asset']=resolve_asset(e['asset'],private)
    for m in config['audio']['music'].values():
        if m and m.get('asset'): m['asset']=resolve_asset(m['asset'],private)
    return {'release_id':str(release.id),'release_sha256':release.digest,'engine_sha256':release.engine_hash,
        'schema_version':1, **{k:config[k] for k in ('bet','presentation','tiles','scene','audio')}}

def validate_draft(draft):
    result=validate_config(draft.config)
    if result['valid']:
        for ref,kind,label in asset_refs(draft.config):
            if ref in BASELINE_REFS: continue
            try:
                a=Asset.objects.get(pk=uuid.UUID(ref),kind=kind,status='ready',is_derivative=True)
                if kind=='tile' and [a.metadata.get('width'),a.metadata.get('height')]!=[218,327]:
                    raise ValueError('Tile derivative must be 218×327')
            except (Asset.DoesNotExist,ValueError,TypeError): result['errors'].append(label+': asset derivative is missing or not Ready')
        for slot,value in draft.config['audio']['music'].items():
            if not value: continue
            try:
                if value['asset']==BASE_MUSIC:
                    length=float(json.loads((settings.BASE_DIR/'web/assets/approved-v082/audio/music.json').read_text())['seconds'])
                elif value['asset'] in BASELINE_REFS:
                    with wave.open(str(settings.BASE_DIR/'web'/value['asset'].lstrip('/')),'rb') as clip:
                        length=clip.getnframes()/clip.getframerate()
                else:
                    a=Asset.objects.get(pk=value['asset']);length=float(a.metadata['duration'])
                if float(value.get('loop_start',0))>=length or (value.get('loop_end') is not None and float(value['loop_end'])>length+.001):
                    result['errors'].append('Music loop exceeds rendered audio duration: '+slot)
            except (Asset.DoesNotExist,ValueError,TypeError,KeyError,OSError,wave.Error):
                result['errors'].append('Music duration could not be verified: '+slot)
    result['valid']=not result['errors']
    result['receipt']={'hash':digest(draft.config),'revision':draft.revision,'engine_sha256':ENGINE_HASH}
    draft.validation=result
    draft.save(update_fields=['validation'])
    return result

@transaction.atomic
def publish(draft, actor, reason):
    # Caller holds the draft lock. Receipt binds exact revision + immutable bytes.
    receipt=draft.validation
    if not receipt.get('valid') or receipt.get('receipt',{}).get('hash')!=digest(draft.config) or receipt['receipt'].get('revision')!=draft.revision:
        raise ValueError('Validate this exact draft revision before publishing')
    result=validate_draft(draft)
    if not result['valid']: raise ValueError('; '.join(result['errors']))
    baseline_hash=digest(baseline_config()['math'])
    if digest(draft.config['math'])!=baseline_hash:
        jobs=Job.objects.filter(kind='simulate',status='succeeded').order_by('-created_at')
        valid_job=next((j for j in jobs if j.request.get('config_hash')==digest(draft.config)
            and j.request.get('engine_hash')==ENGINE_HASH and j.result.get('rounds',0)>=settings.STUDIO_MATH_MIN_ROUNDS
            and j.result.get('independent_validation') is True and j.result.get('failures',1)==0),None)
        if not valid_job: raise ValueError(f'Independent Math Lab validation of at least {settings.STUDIO_MATH_MIN_ROUNDS:,} paid rounds is required for this exact draft')
        result['math_lab_job']=str(valid_job.id)
        result['math_lab']=valid_job.result
    if not isinstance(reason,str) or not reason.strip(): raise ValueError('Publication reason required')
    pointer=ActiveRelease.objects.select_for_update().get(pk=1)
    release=make_release(draft.config,draft.name,actor,result)
    ids=[ref for ref,_,_ in asset_refs(draft.config) if ref not in BASELINE_REFS]
    Asset.objects.filter(pk__in=ids).update(published=True)
    previous=str(pointer.release_id)
    pointer.release=release; pointer.generation+=1; pointer.save(update_fields=['release','generation','changed_at'])
    audit(actor,'publish',release.id,reason=reason[:1000],previous=previous,config_hash=digest(draft.config),revision=draft.revision)
    return release

@transaction.atomic
def activate(release, actor, reason):
    if release.preview or release.engine_hash!=ENGINE_HASH: raise ValueError('Release is not compatible with this engine')
    if not isinstance(reason,str) or not reason.strip(): raise ValueError('Rollback reason required')
    pointer=ActiveRelease.objects.select_for_update().get(pk=1)
    previous=str(pointer.release_id);pointer.release=release;pointer.generation+=1
    pointer.save(update_fields=['release','generation','changed_at'])
    audit(actor,'rollback',release.id,previous=previous,reason=reason[:1000])
    return release
