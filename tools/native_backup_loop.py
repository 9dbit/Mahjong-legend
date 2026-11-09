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

def run(argv=None):
    parser=argparse.ArgumentParser()
    parser.add_argument('--database',required=True)
    parser.add_argument('--game',required=True)
    args=parser.parse_args(argv)
    interval=max(3600,int(os.getenv('ENGINE_BACKUP_INTERVAL_SECONDS','86400')))
    status_file=Path('/data/mahjong-backup-status.json')
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
            status_file.write_text(json.dumps({'backup_verified':True,'verified_at':datetime.now(timezone.utc).isoformat(),'object':result['object'],'sha256':result['manifest']['sha256']}))
            print(json.dumps({'event':'engine.backup.remote_verified','game':args.game,
                              'object':result['object'],'sha256':result['manifest']['sha256']}),flush=True)
        except Exception as exc:
            retry_seconds=min(interval,300)
            try: status_file.write_text(json.dumps({'backup_verified':False,'failed_at':datetime.now(timezone.utc).isoformat(),'error_type':type(exc).__name__}))
            except OSError: pass
            print(json.dumps({'event':'engine.backup.failed','game':args.game,'error_type':type(exc).__name__,
                              'error':str(exc)[:160]}),file=sys.stderr,flush=True)
        time.sleep(retry_seconds)
if __name__=='__main__':
    run()
