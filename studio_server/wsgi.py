import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'studio_server.settings')
from django.core.wsgi import get_wsgi_application
application = get_wsgi_application()

# Started per web worker; signed receipts are grouped by game, not by process.
from .gameops_heartbeat import start_bridge
_gameops_bridge_stop = start_bridge("mahjong-wild", version="0.9.2")
