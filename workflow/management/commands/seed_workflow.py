from django.core.management.base import BaseCommand,CommandError
from django.contrib.auth import get_user_model
from workflow.demo import seed

class Command(BaseCommand):
    help='Создать явно маркированный синтетический каталог. Пароли не создаёт.'
    def add_arguments(self,parser):parser.add_argument('--user',required=True)
    def handle(self,*args,**options):
        user=get_user_model().objects.filter(username=options['user'],is_staff=True).first()
        if not user:raise CommandError('Требуется существующий администратор')
        self.stdout.write(f'Создано демонстрационных карточек: {len(seed(user))}')
