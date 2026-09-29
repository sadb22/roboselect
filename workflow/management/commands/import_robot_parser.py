import subprocess
import sys
import tempfile
from pathlib import Path
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand,CommandError
from workflow.catalog import import_parser

class Command(BaseCommand):
    help='Офлайн-парсер → проверенный JSONL → черновики Django. Публикации нет.'
    def add_arguments(self,parser):
        parser.add_argument('--user',required=True);parser.add_argument('--folder',help='Готовая доверенная JSONL-выгрузка')
    def handle(self,*args,**options):
        user=get_user_model().objects.filter(username=options['user'],is_staff=True).first()
        if not user:raise CommandError('Требуется существующий администратор')
        parser=settings.BASE_DIR/'vendor/robot_parser'
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(options['folder']).resolve() if options['folder'] else Path(temp)
            if not options['folder']:subprocess.run([sys.executable,str(parser/'parser.py'),'--output',str(folder)],check=True,timeout=30)
            subprocess.run([sys.executable,str(parser/'validate_export.py'),str(folder)],check=True,timeout=30)
            batch=import_parser(user,folder)
        self.stdout.write(f'Импорт №{batch.pk}: {batch.rows.count()} строк; публикация только после модерации.')
