"""Idempotent release bootstrap; never creates credentials or grants roles."""
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import BaseCommand
from workflow.demo import seed
from workflow.models import ImportBatch
from workflow.organizer import seed_references

class Command(BaseCommand):
    def handle(self,*args,**kwargs):
        user=get_user_model().objects.filter(is_staff=True,is_active=True).order_by('id').first()
        if not user:
            self.stdout.write('Workflow: administrator absent; initialise catalogue after creating administrator.')
            return
        self.stdout.write(f'Workflow: added demo cards {len(seed(user))}')
        seed_references(user)
        if not ImportBatch.objects.filter(filename='parser-3.1.1').exists():
            call_command('import_robot_parser',user=user.username)
