"""One image, two process roles. Only the web role runs migrations."""
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
os.chdir(ROOT)
os.environ.setdefault('DJANGO_SETTINGS_MODULE','studio_server.settings')
if os.environ.get('STUDIO_ROLE','web')=='worker':
    # A first deployment may start the worker before the web migration commits.
    for attempt in range(60):
        try:
            sys.path.insert(0,str(ROOT))
            import django
            django.setup()
            from game_studio.models import ActiveRelease
            if ActiveRelease.objects.filter(pk=1).exists(): break
        except Exception:
            from django.db import connections
            connections.close_all()
        time.sleep(2)
    else: raise SystemExit('Studio schema was not ready after 120 seconds')
    subprocess.run([sys.executable,'manage.py','verify_storage'],check=True)
    os.execvp(sys.executable,[sys.executable,'manage.py','studio_worker'])
else:
    subprocess.run([sys.executable,'manage.py','migrate','--noinput'],check=True)
    subprocess.run([sys.executable,'manage.py','bootstrap_studio'],check=True)
    subprocess.run([sys.executable,'manage.py','verify_storage'],check=True)
    os.execvp('gunicorn',['gunicorn','studio_server.wsgi:application','--bind','0.0.0.0:'+os.environ.get('PORT','8080'),
                         '--workers','2','--threads','2','--timeout','130','--access-logfile','/dev/null','--error-logfile','-'])
