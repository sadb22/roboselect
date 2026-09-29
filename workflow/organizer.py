"""Manually checked reference cards, catalogue PDF page 6, received 2026-09-29.

Only identity, purpose and stated payload are transcribed. Case-wide gains are
not unit throughput. Missing operating data prevents recommending these cards.
"""
from .models import Supplier,EquipmentRevision
from .catalog import submit,publish

def seed_references(user):
    supplier,_=Supplier.objects.get_or_create(name='Каталог организатора: поставщик подлежит уточнению')
    source='ФЦ БАС: Каталог внедрения 2008 1247.pdf, страница 6; получен 29.09.2026'
    for model,payload in [('Ronavi H1500',1500),('Ronavi SR',50),('Ronavi H2000',2000)]:
        if EquipmentRevision.objects.filter(equipment__supplier=supplier,data__model=model).exists():continue
        data=dict(manufacturer='ООО «Ронави Роботикс»',model=model,configuration='Комплектация в PDF не указана',source=source,operations=['warehouse_general_transport'],rates={},payload_kg=payload)
        evidence=dict(source_file='ФЦ БАС — Каталог внедрения 2008 1247.pdf',page=6,received='2026-09-29',sha256='9567641d3a3a7bed9d2e470240b17cefacba047257b5f0b4a5311c159c580369',review_scope='Наименование, производитель, назначение, заявленная грузоподъёмность до указанного значения. Кейс внедрения не задаёт производительность единицы.')
        rev=submit(user,supplier,data,evidence)
        publish(rev,user,'published','Справочная карточка сверена с PDF. Недостаточно рабочих ТТХ для расчёта; поставщик и комплектация требуют уточнения.')
