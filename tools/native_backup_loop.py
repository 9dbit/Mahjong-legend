"""Optional native backup loop: first attempt at startup, then every 24h.

Runs inside the existing engine service because its SQLite volume is not shared.
Does not block game startup. Failures are logged and retried.
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path
from datetime import datetime,timezone
sys.path.insert(0,str(Path(__file__).resolve().parent))
from native_backup import backup_once,restore_verify
from native_backup_status import write_backup_status

def run(argv=None, *, status_file=None):
    parser=argparse.ArgumentParser()
    parser.add_argument('--database',required=True)
    parser.add_argument('--game',required=True)
    args=parser.parse_args(argv)
    interval=max(3600,int(os.getenv('ENGINE_BACKUP_INTERVAL_SECONDS','86400')))
    source_commit=os.getenv('RAILWAY_GIT_COMMIT_SHA','')
    status_file=Path(status_file) if status_file is not None else Path('/data/mahjong-backup-status.json')
    print(json.dumps({'event':'engine.backup.worker_started','game':args.game,'interval_seconds':interval}),flush=True)
    while True:
        retry_seconds=interval
        try:
            if not Path(args.database).is_file():
                print(json.dumps({'event':'engine.backup.waiting_for_db','game':args.game}),flush=True)
                time.sleep(30)
                continue
            print(json.dumps({'event':'engine.backup.started','game':args.game}),flush=True)
            result=backup_once(args.database,args.game,os.environ['ENGINE_BACKUP_S3_BUCKET'],'native')
            if result.get('verified') is not True:
                raise RuntimeError('Backup verification was not confirmed')
            write_backup_status(status_file,{'backup_verified':True,'verified_at':datetime.now(timezone.utc).isoformat(),'source_commit':source_commit,'object':result['object'],'sha256':result['manifest']['sha256'],'ciphertext_sha256':result.get('ciphertext_sha256'),'key_id':result.get('key_id')})
            print(json.dumps({'event':'engine.backup.remote_verified','game':args.game,
                              'object':result['object'],'sha256':result['manifest']['sha256'],'ciphertext_sha256':result.get('ciphertext_sha256'),'key_id':result.get('key_id')}),flush=True)
        except Exception as exc:
            retry_seconds=min(interval,300)
            try: write_backup_status(status_file,{'backup_verified':False,'failed_at':datetime.now(timezone.utc).isoformat(),'source_commit':source_commit,'error_type':type(exc).__name__})
            except OSError: pass
            print(json.dumps({'event':'engine.backup.failed','game':args.game,'error_type':type(exc).__name__,
                              'error':str(exc)[:160]}),file=sys.stderr,flush=True)
        time.sleep(retry_seconds)
if __name__=='__main__':
    run()
