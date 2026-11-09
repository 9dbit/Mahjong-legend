"""Bounded retention after verification; never assumes Railway lifecycle or WORM."""
import hashlib, json, re, time
from datetime import datetime, timedelta, timezone
POLICY = 'native-7d-4w-12m-v1'
DAY = 86400


def _week(seconds):
    d = datetime.fromtimestamp(seconds, timezone.utc)
    return (d.replace(hour=0,minute=0,second=0,microsecond=0)-timedelta(days=d.weekday())).timestamp()


def _month(seconds):
    d = datetime.fromtimestamp(seconds, timezone.utc); return d.year*12+d.month-1


def retention_plan(keys, *, game, now=None, restoring_object=None, max_deletes=5):
    now = int(time.time()) if now is None else now
    if not re.fullmatch(r'[a-z0-9-]{1,32}', game) or type(now) is not int or type(max_deletes) is not int or not 1 <= max_deletes <= 10:
        raise RuntimeError('RETENTION_CONFIG_INVALID')
    pattern = re.compile(r'^native/' + game + r'/([0-9]{10})-([a-f0-9]{16})-([a-f0-9]{16})\.aesgcm$')
    records, ignored, seen = [], [], set()
    for key in keys:
        if not isinstance(key,str): raise RuntimeError('RETENTION_INVENTORY_INVALID')
        if key in seen: raise RuntimeError('RETENTION_DUPLICATE_INVENTORY')
        seen.add(key); match=pattern.fullmatch(key)
        if not match: ignored.append(key); continue
        at=int(match[1])
        if at>now: raise RuntimeError('RETENTION_FUTURE_OBJECT')
        records.append({'key':key,'created_at':at,'hash_prefix':match[2]})
    records.sort(key=lambda r:(r['created_at'],r['key']), reverse=True)
    keep={r['key'] for r in records[:2]}; periods=set(); representatives=set()
    if restoring_object: keep.add(restoring_object)
    for r in records:
        age=now-r['created_at']
        if age<7*DAY: keep.add(r['key'])
        periods_for_record=(('day',now//DAY-r['created_at']//DAY,7),('week',int((_week(now)-_week(r['created_at']))/(7*DAY)),4),('month',_month(now)-_month(r['created_at']),12))
        for name,index,limit in periods_for_record:
            label=(name,index)
            if 0<=index<limit and label not in periods:
                periods.add(label);keep.add(r['key'])
                if age>=7*DAY: representatives.add(r['key'])
    candidates=list(reversed([r for r in records if r['key'] not in keep and now-r['created_at']>=7*DAY]))[:max_deletes]
    verify_keys={r['key'] for r in records[:2]}|representatives|{r['key'] for r in candidates}
    return {'records':records,'keep':sorted(keep),'ignored':ignored,'candidates':candidates,'verify_keys':sorted(verify_keys)}


def enforce_retention(*, game, identity, current_object, current_ciphertext_sha256, list_page, download, remove, verify,
                      now=None, restoring_object=None, mode='dry-run', max_objects=4096, max_deletes=5, logger=lambda event:None):
    now=int(time.time()) if now is None else now
    report={'policy':POLICY,'enabled':True,'mode':mode,'verified':False,'inventory_count':0,'managed_count':0,'retained_count':0,'protected_unknown_count':0,'eligible_count':0,'deleted_count':0,'verified_at':datetime.fromtimestamp(now,timezone.utc).isoformat()}
    try:
        if mode not in ('dry-run','apply') or not identity or not current_object or not re.fullmatch(r'[a-f0-9]{64}',current_ciphertext_sha256): raise RuntimeError('RETENTION_CONFIG_INVALID')
        keys=[];tokens=set();token=None
        while True:
            page=list_page(token)
            if not isinstance(page,dict) or not isinstance(page.get('keys'),list): raise RuntimeError('RETENTION_INVENTORY_INVALID')
            keys.extend(page['keys'])
            if len(keys)>max_objects: raise RuntimeError('RETENTION_INVENTORY_LIMIT')
            token=page.get('next_token')
            if not token:break
            if token in tokens: raise RuntimeError('RETENTION_PAGINATION_LOOP')
            tokens.add(token)
        report['inventory_count']=len(keys)
        if current_object not in keys: raise RuntimeError('RETENTION_CURRENT_OBJECT_MISSING')
        plan=retention_plan(keys,game=game,now=now,restoring_object=restoring_object,max_deletes=max_deletes)
        report.update(managed_count=len(plan['records']),protected_unknown_count=len(plan['ignored']),retained_count=len(plan['keep']),eligible_count=len(plan['candidates']))
        required=set(plan['verify_keys'])|{current_object}
        if len(required)>32: raise RuntimeError('RETENTION_VERIFICATION_LIMIT')
        records={r['key']:r for r in plan['records']};proofs={}
        for key in sorted(required):
            record=records.get(key)
            if not record: raise RuntimeError('RETENTION_OBJECT_SCOPE_INVALID')
            response=download(key)
            if not isinstance(response,dict) or not isinstance(response.get('bytes'),bytes): raise RuntimeError('RETENTION_DOWNLOAD_INVALID')
            digest=hashlib.sha256(response['bytes']).hexdigest()
            if key==current_object and digest!=current_ciphertext_sha256: raise RuntimeError('RETENTION_CURRENT_CIPHERTEXT_CHANGED')
            manifest=verify(response['bytes'])
            if not isinstance(manifest,dict) or manifest.get('game')!=game or manifest.get('created_at')!=record['created_at'] or not str(manifest.get('sha256','')).startswith(record['hash_prefix']) or manifest.get('deployment_identity')!=identity:
                raise RuntimeError('RETENTION_FOREIGN_OR_MALFORMED_MANIFEST')
            if key==current_object and not 0<=now-manifest['created_at']<=25*3600: raise RuntimeError('RETENTION_CURRENT_BACKUP_STALE')
            proofs[key]={'digest':digest,'etag':response.get('etag')}
        report['planned_objects']=[r['key'] for r in plan['candidates']]
        logger({'event':'engine.backup.retention_plan',**report})
        if mode=='apply':
            for candidate in plan['candidates']:
                proof=proofs[candidate['key']];etag=proof['etag']
                if not isinstance(etag,str) or not etag or '\r' in etag or '\n' in etag: raise RuntimeError('RETENTION_CONDITIONAL_DELETE_UNAVAILABLE')
                remove(candidate['key'],etag);report['deleted_count']+=1
        report['verified']=True;logger({'event':'engine.backup.retention_completed',**report});return report
    except Exception as error:
        report['error_code']=str(error) if re.fullmatch(r'RETENTION_[A-Z_]+',str(error)) else 'RETENTION_OPERATION_FAILED'
        logger({'event':'engine.backup.retention_blocked',**report});return report
