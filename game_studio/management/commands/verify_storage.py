from django.core.management.base import BaseCommand, CommandError
from game_studio.views import content_store

class Command(BaseCommand):
    help='Verify immutable storage with one harmless fixed content-addressed probe.'
    def handle(self,*args,**options):
        data=b'Mahjong Legend Studio storage verification v1\n'
        store=content_store()
        try:
            result=store.put(data,'bin')
            if store.get(result['key'])!=data: raise ValueError('Probe mismatch')
        except Exception as exc:
            raise CommandError('Private object storage verification failed: '+type(exc).__name__) from None
        self.stdout.write('Private object storage write/read SHA-256 verification: PASS')
