import time
from django.core.management.base import BaseCommand
from django.db import close_old_connections
from game_studio.jobs import run_one
from game_studio.models import WorkerHeartbeat
from django.utils import timezone

class Command(BaseCommand):
    help='Run durable media and Math Lab jobs in an independent worker process.'
    def add_arguments(self,parser): parser.add_argument('--once',action='store_true')
    def handle(self,*args,**options):
        last=0
        while True:
            close_old_connections()
            if time.monotonic()-last>=10:
                WorkerHeartbeat.objects.update_or_create(name='studio-worker',defaults={'seen_at':timezone.now()});last=time.monotonic()
            ran=run_one()
            if options['once']: return
            if not ran: time.sleep(1)
