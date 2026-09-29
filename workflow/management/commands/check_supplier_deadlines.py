from datetime import timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone
from workflow.models import SupplierRequest,Notice

class Command(BaseCommand):
    help='Создать внутренние уведомления о семи днях без ответа; запускать ежедневно'
    def handle(self,*args,**options):
        for part in SupplierRequest.objects.filter(state='waiting',procurement__created_at__lt=timezone.now()-timedelta(days=7)):
            Notice.objects.get_or_create(user=part.procurement.owner,url=f'/requests/{part.procurement_id}/',text=f'Поставщик {part.supplier.name} не ответил за семь дней. Доступен подбор замены.')
