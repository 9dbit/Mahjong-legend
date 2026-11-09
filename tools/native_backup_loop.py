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
sys.path.insert(0,str(Path(__file__).resolve().parent))
from native_backup import backup_once,restore_verify

def run():
    parser=argparse.ArgumentParser()
    parser.add_argument('--database',required=True)
    parser.add_argument('--game',required=True)
    args=parser.parse_args()
    interval=max(3600,int(os.getenv('ENGINE_BACKUP_INTERVAL_SECONDS','86400')))
    while True:
        try:
            if not Path(args.database).is_file():
                print(json.dumps({'event':'engine.backup.waiting_for_db','game':args.game}),flush=True)
                time.sleep(30)
                continue
            print(json.dumps({'event':'engine.backup.started','game':args.game}),flush=True)
            result=backup_once(args.database,args.game,os.environ['ENGINE_BACKUP_S3_BUCKET'],'native')
            print(json.dumps({'event':'engine.backup.remote_verified','game':args.game,
                              'object':result['object'],'sha256':result['manifest']['sha256']}),flush=True)
        except Exception as exc:
            print(json.dumps({'event':'engine.backup.failed','game':args.game,'error_type':type(exc).__name__,
                              'error':str(exc)[:160]}),file=sys.stderr,flush=True)
        time.sleep(interval)
if __name__=='__main__':
    run()
