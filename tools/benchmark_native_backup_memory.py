"""Measure frozen native backup memory using disposable SQLite + filesystem S3 fixture."""
import argparse,contextlib,hashlib,importlib.util,json,os,pathlib,resource,sqlite3,tempfile,time
import boto3
from botocore.exceptions import ClientError

p=argparse.ArgumentParser()
p.add_argument('--mib',type=int,required=True)
p.add_argument('--retention',action='store_true')
args=p.parse_args()
def rss_kib():
    return int(pathlib.Path('/proc/self/status').read_text().split('VmRSS:')[1].split()[0])
with tempfile.TemporaryDirectory(prefix='native-memory-sizing-') as directory:
    root=pathlib.Path(directory);db=root/'native.sqlite';objects=root/'objects';objects.mkdir()
    identity={'environment':'sandbox','deployment_id':'disposable-memory-fixture','core_deployment_id':'disposable-core','game_id':'uno-luck','identity_version':1}
    with sqlite3.connect(db) as conn:
        conn.execute('CREATE TABLE native_deployment_identity(singleton INTEGER PRIMARY KEY, identity_json TEXT NOT NULL)')
        conn.execute('INSERT INTO native_deployment_identity VALUES(1,?)',(json.dumps(identity),))
        conn.execute('CREATE TABLE fixture_records(id INTEGER PRIMARY KEY, record BLOB NOT NULL)')
        conn.executemany('INSERT INTO fixture_records(record) VALUES(zeroblob(1048576))', [() for _ in range(args.mib)])
        conn.commit()
    class Storage:
        def path(self,key): return objects/key
        def etag(self,path):
            h=hashlib.md5()
            with path.open('rb') as source:
                while chunk:=source.read(1024*1024): h.update(chunk)
            return '"'+h.hexdigest()+'"'
        def fail(self,code):
            raise ClientError({'Error':{'Code':str(code)},'ResponseMetadata':{'HTTPStatusCode':code}},'Fixture')
        def put_object(self,Bucket,Key,Body,**kwargs):
            path=self.path(Key);path.parent.mkdir(parents=True,exist_ok=True)
            with path.open('wb') as output:
                if hasattr(Body,'read'):
                    while chunk:=Body.read(1024*1024): output.write(chunk)
                else:output.write(Body)
            return {'ETag':self.etag(path)}
        def get_object(self,Bucket,Key):
            path=self.path(Key)
            if not path.is_file(): self.fail(404)
            return {'Body':path.open('rb'),'ETag':self.etag(path)}
        def head_object(self,Bucket,Key):
            path=self.path(Key)
            if not path.is_file(): self.fail(404)
            return {'ETag':self.etag(path)}
        def list_objects_v2(self,Bucket,Prefix,MaxKeys=1000,**kwargs):
            return {'IsTruncated':False,'Contents':[{'Key':str(path.relative_to(objects))} for path in objects.rglob('*') if path.is_file() and str(path.relative_to(objects)).startswith(Prefix)]}
        def delete_object(self,Bucket,Key,IfMatch=None):
            path=self.path(Key)
            if not path.is_file(): self.fail(404)
            if IfMatch!=self.etag(path): self.fail(412)
            path.unlink();return {}
    storage=Storage();boto3.client=lambda *a,**kw:storage
    os.environ.update(ENGINE_BACKUP_KEY_HEX='a5'*32,ENGINE_BACKUP_S3_ENDPOINT='https://fixture.invalid',ENGINE_BACKUP_S3_ACCESS_KEY_ID='fixture',ENGINE_BACKUP_S3_SECRET_ACCESS_KEY='fixture',ENGINE_BACKUP_RETENTION_ENABLED='true' if args.retention else 'false',ENGINE_BACKUP_RETENTION_PROBE='true',ENGINE_BACKUP_RETENTION_MODE='apply')
    import sys
    sys.path.insert(0,str(pathlib.Path(__file__).resolve().parent))
    import native_backup
    before=rss_kib();baseline_peak=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss;started=time.monotonic()
    with contextlib.redirect_stdout(open(os.devnull,'w')):
        result=native_backup.backup_once(str(db),'uno','fixture','native')
    peak=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    print(json.dumps({'requested_mib':args.mib,'snapshot_bytes':result['manifest']['size'],'retention':args.retention,'baseline_rss_kib':before,'baseline_peak_kib':baseline_peak,'peak_rss_kib':peak,'incremental_peak_kib':peak-before,'incremental_to_snapshot_ratio':round((peak-before)*1024/result['manifest']['size'],3),'elapsed_seconds':round(time.monotonic()-started,3),'verified':result['verified'],'retention_verified':result.get('retention',{}).get('conditional_delete_verified'),'transport':'disposable disk fixture, no external request','module':pathlib.Path(native_backup.__file__).name,'module_sha256':hashlib.sha256(pathlib.Path(native_backup.__file__).read_bytes()).hexdigest()}))

