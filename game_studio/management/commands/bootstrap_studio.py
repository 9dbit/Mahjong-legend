from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group, Permission
from game_studio.releases import bootstrap

class Command(BaseCommand):
    help='Import the exact legacy baseline and create Studio permission groups idempotently.'
    def handle(self,*args,**options):
        release=bootstrap()
        for name,codes in {'Owner':['edit_studio','publish_release','test_studio'],
                           'Editor':['edit_studio','test_studio'],'Tester':['test_studio']}.items():
            group,_=Group.objects.get_or_create(name=name)
            group.permissions.add(*Permission.objects.filter(content_type__app_label='game_studio',codename__in=codes))
        self.stdout.write('Baseline ready: '+str(release.id))
